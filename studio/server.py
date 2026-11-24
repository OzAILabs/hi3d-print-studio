"""Hi3D Print Studio: a clean web front end for picture -> detailed 3D -> colour print.

Runs the second ComfyUI (Python 3.12 / torch 2.8, port 8189) hidden in the background
and drives the PixelArtistry Hi3D workflow (plus WTiVo seal and the Colour Print node)
through its API. The browser gets live job state over Server-Sent Events.

    ComfyUI_py312\\python_embeded\\python.exe studio\\server.py   ->  http://127.0.0.1:7870
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import aiohttp
from aiohttp import web

# The embedded Python's ._pth file leaves the script folder off sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stages import NODE_STAGE, SHOT_LABELS, STAGE_NODES, STAGE_SECONDS, STAGES, WORK  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
COMFY_DIR = ROOT / "ComfyUI_py312"
COMFY_PY = COMFY_DIR / "python_embeded" / "python.exe"
COMFY_OUT = COMFY_DIR / "ComfyUI" / "output"
COMFY_URL = "http://127.0.0.1:8189"
# Other ComfyUI installs on this PC: "Stop everything" asks them to unload their models too,
# but only when they are idle (their work is not the studio's to cancel).
OTHER_COMFY_URLS = [u for u in os.environ.get("HI3D_OTHER_COMFY", "http://127.0.0.1:8188").split(",") if u]
JOBS = HERE / "jobs"
STATIC = HERE / "static"
BAMBU = Path(r"C:\Program Files\Bambu Studio\bambu-studio.exe")
RECOLOUR_PY = ROOT / "comfyui_nodes" / "Hi3D-ColourPrint" / "recolour.py"
SPLIT_PY = ROOT / "split" / "split_job.py"          # experimental: split a print into pieces


def split_installed():
    """The split feature is optional: it shows only once setup/install_split.sh has been run."""
    parts = ROOT / "parts"
    return ((parts / ".venv-p3sam" / "Scripts" / "python.exe").exists()
            and (parts / "weights" / "p3sam" / "p3sam.safetensors").exists())
PORT = int(os.environ.get("HI3D_STUDIO_PORT", "7870"))
CLIENT_ID = "hi3d-print-studio-" + uuid.uuid4().hex[:8]
TEMPLATE = json.loads((HERE / "workflow_api.json").read_text())
SEED_INPUTS = {"3": "seed", "18": "seed", "23": "seed", "399": "seed", "402": "seed"}

# Checkpoints: the run stops after these phases so a person can look before the long part.
# Each phase submits only the nodes its outputs need; the next phase resubmits more of the
# same graph and ComfyUI reuses everything already computed (same inputs, same seeds).
GATES = {
    "shape": {"outputs": ["902", "302", "303"], "seeds": ["3", "18", "23"],
              "reset": ["shape", "prep", "hi3d512", "hi3d1024", "paintmesh", "paint", "seal", "print"],
              "model": "coarse"},
    "detail": {"outputs": ["407"], "seeds": ["399", "402"],
               "reset": ["hi3d512", "hi3d1024", "paintmesh", "paint", "seal", "print"], "model": "detail"},
}
GATE_ORDER = ["shape", "detail"]

JOBS.mkdir(exist_ok=True)
pool = ThreadPoolExecutor(max_workers=2)
jobs: dict[str, dict] = {}
by_prompt: dict[str, str] = {}
listeners: set[asyncio.Queue] = set()
engine = {"state": "starting", "detail": "", "process": None}
web_procs: set = set()          # webmodel.py helpers currently running
ACTIVE = ("submitting", "queued", "running", "paused")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ------------------------------------------------------------------ job storage
def job_dir(jid):
    return JOBS / jid


def save_job(job):
    path = job_dir(job["id"]) / "job.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=1))
    os.replace(tmp, path)


def shape_name(job):
    return "Pixal3D" if job.get("params", {}).get("shape_model") == "pixal3d" else "TRELLIS.2"


# Shape depth (thinnest / middle side, from webmodel.py) below these reads as a slab / as shallow.
# Measured: a cardboard-cut-out result 0.08, a shallow one 0.32, good figures 0.5-0.98.
FLAT_BELOW, SHALLOW_BELOW = 0.25, 0.45


def read_shape_check(job):
    f = job_dir(job["id"]) / "web" / "coarse.glb.json"
    try:
        depth = json.loads(f.read_text())["depth"]
    except Exception:
        return
    level = "flat" if depth < FLAT_BELOW else "shallow" if depth < SHALLOW_BELOW else "ok"
    job["shape_check"] = {"depth": depth, "level": level}


def public(job):
    out = {k: v for k, v in job.items() if not k.startswith("_")}
    out["can_retry_print"] = job.get("status") == "failed" and print_step_failed(job)
    return out


def load_jobs():
    for p in sorted(JOBS.glob("*/job.json")):
        try:
            job = json.loads(p.read_text())
        except Exception:
            continue
        for k in ("_done_nodes", "_cached_nodes"):
            job[k] = set(job.get(k) or [])
        if "shape_check" not in job:
            read_shape_check(job)
        job["recolouring"] = False             # a remake cut short by a restart
        job["splitting"] = False
        jobs[job["id"]] = job


async def reattach(app):
    """After a studio restart: follow jobs ComfyUI is still running, collect finished ones."""
    session = app["session"]
    while engine["state"] != "ready":
        await asyncio.sleep(1)
    async with session.get(COMFY_URL + "/queue") as r:
        q = await r.json()
    live = {item[1] for item in q.get("queue_running", []) + q.get("queue_pending", [])}
    for job in list(jobs.values()):
        if job.get("status") == "paused":          # make sure its checkpoint preview exists
            out_dir = COMFY_OUT / "studio" / job["id"]
            for key, label in (("coarse", f"Shape ({shape_name(job)})"), ("detail", "Hi3D detail")):
                if key not in job["models"] and list(out_dir.glob(f"{key}_*.glb")):
                    asyncio.create_task(make_web_model(job["id"], out_dir, key, label))
        if job.get("status") not in ("submitting", "queued", "running"):
            continue
        pid = job.get("prompt_id")
        if pid and pid in live:
            by_prompt[pid] = job["id"]
            log(f"re-attached to running job {job['id']}")
            continue
        if await collect_finished(app, job):
            log(f"collected job {job['id']} that finished while the studio was not listening")
        else:
            job["status"] = "interrupted"
            job["error"] = "The engine stopped while this job ran."
            save_job(job)
            await broadcast(job)


async def collect_finished(app, job):
    """Finish a job from ComfyUI's history, or from the files it wrote. True if collected."""
    session = app["session"]
    pid = job.get("prompt_id")
    hist = {}
    if pid:
        try:
            async with session.get(f"{COMFY_URL}/history/{pid}") as r:
                hist = (await r.json()).get(pid) or {}
        except Exception:
            hist = {}
    if hist and (hist.get("status") or {}).get("completed") is not None:
        for nid, output in (hist.get("outputs") or {}).items():
            job["_done_nodes"].add(str(nid))
            await on_output(app, job, str(nid), output)
        ok = (hist.get("status") or {}).get("status_str") == "success"
        if not ok:
            msgs = [m for m in (hist.get("status") or {}).get("messages", []) if m[0] == "execution_error"]
            job["error"] = job.get("error") or (
                f"{msgs[0][1].get('node_type')}: {msgs[0][1].get('exception_message', '')[:600]}" if msgs
                else "The job did not finish.")
        if ok and job.get("phase", "full") != "full":
            await phase_done(app, job)          # a checkpoint phase: pause, don't finish
            return True
        if ok:
            for key in WORK:
                job["_done_nodes"] |= WORK[key]
        recompute_stages(job, time.time())
        await finish(app, job, ok=ok)
        return True
    # No history (the engine restarted): the print node leaves its report next to the files.
    out_dir = COMFY_OUT / "studio" / job["id"]
    reports = sorted(out_dir.glob("print_*_report.json"))
    if not reports:
        return False
    report_text = reports[-1].read_text(encoding="utf-8")
    for nid in ("902", "407", "386"):
        await on_output(app, job, nid, {})
    await on_output(app, job, "901", {"text": [report_text]})
    for key in WORK:
        job["_done_nodes"] |= WORK[key]
    recompute_stages(job, time.time())
    await finish(app, job, ok=True)
    return True


async def watchdog(app):
    """Events can be lost (a dropped websocket); every 20 s, ask ComfyUI about running jobs."""
    while True:
        await asyncio.sleep(20)
        if engine["state"] != "ready":
            continue
        for job in list(jobs.values()):
            if job.get("status") in ("queued", "running") and job.get("prompt_id"):
                try:
                    pid = job["prompt_id"]
                    async with app["session"].get(f"{COMFY_URL}/history/{pid}") as r:
                        hist = (await r.json()).get(pid)
                    if hist and (hist.get("status") or {}).get("completed") is not None:
                        log(f"watchdog: job {job['id']} finished without its final event; collecting")
                        await collect_finished(app, job)
                except Exception as e:
                    log(f"watchdog error: {e!r}")


async def broadcast(job):
    job["updated"] = time.time()
    msg = json.dumps({"type": "job", "job": public(job)})
    for q in list(listeners):
        if q.qsize() < 200:
            q.put_nowait(msg)


async def broadcast_engine():
    msg = json.dumps({"type": "engine", "engine": {k: v for k, v in engine.items() if k != "process"}})
    for q in list(listeners):
        q.put_nowait(msg)


# ------------------------------------------------------------------ ComfyUI engine
async def comfy_up(session):
    try:
        async with session.get(COMFY_URL + "/system_stats", timeout=aiohttp.ClientTimeout(total=3)) as r:
            return r.status == 200
    except Exception:
        return False


async def ensure_engine(app):
    session = app["session"]
    if await comfy_up(session):
        engine.update(state="ready", detail="ComfyUI engine running")
        await broadcast_engine()
        return
    engine.update(state="starting", detail="Starting the ComfyUI engine (about 20 s)")
    await broadcast_engine()
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    logf = open(HERE / "comfyui.log", "ab")
    cmd = [str(COMFY_PY), "-s", "ComfyUI/main.py", "--windows-standalone-build", "--port", "8189",
           "--disable-auto-launch"]
    # Detached, so restarting or closing the studio does not kill a job in the middle.
    flags = 0x08000000 | 0x00000200          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:
        engine["process"] = subprocess.Popen(cmd, cwd=COMFY_DIR, env=env, stdout=logf, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, creationflags=flags | 0x01000000)
    except OSError:                          # CREATE_BREAKAWAY_FROM_JOB not allowed here
        engine["process"] = subprocess.Popen(cmd, cwd=COMFY_DIR, env=env, stdout=logf, stderr=subprocess.STDOUT,
                                             stdin=subprocess.DEVNULL, creationflags=flags)
    for _ in range(180):
        await asyncio.sleep(1)
        if await comfy_up(session):
            engine.update(state="ready", detail="ComfyUI engine running")
            await broadcast_engine()
            return
        if engine["process"].poll() is not None:
            break
    engine.update(state="error", detail="The ComfyUI engine did not start; see studio/comfyui.log")
    await broadcast_engine()


async def comfy_events(app):
    """One websocket to ComfyUI for the whole studio; events are routed by prompt id."""
    session = app["session"]
    while True:
        if engine["state"] != "ready":
            await asyncio.sleep(2)
            continue
        try:
            async with session.ws_connect(f"{COMFY_URL.replace('http', 'ws')}/ws?clientId={CLIENT_ID}",
                                          heartbeat=30, max_msg_size=0) as ws:
                log("connected to ComfyUI events")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            await on_comfy(app, json.loads(msg.data))
                        except Exception as e:      # never let one bad event kill the listener
                            log(f"event error: {e!r}")
        except Exception as e:
            log(f"ComfyUI events lost ({e!r}); reconnecting")
            if not await comfy_up(session):
                engine.update(state="starting", detail="Reconnecting to the ComfyUI engine")
                await broadcast_engine()
                await ensure_engine(app)
        await asyncio.sleep(2)


def stage_state(job, key):
    return job["stages"][key]


def update_progress(job):
    """Overall fraction and ETA from stage weights, scaled by how fast this run goes."""
    done_w = total_w = 0.0
    expected_done = actual_done = 0.0
    for key, *_ in STAGES:
        w = job["_weights"][key]
        st = stage_state(job, key)
        total_w += w
        if st["state"] in ("done", "cached"):
            done_w += w
            if st["state"] == "done" and st.get("seconds"):
                expected_done += w
                actual_done += st["seconds"]
        elif st["state"] == "running":
            done_w += w * st.get("fraction", 0.0)
    job["progress"] = round(done_w / total_w, 4) if total_w else 0.0
    speed = min(2.0, max(0.5, actual_done / expected_done)) if expected_done > 30 else 1.0
    job["eta_seconds"] = int((total_w - done_w) * speed) if job["status"] == "running" else None


async def on_comfy(app, ev):
    kind, data = ev.get("type"), ev.get("data") or {}
    jid = by_prompt.get(data.get("prompt_id", ""))
    if not jid:
        return
    job = jobs[jid]
    if job.get("status") == "cancelled":       # stopped: late events must not revive it
        return
    now = time.time()
    if kind == "execution_start":
        job["status"] = "running"
        job["started"] = now
    elif kind == "execution_cached":
        cached = {str(n) for n in data.get("nodes", [])}
        job["_done_nodes"] |= cached
        job["_cached_nodes"] = cached
    elif kind == "executing":
        nid = data.get("node")
        if nid is None:
            return
        nid = str(nid)
        prev = job.get("_current_node")
        if prev:
            job["_done_nodes"].add(prev)
        job["_current_node"] = nid
    elif kind == "progress":
        nid = str(data.get("node"))
        key = NODE_STAGE.get(nid)
        if key and data.get("max") and nid in WORK[key]:
            job["_node_frac"] = (nid, data["value"] / data["max"])
            stage_state(job, key)["step"] = f"{data['value']}/{data['max']}"
    elif kind == "executed":
        nid = str(data.get("node"))
        job["_done_nodes"].add(nid)
        await on_output(app, job, nid, data.get("output") or {})
    elif kind == "execution_success":
        await phase_done(app, job)
        return
    elif kind == "execution_error":
        job["error"] = f"{data.get('node_type')}: {data.get('exception_message', '').strip()[:600]}"
        await finish(app, job, ok=False)
        return
    elif kind == "execution_interrupted":
        job["error"] = "Cancelled."
        await finish(app, job, ok=False, status="cancelled")
        return
    recompute_stages(job, now)
    update_progress(job)
    await broadcast(job)


def recompute_stages(job, now):
    """Stage states from which of each stage's work nodes have run (see stages.WORK)."""
    done, current = job["_done_nodes"], job.get("_current_node")
    cached = job.get("_cached_nodes", set())
    node_frac = job.get("_node_frac")
    for key, *_ in STAGES:
        st, work = stage_state(job, key), WORK[key]
        finished = work & done
        if work <= done:
            if st["state"] not in ("done", "cached"):
                if work <= cached:
                    st.update(state="cached", fraction=1.0)
                else:
                    st.update(state="done", fraction=1.0, seconds=round(now - st.get("started", now), 1))
                    st.pop("step", None)
            continue
        if finished or current in work:
            if st["state"] == "pending":
                st.update(state="running", started=now)
            frac = len(finished) / len(work)
            if node_frac and node_frac[0] in work and node_frac[0] not in done:
                frac += node_frac[1] / len(work)
            st["fraction"] = max(st.get("fraction", 0.0), min(0.99, frac))
            job["current_stage"] = key


async def on_output(app, job, nid, output):
    session = app["session"]
    # progress shots (PreviewImage / SaveImage results)
    for img in output.get("images", []) or []:
        if not isinstance(img, dict) or "filename" not in img:
            continue
        label = SHOT_LABELS.get(nid)
        if not label:
            continue
        params = {"filename": img["filename"], "subfolder": img.get("subfolder", ""), "type": img.get("type", "temp")}
        try:
            async with session.get(COMFY_URL + "/view", params=params) as r:
                data = await r.read()
        except Exception:
            continue
        name = f"shot_{len(job['shots']):02d}_{nid}{Path(img['filename']).suffix or '.png'}"
        (job_dir(job["id"]) / "shots").mkdir(exist_ok=True)
        (job_dir(job["id"]) / "shots" / name).write_bytes(data)
        job["shots"].append({"label": label, "file": f"shots/{name}", "stage": NODE_STAGE.get(nid), "t": time.time()})
    # 3D results
    out_dir = COMFY_OUT / "studio" / job["id"]
    model_nodes = {"902": ("coarse", f"Shape ({shape_name(job)})"), "407": ("detail", "Hi3D detail"),
                   "386": ("painted", "Painted (UltraTex)")}
    if nid in model_nodes:
        key, label = model_nodes[nid]
        asyncio.create_task(make_web_model(job["id"], out_dir, key, label))
    if nid == "901":
        texts = output.get("text") or []
        try:
            report = json.loads(texts[0]) if texts else {}
        except Exception:
            report = {}
        job["report"] = report
        job["summary"] = report.get("summary")
        if report.get("bambu", {}).get("project"):
            job["project"] = report["bambu"]["project"]
        if report.get("preview"):
            web_dir = job_dir(job["id"]) / "web"
            web_dir.mkdir(exist_ok=True)
            shutil.copyfile(report["preview"], web_dir / "print.glb")
            job["models"]["print"] = {"file": "web/print.glb", "label": "Print colours"}


async def make_web_model(jid, out_dir, key, label, faces=200_000):
    """A light copy of a saved GLB for the browser (big meshes are 100+ MB).

    Runs webmodel.py as its own process: done in here, the heavy mesh work held the
    server's interpreter for a minute and the page stopped updating.
    """
    import re

    job = jobs.get(jid)
    src = None
    for _ in range(30):
        # exact names only: "painted_*" would also match the in-between "painted_only_*" file
        files = sorted(p for p in out_dir.glob(f"{key}_*.glb") if re.fullmatch(rf"{key}_\d+_?\.glb", p.name))
        if files and files[-1].stat().st_size > 0:
            src = files[-1]
            break
        await asyncio.sleep(1)
    if src is None:
        return
    web_dir = job_dir(jid) / "web"
    web_dir.mkdir(exist_ok=True)
    dst = web_dir / f"{key}.glb"
    mode = "copy" if key == "painted" or src.stat().st_size < 4_000_000 else "clay"
    proc = await asyncio.create_subprocess_exec(
        str(COMFY_PY), "-s", str(HERE / "webmodel.py"), str(src), str(dst), str(faces), mode,
        "measure" if key == "coarse" else "",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    web_procs.add(proc)
    try:
        out, _ = await proc.communicate()
    finally:
        web_procs.discard(proc)
    if proc.returncode != 0 or not dst.exists():
        log(f"web model {key} failed: {out.decode(errors='replace')[-400:]}")
        return
    # versioned URL: a retried shape replaces the file, and the browser must not show the old one
    job["models"][key] = {"file": f"web/{key}.glb?v={int(time.time())}", "label": label}
    job["outputs"][key] = str(src)
    if key == "coarse":
        read_shape_check(job)
        if job.get("shape_check", {}).get("level") == "flat":
            log(f"job {jid}: shape looks flat (depth {job['shape_check']['depth']})")
    save_job(job)
    await broadcast(job)


loop_ref = {}


async def phase_done(app, job):
    """A phase finished: pause at its checkpoint, or finish the job after the full run."""
    phase = job.get("phase", "full")
    if phase == "full":
        await finish(app, job, ok=True)
        return
    now = time.time()
    upto = {"shape": ["cutout", "shape"], "detail": ["cutout", "shape", "prep", "hi3d512", "hi3d1024"]}[phase]
    for key in upto:                       # everything this phase ran is finished, by definition
        job["_done_nodes"] |= WORK[key]
    recompute_stages(job, now)
    job["status"] = "paused"
    job["gate"] = phase
    job["eta_seconds"] = None
    job["_current_node"] = None
    update_progress(job)
    save_job(job)
    await broadcast(job)


async def finish(app, job, ok, status=None):
    now = time.time()
    for key, *_ in STAGES:
        st = stage_state(job, key)
        if st["state"] == "running":
            st.update(state="done" if ok else "failed", seconds=round(now - st.get("started", now), 1))
            if ok:
                st["fraction"] = 1.0
    job["status"] = status or ("done" if ok else "failed")
    job["gate"] = None
    job["finished"] = now
    job["eta_seconds"] = None
    if ok:
        job["progress"] = 1.0
        if not job.get("project"):
            job["status"] = "failed"
            job["error"] = job.get("error") or "The print file was not written; see the report."
    save_job(job)
    await broadcast(job)


# ------------------------------------------------------------------ submitting jobs
def build_prompt(job, image_name, phase="full"):
    p = copy.deepcopy(TEMPLATE)
    s = job["params"]
    for node in p.values():
        prefix = node["inputs"].get("filename_prefix")
        if isinstance(prefix, str) and "JOB" in prefix:
            node["inputs"]["filename_prefix"] = prefix.replace("JOB", job["id"])
    p["122"]["inputs"]["image"] = image_name
    p["316"]["inputs"]["value"] = s["shape_model"] == "trellis2"
    steps = 25 if s["colour_quality"] == "best" else 4
    p["358"]["inputs"]["steps"] = p["358"]["inputs"]["extra_steps"] = steps
    for nid, field in SEED_INPUTS.items():
        p[nid]["inputs"][field] = job["seeds"][nid]
    pr = p["901"]["inputs"]
    pr.update(height_mm=float(s["height_mm"]), colours=int(s["colours"]), printer=s["printer"])
    if s.get("ink_cleanup"):
        # Experimental: the painter and the print step's palette see the picture with its
        # cartoon outlines replaced by the colours beside them (the shape still uses the original).
        p["904"] = {"class_type": "Hi3DInkCleanup",
                    "inputs": {"image": ["122", 0], "mask": ["248", 0], "line_width": 0.008}}
        p["905"] = {"class_type": "ImageCropToMask",
                    "inputs": dict(p["312"]["inputs"], images=["904", 0])}
        p["906"] = {"class_type": "PreviewImage", "inputs": {"images": ["905", 0]}}
        p["375"]["inputs"]["reference"] = ["904", 0]
        pr["picture"] = ["905", 0]
    if phase == "full":
        return p
    # Only what this checkpoint (and the ones before it) needs.
    outputs = []
    for g in GATE_ORDER[:GATE_ORDER.index(phase) + 1]:
        outputs += GATES[g]["outputs"]
    keep, stack = set(), list(outputs)
    while stack:
        nid = stack.pop()
        if nid in keep:
            continue
        keep.add(nid)
        stack += [v[0] for v in p[nid]["inputs"].values() if isinstance(v, list) and len(v) == 2]
    return {nid: node for nid, node in p.items() if nid in keep}


def first_phase(job):
    gates = [g for g in GATE_ORDER if g in job["params"].get("gates", [])]
    return gates[0] if gates else "full"


def next_phase(job):
    gates = [g for g in GATE_ORDER if g in job["params"].get("gates", [])]
    cur = job.get("phase")
    later = [g for g in gates if GATE_ORDER.index(g) > GATE_ORDER.index(cur)] if cur in GATE_ORDER else []
    return later[0] if later else "full"


async def submit(app, job, image_path):
    """Upload the picture once, then start the first phase."""
    session = app["session"]
    if engine["state"] != "ready":
        await ensure_engine(app)
    form = aiohttp.FormData()
    form.add_field("image", image_path.read_bytes(), filename=f"{job['id']}{image_path.suffix}")
    form.add_field("subfolder", "studio")
    form.add_field("overwrite", "true")
    async with session.post(COMFY_URL + "/upload/image", data=form) as r:
        up = await r.json()
    if job.get("status") == "cancelled":
        return
    job["image_name"] = f"{up.get('subfolder', 'studio')}/{up['name']}" if up.get("subfolder") else up["name"]
    await submit_phase(app, job, first_phase(job))


async def submit_phase(app, job, phase):
    if job.get("status") == "cancelled":
        return
    prompt = build_prompt(job, job["image_name"], phase)
    async with app["session"].post(COMFY_URL + "/prompt", json={"prompt": prompt, "client_id": CLIENT_ID}) as r:
        res = await r.json()
    if "prompt_id" not in res:
        job["status"] = "failed"
        job["error"] = "ComfyUI refused the job: " + json.dumps(res.get("error") or res.get("node_errors"))[:600]
    else:
        job["phase"] = phase
        job["gate"] = None
        job["prompt_id"] = res["prompt_id"]
        job.setdefault("prompt_ids", []).append(res["prompt_id"])
        by_prompt[res["prompt_id"]] = job["id"]
        job["status"] = "queued"
    save_job(job)
    await broadcast(job)


def new_job(params, image_bytes, filename):
    jid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    d = job_dir(jid)
    d.mkdir(parents=True)
    ext = Path(filename).suffix.lower() if Path(filename).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") else ".png"
    (d / f"input{ext}").write_bytes(image_bytes)
    weights = dict(STAGE_SECONDS)
    if params["colour_quality"] != "best":
        weights["paint"] = 300
    job = {
        "id": jid, "name": params.get("name") or Path(filename).stem, "created": time.time(),
        "status": "submitting", "params": params, "input": f"input{ext}", "progress": 0.0,
        "eta_seconds": None, "current_stage": None, "error": None, "shots": [], "models": {},
        "outputs": {}, "summary": None, "project": None,
        "stages": {key: {"state": "pending", "fraction": 0.0, "title": title,
                         "description": desc.replace("TRELLIS.2", "Pixal3D") if params["shape_model"] == "pixal3d" else desc}
                   for key, title, desc, _, _ in STAGES},
        "_weights": weights, "_done_nodes": set(), "_current_node": None,
        "seeds": {nid: params["seed"] + int(nid) for nid in SEED_INPUTS},
        "phase": None, "gate": None,
    }
    jobs[jid] = job
    return job, d / f"input{ext}"


# json can't store sets: keep them private and rebuild on load
def _default(o):
    if isinstance(o, set):
        return sorted(o)
    raise TypeError


_dumps = json.dumps
json.dumps = lambda obj, **kw: _dumps(obj, default=_default, **{k: v for k, v in kw.items() if k != "default"})


# ------------------------------------------------------------------ HTTP API
async def index(request):
    return web.FileResponse(STATIC / "index.html")


async def api_jobs(request):
    items = sorted(jobs.values(), key=lambda j: j["created"], reverse=True)
    return web.json_response([public(j) for j in items], dumps=json.dumps)


async def api_job(request):
    job = jobs.get(request.match_info["jid"])
    if not job:
        raise web.HTTPNotFound()
    return web.json_response(public(job), dumps=json.dumps)


async def api_create(request):
    reader = await request.multipart()
    params, image, filename = {}, None, "picture.png"
    async for part in reader:
        if part.name == "image":
            filename = part.filename or filename
            image = await part.read()
        else:
            params[part.name] = (await part.text()).strip()
    if not image:
        raise web.HTTPBadRequest(text="No picture")
    clean = {
        "name": params.get("name", "")[:80],
        "height_mm": max(30.0, min(180.0, float(params.get("height_mm", 100)))),
        "colours": max(1, min(4, int(params.get("colours", 4)))),
        "printer": params.get("printer", "A1 mini 0.4"),
        "colour_quality": "best" if params.get("colour_quality", "best") == "best" else "fast",
        "shape_model": "pixal3d" if params.get("shape_model") == "pixal3d" else "trellis2",
        "seed": int(params["seed"]) if params.get("seed", "").isdigit() else random.randint(1, 10_000_000),
        "gates": [g for g in GATE_ORDER if params.get(f"gate_{g}", "1") == "1"],
        "ink_cleanup": params.get("ink_cleanup") == "1",
        "batch": params.get("batch", "")[:40],
    }
    job, image_path = new_job(clean, image, filename)
    save_job(job)
    await broadcast(job)
    asyncio.create_task(submit(request.app, job, image_path))
    return web.json_response(public(job), dumps=json.dumps)


async def api_continue(request):
    job = jobs.get(request.match_info["jid"])
    if not job or job.get("status") != "paused":
        raise web.HTTPBadRequest(text="This job is not waiting at a checkpoint")
    await submit_phase(request.app, job, next_phase(job))
    return web.json_response({"ok": True})


async def api_retry(request):
    """Run the checkpoint's stage again with new seeds (a different shape / different detail)."""
    job = jobs.get(request.match_info["jid"])
    if not job or job.get("status") != "paused" or job.get("gate") not in GATES:
        raise web.HTTPBadRequest(text="This job is not waiting at a checkpoint")
    gate = GATES[job["gate"]]
    for nid in gate["seeds"]:
        job["seeds"][nid] = random.randint(1, 10_000_000)
    for key in gate["reset"]:
        job["stages"][key].update(state="pending", fraction=0.0)
        for k in ("seconds", "step", "started"):
            job["stages"][key].pop(k, None)
        job["_done_nodes"] -= WORK[key]
    job["models"].pop(gate["model"], None)
    if gate["model"] == "coarse":
        job.pop("shape_check", None)
    job["tries"] = job.get("tries", 1) + 1
    await submit_phase(request.app, job, job["gate"])
    return web.json_response({"ok": True})


async def api_cancel(request):
    job = jobs.get(request.match_info["jid"])
    if not job:
        raise web.HTTPNotFound()
    if job.get("status") == "paused":
        job["error"] = "Stopped at the checkpoint."
        await finish(request.app, job, ok=False, status="cancelled")
        return web.json_response({"ok": True})
    session = request.app["session"]
    pid = job.get("prompt_id")
    async with session.get(COMFY_URL + "/queue") as r:
        q = await r.json()
    running = [item[1] for item in q.get("queue_running", [])]
    if pid in running:
        await session.post(COMFY_URL + "/interrupt", json={"prompt_id": pid})
    elif pid:
        await session.post(COMFY_URL + "/queue", json={"delete": [pid]})
        job["error"] = "Cancelled."
        await finish(request.app, job, ok=False, status="cancelled")
    return web.json_response({"ok": True})


def gpu_memory():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().split(", ")
        return int(out[0]), int(out[1])
    except Exception:
        return None


def kill_engine_tree():
    """Kill the studio's ComfyUI (whoever started it) and everything it launched."""
    import psutil
    port = int(COMFY_URL.rsplit(":", 1)[1])
    pids = {c.pid for c in psutil.net_connections("tcp")
            if c.laddr and c.laddr.port == port and c.status == psutil.CONN_LISTEN and c.pid}
    if engine.get("process") and engine["process"].poll() is None:
        pids.add(engine["process"].pid)
    procs = []
    for pid in pids:
        try:
            parent = psutil.Process(pid)
            procs += parent.children(recursive=True) + [parent]
        except psutil.NoSuchProcess:
            pass
    for pr in procs:
        try:
            pr.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=15)
    engine["process"] = None
    return len(procs)


async def api_stop_all(request):
    """The master stop: cancel every job, stop the engine's work and free the graphics memory.

    ComfyUI only notices an interrupt between steps; a long node (sealing, the print step,
    Bambu's slicer) can run for minutes without looking. If the engine is still busy after
    a short wait, it is restarted, which always stops the work and frees its memory.
    """
    app = request.app
    session = app["session"]
    before = gpu_memory()
    stopped = []
    for job in jobs.values():
        if job.get("status") in ACTIVE:
            job["error"] = "Stopped with Stop everything."
            await finish(app, job, ok=False, status="cancelled")
            stopped.append(job["id"])
    for proc in list(web_procs):
        try:
            proc.kill()
        except ProcessLookupError:
            pass

    restarted = False
    timeout = aiohttp.ClientTimeout(total=10)
    if await comfy_up(session):
        try:
            await session.post(COMFY_URL + "/queue", json={"clear": True}, timeout=timeout)
            await session.post(COMFY_URL + "/interrupt", json={}, timeout=timeout)
            busy = True
            for _ in range(10):
                async with session.get(COMFY_URL + "/queue", timeout=timeout) as r:
                    q = await r.json()
                busy = bool(q.get("queue_running") or q.get("queue_pending"))
                if not busy:
                    break
                await asyncio.sleep(1)
        except Exception:
            busy = True
        if busy:
            log("stop everything: engine still busy after the interrupt, restarting it")
            engine.update(state="starting", detail="Restarting the engine to stop its work")
            await broadcast_engine()
            await asyncio.get_running_loop().run_in_executor(pool, kill_engine_tree)
            restarted = True
            asyncio.create_task(ensure_engine(app))
        else:
            await session.post(COMFY_URL + "/free", json={"unload_models": True, "free_memory": True},
                               timeout=timeout)

    others = []
    for url in OTHER_COMFY_URLS:
        try:
            async with session.get(url + "/queue", timeout=aiohttp.ClientTimeout(total=3)) as r:
                q = await r.json()
            if q.get("queue_running") or q.get("queue_pending"):
                others.append({"url": url, "freed": False, "why": "busy with its own work"})
                continue
            await session.post(url + "/free", json={"unload_models": True, "free_memory": True},
                               timeout=aiohttp.ClientTimeout(total=10))
            others.append({"url": url, "freed": True})
        except Exception:
            pass                                    # not running

    await asyncio.sleep(2)                          # let the driver hand the memory back
    after = gpu_memory()
    log(f"stop everything: {len(stopped)} job(s) stopped, engine restarted={restarted}, "
        f"GPU {before and before[0]} -> {after and after[0]} MiB")
    return web.json_response({"stopped": stopped, "engine_restarted": restarted, "others": others,
                              "gpu_before": before and before[0], "gpu_after": after and after[0],
                              "gpu_total": after and after[1]})


async def api_recolour(request):
    """Remake the print file with the filament colours the person chose (no re-painting)."""
    job = jobs.get(request.match_info["jid"])
    if not job or not (job.get("status") == "done" and job.get("project") or print_step_failed(job)):
        raise web.HTTPBadRequest(text="Only a finished print can be recoloured")
    if job.get("recolouring"):
        raise web.HTTPBadRequest(text="Already remaking this print file")
    body = await request.json()
    palette = [str(h) for h in body.get("palette", [])]
    if not 1 <= len(palette) <= 4 or not all(len(h) == 7 and h[0] == "#" and
                                            all(c in "0123456789abcdefABCDEF" for c in h[1:]) for h in palette):
        raise web.HTTPBadRequest(text="Choose 1 to 4 colours")
    painted_3mf = first_painted_3mf(job)
    painted_glb = job.get("outputs", {}).get("painted")
    if not painted_3mf or not painted_3mf.exists() or not painted_glb or not Path(painted_glb).exists():
        raise web.HTTPNotFound(text="The painted files for this print are missing")
    if job.get("project"):
        job.setdefault("first_project", job["project"])
    n = job.get("recolours", 0) + 1
    name = f"print_recolour{n}"
    job.update(recolouring=True, recolour_error=None)
    save_job(job)
    await broadcast(job)
    asyncio.create_task(run_recolour(job, painted_3mf, painted_glb, name, palette, n))
    return web.json_response({"ok": True})


def first_painted_3mf(job):
    """The painted 3MF the print step wrote (it holds the final print mesh)."""
    if job.get("first_project") or job.get("project"):
        first = Path(job.get("first_project") or job["project"])
        return first.with_name(first.name.replace("_bambu.3mf", "_painted.3mf"))
    found = sorted((COMFY_OUT / "studio" / job["id"]).glob("print_0*_painted.3mf"))
    return found[-1] if found else None


def print_step_failed(job):
    """Everything was made, but Bambu's slice check refused the print file: it can be retried."""
    p = first_painted_3mf(job)
    return (job.get("status") == "failed" and not job.get("project") and bool((job.get("summary") or {}).get("palette"))
            and p is not None and p.exists() and bool(job.get("outputs", {}).get("painted")))


async def run_recolour(job, painted_3mf, painted_glb, name, palette, n):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    proc = await asyncio.create_subprocess_exec(
        str(COMFY_PY), "-s", str(RECOLOUR_PY), str(painted_3mf), str(painted_glb), str(painted_3mf.parent), name,
        job["params"]["printer"], str(float(TEMPLATE["901"]["inputs"]["min_island_mm2"])), *palette,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    web_procs.add(proc)
    try:
        out, _ = await proc.communicate()
    finally:
        web_procs.discard(proc)
    job["recolouring"] = False
    try:
        report = json.loads(out.decode(errors="replace").strip().splitlines()[-1])
        project = report.get("bambu", {}).get("project")
        if not project:
            raise ValueError(report.get("bambu", {}).get("error") or "no project written")
    except Exception as e:
        job["recolour_error"] = f"Could not remake the print file: {e}"[:400]
        log(f"recolour {job['id']} failed: {out.decode(errors='replace')[-600:]}")
        save_job(job)
        await broadcast(job)
        return
    job["recolours"] = n
    if job.get("status") == "failed":                   # a print file that failed the slice check, now made
        job.update(status="done", error=None, progress=1.0)
        job["stages"]["print"].update(state="done", fraction=1.0)
    job["report"] = report
    job["summary"] = report.get("summary")
    job["project"] = project
    if report.get("preview"):
        web_dir = job_dir(job["id"]) / "web"
        shutil.copyfile(report["preview"], web_dir / "print.glb")
        job["models"]["print"] = {"file": f"web/print.glb?v={int(time.time())}", "label": "Print colours"}
    log(f"recoloured {job['id']}: {palette} -> {job['summary'].get('print_hours')} h")
    save_job(job)
    await broadcast(job)


async def api_split(request):
    """Experimental: cut a finished print into pegged pieces along P3-SAM's parts."""
    job = jobs.get(request.match_info["jid"])
    if not job or job.get("status") != "done" or not job.get("project"):
        raise web.HTTPBadRequest(text="Only a finished print can be split")
    if job.get("splitting"):
        raise web.HTTPBadRequest(text="Already splitting this print")
    if not split_installed():
        raise web.HTTPBadRequest(text="Split into pieces is not installed: run setup/install_split.sh")
    busy = [j for j in jobs.values() if j.get("status") in ("submitting", "queued", "running") or j.get("splitting")]
    if busy:
        raise web.HTTPBadRequest(text="Wait until nothing else is running: the part finder needs the whole graphics card")
    pieces = int((await request.json()).get("pieces", 4))
    if not 2 <= pieces <= 8:
        raise web.HTTPBadRequest(text="Choose 2 to 8 pieces")
    painted = first_painted_3mf(job)
    if not painted or not painted.exists():
        raise web.HTTPNotFound(text="The painted print file for this job is missing")
    job.update(splitting=True, split_error=None)
    save_job(job)
    await broadcast(job)
    asyncio.create_task(run_split(request.app, job, painted, pieces))
    return web.json_response({"ok": True})


async def run_split(app, job, painted, pieces):
    try:      # the part finder needs ~21 GB: ask the idle engine to let go of its models first
        await app["session"].post(COMFY_URL + "/free", json={"unload_models": True, "free_memory": True},
                                  timeout=aiohttp.ClientTimeout(total=10))
    except Exception:
        pass
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    palette = ",".join((job.get("summary") or {}).get("palette") or [])
    proc = await asyncio.create_subprocess_exec(
        str(COMFY_PY), "-s", str(SPLIT_PY), str(painted), str(job_dir(job["id"]) / "split"), str(pieces), palette,
        job["params"]["printer"], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    web_procs.add(proc)
    try:
        out, _ = await proc.communicate()
    finally:
        web_procs.discard(proc)
    job["splitting"] = False
    text = out.decode(errors="replace").strip()
    try:
        result = json.loads(text.splitlines()[-1])
        if not result.get("project"):
            raise ValueError(result.get("message") or "no project written")
        result["asked"] = pieces
        job["split"] = result
        log(f"split {job['id']} into {result['pieces']} pieces")
    except Exception as e:
        last = text.splitlines()[-1] if text else str(e)
        job["split_error"] = f"Could not split this print: {last}"[:400]
        log(f"split {job['id']} failed: {text[-800:]}")
    save_job(job)
    await broadcast(job)


async def api_open_bambu(request):
    job = jobs.get(request.match_info["jid"])
    which = request.query.get("what")
    path = (job.get("split") or {}).get("project") if job and which == "split" else (job or {}).get("project")
    if not job or not path or not Path(path).exists():
        raise web.HTTPNotFound(text="No project file for this job")
    if not BAMBU.exists():
        raise web.HTTPNotFound(text="Bambu Studio is not installed")
    subprocess.Popen([str(BAMBU), path], close_fds=True)
    return web.json_response({"ok": True})


async def api_open_folder(request):
    job = jobs.get(request.match_info["jid"])
    if not job:
        raise web.HTTPNotFound()
    folder = Path(job["project"]).parent if job.get("project") else job_dir(job["id"])
    subprocess.Popen(["explorer", str(folder)])
    return web.json_response({"ok": True})


async def api_delete(request):
    jid = request.match_info["jid"]
    job = jobs.get(jid)
    if not job or job["status"] in ("queued", "running", "submitting"):
        raise web.HTTPBadRequest(text="Only finished jobs can be removed")
    jobs.pop(jid)
    shutil.rmtree(job_dir(jid), ignore_errors=True)
    shutil.rmtree(COMFY_OUT / "studio" / jid, ignore_errors=True)
    msg = json.dumps({"type": "removed", "id": jid})
    for q in list(listeners):
        q.put_nowait(msg)
    return web.json_response({"ok": True})


async def api_file(request):
    jid, rel = request.match_info["jid"], request.match_info["path"]
    if rel == "split.3mf":
        job = jobs.get(jid)
        path = (job or {}).get("split", {}).get("project")
        if path and Path(path).exists():
            return web.FileResponse(path, headers={
                "Content-Disposition": f'attachment; filename="{job["name"]}_pieces_bambu.3mf"'})
        raise web.HTTPNotFound()
    if rel == "project.3mf":
        job = jobs.get(jid)
        if job and job.get("project"):
            return web.FileResponse(job["project"], headers={
                "Content-Disposition": f'attachment; filename="{job["name"]}_bambu.3mf"'})
        raise web.HTTPNotFound()
    base = job_dir(jid).resolve()
    path = (base / rel).resolve()
    if base not in path.parents or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


async def api_status(request):
    gpu = None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip().split(", ")
        gpu = {"name": out[0], "util": int(out[1]), "mem_used": int(out[2]), "mem_total": int(out[3])}
    except Exception:
        pass
    return web.json_response({"engine": {k: v for k, v in engine.items() if k != "process"}, "gpu": gpu,
                              "split_installed": split_installed()})


async def api_events(request):
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    q: asyncio.Queue = asyncio.Queue()
    listeners.add(q)
    try:
        await resp.write(f"data: {json.dumps({'type': 'engine', 'engine': {k: v for k, v in engine.items() if k != 'process'}})}\n\n".encode())
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=15)
                await resp.write(f"data: {msg}\n\n".encode())
            except asyncio.TimeoutError:
                await resp.write(b": ping\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        listeners.discard(q)
    return resp


async def on_startup(app):
    loop_ref["loop"] = asyncio.get_running_loop()
    app["session"] = aiohttp.ClientSession()
    load_jobs()
    asyncio.create_task(ensure_engine(app))
    app["events"] = asyncio.create_task(comfy_events(app))
    asyncio.create_task(reattach(app))
    asyncio.create_task(watchdog(app))


async def on_cleanup(app):
    await app["session"].close()


@web.middleware
async def no_cache(request, handler):
    """The page and its scripts change with updates; never let the browser serve stale ones."""
    resp = await handler(request)
    if request.path == "/" or request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


def main():
    app = web.Application(client_max_size=64 * 1024 * 1024, middlewares=[no_cache])
    app.add_routes([
        web.get("/", index),
        web.get("/api/jobs", api_jobs),
        web.post("/api/jobs", api_create),
        web.get("/api/jobs/{jid}", api_job),
        web.post("/api/jobs/{jid}/cancel", api_cancel),
        web.post("/api/jobs/{jid}/continue", api_continue),
        web.post("/api/jobs/{jid}/retry", api_retry),
        web.post("/api/jobs/{jid}/open-bambu", api_open_bambu),
        web.post("/api/jobs/{jid}/recolour", api_recolour),
        web.post("/api/jobs/{jid}/split", api_split),
        web.post("/api/jobs/{jid}/open-folder", api_open_folder),
        web.delete("/api/jobs/{jid}", api_delete),
        web.get("/api/status", api_status),
        web.post("/api/stop-all", api_stop_all),
        web.get("/api/events", api_events),
        web.get("/files/{jid}/{path:.+}", api_file),
        web.static("/static", STATIC),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    log(f"Hi3D Print Studio on http://127.0.0.1:{PORT}")
    web.run_app(app, host="127.0.0.1", port=PORT, print=None)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
