// Hi3D Print Studio front end: live job state over Server-Sent Events, no framework.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const state = { jobs: {}, sel: null, tab: "live", model: null, autoTab: true, file: null };

const STAGE_ICONS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];
const ACTIVE = new Set(["submitting", "queued", "running", "paused"]);
const GATE_TEXT = {
  shape: ["Check the shape",
    "Spin it in the 3D view. Wrong pose, an extra tail, a missing arm or a strange back? Try another shape (about 2 minutes) instead of waiting for the whole run.",
    "coarse"],
  detail: ["Check the detail",
    "Hi3D has added the fine detail. If the face or small parts look off, try another detail pass (about 3 minutes) before the long painting step.",
    "detail"],
};

function fmtDur(s) {
  if (s == null || !isFinite(s)) return "";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return `${h} h ${m} min`;
  if (m) return `${m} min ${String(sec).padStart(2, "0")} s`;
  return `${sec} s`;
}
const fmtDate = (t) => new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const statusText = { submitting: "Starting", queued: "Queued", running: "Running", paused: "Waiting for you", done: "Done", failed: "Failed", cancelled: "Cancelled", interrupted: "Interrupted" };
const fileUrl = (job, rel) => `/files/${job.id}/${rel}`;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.hidden = true), Math.max(3200, msg.length * 70));
}

// ---------------------------------------------------------------- new print form
function initForm() {
  const drop = $("#drop"), file = $("#file");
  const setFile = (f) => {
    if (!f || !f.type.startsWith("image/")) return;
    state.file = f;
    $("#dropImg").src = URL.createObjectURL(f);
    drop.classList.add("has");
    if (!$("#name").value) $("#name").placeholder = f.name.replace(/\.[^.]+$/, "");
    $("#go").disabled = false;
  };
  file.addEventListener("change", () => setFile(file.files[0]));
  ["dragenter", "dragover"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => drop.addEventListener(e, (ev) => { ev.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (ev) => setFile(ev.dataTransfer.files[0]));
  $("#height").addEventListener("input", (e) => ($("#heightVal").textContent = `${e.target.value} mm`));
  $$(".seg").forEach((seg) => seg.addEventListener("click", (e) => {
    if (e.target.tagName !== "BUTTON") return;
    $$("button", seg).forEach((b) => b.classList.toggle("on", b === e.target));
  }));
  $("#newForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.file) return;
    const fd = new FormData();
    fd.append("image", state.file, state.file.name);
    fd.append("name", $("#name").value || $("#name").placeholder);
    fd.append("height_mm", $("#height").value);
    fd.append("colours", $("#colours .on").textContent);
    fd.append("colour_quality", $("#quality .on").dataset.v);
    fd.append("shape_model", $("#shape .on").dataset.v);
    fd.append("seed", $("#seed").value.trim());
    fd.append("gate_shape", $("#gateShape").checked ? "1" : "0");
    fd.append("gate_detail", $("#gateDetail").checked ? "1" : "0");
    $("#go").disabled = true;
    $("#go").textContent = "Sending…";
    try {
      const r = await fetch("/api/jobs", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const job = await r.json();
      state.jobs[job.id] = job;
      select(job.id);
      toast("Started. You can leave this page open or come back later.");
    } catch (err) {
      toast("Could not start: " + err.message);
    } finally {
      $("#go").textContent = "Make it";
      $("#go").disabled = !state.file;
    }
  });
}

// ---------------------------------------------------------------- history list
function renderList() {
  const jobs = Object.values(state.jobs).sort((a, b) => b.created - a.created);
  $("#count").textContent = jobs.length ? `· ${jobs.length}` : "";
  const list = $("#list");
  if (!jobs.length) {
    list.innerHTML = `<div class="muted" style="padding:8px 4px">Your prints will appear here.</div>`;
    return;
  }
  list.innerHTML = jobs.map((j) => `
    <div class="item ${j.id === state.sel ? "sel" : ""}" data-id="${j.id}">
      <img src="${fileUrl(j, j.input)}" alt="" loading="lazy">
      <div style="min-width:0">
        <div class="t">${escapeHtml(j.name)}</div>
        <div class="s"><span class="dot ${j.status}"></span>${statusText[j.status] || j.status} · ${fmtDate(j.created)}</div>
        ${ACTIVE.has(j.status) ? `<div class="mini"><div style="width:${(j.progress * 100).toFixed(1)}%"></div></div>` : ""}
      </div>
    </div>`).join("");
  $$(".item", list).forEach((el) => el.addEventListener("click", () => select(el.dataset.id)));
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------------------------------------------------------------- job view
function select(id) {
  state.sel = id;
  state.model = null;
  state.autoTab = true;
  state.lastShot = null;
  state._modelCount = undefined;          // the first render of a job sets the baseline
  setTab("live");
  render();
}

function setTab(tab) {
  state.tab = tab;
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  $$(".tabBody").forEach((b) => (b.hidden = b.dataset.body !== tab));
}

function render() {
  renderList();
  const job = state.jobs[state.sel];
  $("#empty").hidden = !!job;
  $("#job").hidden = !job;
  if (!job) return;

  $("#jobThumb").src = fileUrl(job, job.input);
  $("#jobName").textContent = job.name;
  const chip = $("#jobStatus");
  chip.className = `chip ${job.status}`;
  chip.textContent = statusText[job.status] || job.status;
  const p = job.params || {};
  $("#jobMeta").textContent = [`${p.height_mm} mm`, `${p.colours} colours`, p.colour_quality === "best" ? "best colour" : "fast colour",
    p.shape_model === "pixal3d" ? "Pixal3D" : "TRELLIS.2", `seed ${p.seed}`, fmtDate(job.created)].join(" · ");
  const pct = Math.round((job.progress || 0) * 100);
  const bar = $("#jobBar");
  bar.style.width = `${pct}%`;
  bar.classList.toggle("live", job.status === "running" || job.status === "queued");
  $("#jobPct").textContent = `${pct}%`;
  const elapsed = job.started ? ((job.finished || Date.now() / 1000) - job.started) : null;
  $("#jobEta").textContent = job.status === "running"
    ? `${fmtDur(elapsed)} elapsed${job.eta_seconds != null ? ` · about ${fmtDur(job.eta_seconds)} left` : ""}`
    : job.status === "paused" ? "paused at a checkpoint"
    : job.finished && job.started ? `took ${fmtDur(elapsed)}` : job.status === "queued" ? "waiting for the GPU" : "";
  $("#cancelBtn").hidden = !ACTIVE.has(job.status) || job.status === "paused";
  $("#removeBtn").hidden = ACTIVE.has(job.status);

  renderGate(job);
  renderStages(job);
  renderLive(job);
  renderModels(job);
  renderShots(job);
  renderResult(job);
  const err = $("#errorBox");
  err.hidden = !job.error || job.status === "done";
  err.textContent = job.error ? `Stopped: ${job.error}` : "";
}

// The shape model's name, for jobs made before the studio labelled Pixal3D runs correctly.
function shapeName(job, text) {
  return (job.params || {}).shape_model === "pixal3d" ? String(text).replace("TRELLIS.2", "Pixal3D") : text;
}

// How deep the shape came out (measured by the studio when the shape model is ready).
function slabText(job) {
  const c = job.shape_check;
  if (!c || c.level === "ok") return null;
  const pct = Math.round(c.depth * 100);
  const pixal = (job.params || {}).shape_model === "pixal3d";
  const fix = pixal ? "Try another for a new seed." : "Try another for a new seed, or start again with Pixal3D, which handles flat cartoons better.";
  return c.level === "flat"
    ? { cls: "flat", text: `This shape looks like a flat slab: it is only ${pct}% as deep as it is wide, so it would print like a cardboard cut-out. ${fix}` }
    : { cls: "", text: `This shape is shallow: ${pct}% as deep as it is wide. Turn it sideways to check. ${fix}` };
}

function renderGate(job) {
  const box = $("#gate");
  const g = job.status === "paused" && GATE_TEXT[job.gate];
  box.hidden = !g;
  if (!g) { state.gateShown = null; return; }
  const [title, body, model] = g;
  $("#gateTitle").textContent = title + (job.tries > 1 ? ` · try ${job.tries}` : "");
  $("#gateBody").textContent = body;
  const slab = job.gate === "shape" ? slabText(job) : null;
  $("#gateWarn").hidden = !slab;
  if (slab) { $("#gateWarn").className = `gateWarn ${slab.cls}`; $("#gateWarn").textContent = slab.text; }
  const key = `${job.id}:${job.gate}:${job.tries || 1}`;
  if (state.gateShown !== key) {            // first time at this checkpoint: show its model
    state.gateShown = key;
    state.model = model;
    state.wantModel = model;                 // switch to it as soon as its preview is ready
    state._userPicked = true;
    state.autoTab = false;
    setTab("model");
  }
  if (!(job.models || {})[model]) $("#modelEmpty").textContent = "Preparing the 3D preview…";
  ["#gateGo", "#gateRetry", "#gateStop"].forEach((s) => ($(s).disabled = false));
}

function renderStages(job) {
  const order = Object.keys(job.stages);
  $("#stages").innerHTML = order.map((k, i) => {
    const s = job.stages[k];
    const icon = s.state === "done" || s.state === "cached" ? "✓" : s.state === "failed" ? "!" : STAGE_ICONS[i];
    const time = s.state === "running" && s.started ? fmtDur(Date.now() / 1000 - s.started)
      : s.seconds ? fmtDur(s.seconds) : s.state === "cached" ? "reused" : "";
    const step = s.state === "running" && s.step ? ` · step ${s.step}` : "";
    return `<li class="stage ${s.state}">
      <span class="ico">${icon}</span>
      <div><div class="nm">${s.title}</div><div class="ds">${shapeName(job, s.description)}${step}</div></div>
      <span class="tm">${time}</span>
      <div class="sb"><div style="width:${Math.round((s.fraction || 0) * 100)}%"></div></div>
    </li>`;
  }).join("");
}

function latestVisual(job) {
  const shots = job.shots || [];
  return shots.length ? shots[shots.length - 1] : null;
}

function renderLive(job) {
  const live = $("#live");
  const shot = latestVisual(job);
  const key = shot ? shot.file : `wait-${job.status}-${job.current_stage}`;
  if (state.lastShot === key) return;
  state.lastShot = key;
  if (shot) {
    live.innerHTML = `<img src="${fileUrl(job, shot.file)}" alt=""><span class="cap">${escapeHtml(shot.label)}</span>`;
  } else if (ACTIVE.has(job.status)) {
    const st = job.current_stage ? job.stages[job.current_stage] : null;
    live.innerHTML = `<div class="wait"><div class="spinner"></div><div>${st ? escapeHtml(st.description) : "Getting ready"}…</div></div>`;
  } else {
    live.innerHTML = `<img src="${fileUrl(job, job.input)}" alt=""><span class="cap">Your picture</span>`;
  }
}

const MODEL_ORDER = ["coarse", "detail", "painted", "print"];
function renderModels(job) {
  const models = job.models || {};
  const keys = MODEL_ORDER.filter((k) => models[k]);
  $('#tabs [data-tab="model"]').textContent = keys.length ? `3D (${keys.length})` : "3D";
  // A new model arrived: show it, unless the person chose a tab themselves.
  if (state.autoTab && keys.length > (state._modelCount ?? 0) && state._modelCount !== undefined) setTab("model");
  state._modelCount = keys.length;
  $("#modelEmpty").hidden = keys.length > 0;
  // warn under the 3D view while the shape is shown (the checkpoint card says it too)
  const slab = slabText(job);
  const showSlab = !!slab && keys.length > 0 && state.model === "coarse" && !(job.status === "paused" && job.gate === "shape");
  $("#modelWarn").hidden = !showSlab;
  if (showSlab) { $("#modelWarn").className = `modelWarn ${slab.cls}`; $("#modelWarn").textContent = slab.text; }
  $("#mv").style.display = keys.length ? "" : "none";
  if (!keys.length) { $("#modelBar").innerHTML = ""; return; }
  const newest = keys[keys.length - 1];
  if (state.wantModel && models[state.wantModel]) { state.model = state.wantModel; state.wantModel = null; }
  else if (!state.model || !models[state.model] || state._userPicked !== true) state.model = newest;
  $("#modelBar").innerHTML = keys.map((k) => `<button data-k="${k}" class="${k === state.model ? "on" : ""}">${shapeName(job, models[k].label)}</button>`).join("");
  $$("#modelBar button").forEach((b) => b.addEventListener("click", () => { state.model = b.dataset.k; state._userPicked = true; renderModels(job); }));
  const src = fileUrl(job, models[state.model].file);
  const mv = $("#mv");
  if (mv.getAttribute("src") !== src) mv.setAttribute("src", src);
  if (state.autoTab && state._seenModels !== keys.length) {
    state._seenModels = keys.length;
    if (keys.includes("print") && job.status === "done") setTab("model");
  }
}

function renderShots(job) {
  const shots = job.shots || [];
  $("#shotCount").textContent = shots.length ? `(${shots.length})` : "";
  const el = $("#shots");
  if (el.dataset.n === String(shots.length) && el.dataset.id === job.id) return;
  el.dataset.n = shots.length;
  el.dataset.id = job.id;
  el.innerHTML = shots.length ? shots.slice().reverse().map((s) => `
    <div class="shot" data-src="${fileUrl(job, s.file)}" data-cap="${escapeHtml(s.label)}">
      <img src="${fileUrl(job, s.file)}" alt="" loading="lazy"><span>${escapeHtml(s.label)}</span></div>`).join("")
    : `<div class="muted">Progress shots appear here while the job runs.</div>`;
  $$(".shot", el).forEach((s) => s.addEventListener("click", () => {
    const lb = $("#lightbox");
    $("img", lb).src = s.dataset.src;
    $(".lbCap", lb).textContent = s.dataset.cap;
    lb.hidden = false;
  }));
}

function renderResult(job) {
  const box = $("#result");
  const sm = job.summary;
  box.hidden = !(job.status === "done" && job.project);
  if (box.hidden) return;
  $("#dlBtn").href = fileUrl(job, "project.3mf");
  const stats = [];
  if (sm && sm.sliced) {
    stats.push([`${sm.print_hours} h`, "Print time (A1 mini)"]);
    stats.push([sm.colour_changes, "Colour changes"]);
    stats.push([`${Math.round(sm.filament_g)} g`, `Filament · ${Math.round(sm.model_g)} g in the model`]);
  } else {
    stats.push(["—", "Slice check did not run"]);
  }
  if (sm && sm.size_mm) stats.push([`${sm.size_mm.map((x) => Math.round(x)).join(" × ")}`, "Size in mm"]);
  $("#stats").innerHTML = stats.map(([b, s]) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`).join("");
  const pal = (sm && sm.palette) || [];
  $("#palette").innerHTML = pal.map((hex, i) => `
    <div class="sw"><i style="background:${hex}"></i><div>Filament ${i + 1}<br><b>${hex}</b>${sm.per_filament_g ? ` · ${Math.round(sm.per_filament_g[i] || 0)} g` : ""}</div></div>`).join("");
  const w = sm && sm.warning;
  $("#warn").hidden = !w;
  $("#warn").textContent = w ? `Bambu Studio says: ${w}` + (/floating|support/i.test(w) ? " Turn on supports (tree supports suit figures) before printing." : "") : "";
}

// ---------------------------------------------------------------- actions
async function post(url, method = "POST") {
  const r = await fetch(url, { method });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function initActions() {
  $$("#tabs button").forEach((b) => b.addEventListener("click", () => { state.autoTab = false; setTab(b.dataset.tab); }));
  $("#lightbox").addEventListener("click", () => ($("#lightbox").hidden = true));
  $("#cancelBtn").addEventListener("click", async () => {
    if (!confirm("Cancel this job?")) return;
    try { await post(`/api/jobs/${state.sel}/cancel`); toast("Cancelling…"); } catch (e) { toast(e.message); }
  });
  $("#removeBtn").addEventListener("click", async () => {
    if (!confirm("Remove this job and its files?")) return;
    try { await post(`/api/jobs/${state.sel}`, "DELETE"); delete state.jobs[state.sel]; state.sel = null; render(); } catch (e) { toast(e.message); }
  });
  const gateAction = (sel, path, msg) => $(sel).addEventListener("click", async () => {
    ["#gateGo", "#gateRetry", "#gateStop"].forEach((s) => ($(s).disabled = true));
    try { await post(`/api/jobs/${state.sel}/${path}`); toast(msg); state.autoTab = true; state._userPicked = false; }
    catch (e) { toast(e.message); ["#gateGo", "#gateRetry", "#gateStop"].forEach((s) => ($(s).disabled = false)); }
  });
  gateAction("#gateGo", "continue", "Continuing…");
  gateAction("#gateRetry", "retry", "Trying again with a new seed…");
  gateAction("#gateStop", "cancel", "Stopped.");
  $("#bambuBtn").addEventListener("click", async () => {
    try { await post(`/api/jobs/${state.sel}/open-bambu`); toast("Opening Bambu Studio…"); } catch (e) { toast(e.message); }
  });
  $("#stopAll").addEventListener("click", async () => {
    const live = Object.values(state.jobs).filter((j) => ACTIVE.has(j.status)).length;
    const what = live ? `This cancels ${live} job${live > 1 ? "s" : ""}, stops the engine and frees the graphics memory.`
                      : "Nothing is running. This frees the graphics memory the engine is holding.";
    if (!confirm(`Stop everything?

${what}`)) return;
    const btn = $("#stopAll");
    btn.disabled = true; btn.classList.add("busy"); $("span", btn).textContent = "Stopping…";
    try {
      const r = await post("/api/stop-all");
      const gb = (m) => (m / 1024).toFixed(1);
      const parts = [r.stopped.length ? `Stopped ${r.stopped.length} job${r.stopped.length > 1 ? "s" : ""}` : "Nothing was running"];
      if (r.gpu_before != null && r.gpu_after != null) parts.push(`GPU memory ${gb(r.gpu_before)} → ${gb(r.gpu_after)} GB`);
      if (r.engine_restarted) parts.push("engine restarting (about 20 s)");
      const busy = (r.others || []).filter((o) => !o.freed);
      if (busy.length) parts.push("your other ComfyUI is busy, so it was left alone");
      toast(parts.join(" · "));
      pollStatus();
    } catch (e) { toast(e.message); }
    finally { btn.disabled = false; btn.classList.remove("busy"); $("span", btn).textContent = "Stop everything"; }
  });
  $("#folderBtn").addEventListener("click", async () => {
    try { await post(`/api/jobs/${state.sel}/open-folder`); } catch (e) { toast(e.message); }
  });
}

// ---------------------------------------------------------------- live updates
function setEngine(e) {
  const pill = $("#enginePill");
  pill.className = "pill " + (e.state === "ready" ? "ok" : e.state === "error" ? "err" : "busy");
  $("span", pill).textContent = e.state === "ready" ? "Engine ready" : e.state === "error" ? "Engine error" : "Engine starting";
  pill.title = e.detail || "";
}

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "job") {
      state.jobs[msg.job.id] = msg.job;
      if (!state.sel) state.sel = msg.job.id;
      if (msg.job.id === state.sel) render(); else renderList();
    } else if (msg.type === "engine") {
      setEngine(msg.engine);
    } else if (msg.type === "removed") {
      delete state.jobs[msg.id];
      if (state.sel === msg.id) state.sel = null;
      render();
    }
  };
  es.onerror = () => { setEngine({ state: "starting", detail: "Reconnecting to the studio" }); };
}

async function pollStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    setEngine(s.engine);
    if (s.gpu) $("#gpuPill span").textContent = `GPU ${s.gpu.util}% · ${(s.gpu.mem_used / 1024).toFixed(1)}/${(s.gpu.mem_total / 1024).toFixed(0)} GB`;
  } catch { /* studio restarting */ }
}

async function init() {
  initForm();
  initActions();
  const jobs = await (await fetch("/api/jobs")).json();
  jobs.forEach((j) => (state.jobs[j.id] = j));
  const running = jobs.find((j) => ACTIVE.has(j.status));
  state.sel = running ? running.id : null;
  // Deep links: ?job=<id>&tab=model|shots|live&model=coarse|detail|painted|print
  const q = new URLSearchParams(location.search);
  if (q.get("job") && state.jobs[q.get("job")]) {
    select(q.get("job"));
    if (q.get("model")) { state.wantModel = q.get("model"); state._userPicked = true; }
    if (q.get("tab")) { state.autoTab = false; setTab(q.get("tab")); }
    if (q.get("still")) { $("#mv").removeAttribute("auto-rotate"); $("#mv").cameraOrbit = `${q.get("still")}deg 80deg auto`; }
  }
  render();
  connect();
  pollStatus();
  setInterval(pollStatus, 4000);
  setInterval(() => { const j = state.jobs[state.sel]; if (j && ACTIVE.has(j.status)) { renderStages(j); render(); } }, 1000);
}
init();
