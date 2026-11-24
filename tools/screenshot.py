"""Full-size screenshot of a page with headless Chrome over the DevTools protocol.

python tools/screenshot.py <url> <out.png> [width] [height] [wait_seconds]
(Chrome's --screenshot flag never fires on pages with a live event stream, like the studio.)
"""
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time

import aiohttp

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
url, out = sys.argv[1], sys.argv[2]
W = int(sys.argv[3]) if len(sys.argv) > 3 else 1600
H = int(sys.argv[4]) if len(sys.argv) > 4 else 1000
WAIT = float(sys.argv[5]) if len(sys.argv) > 5 else 8


async def main():
    profile = tempfile.mkdtemp(prefix="shot_")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--user-data-dir={profile}", "--remote-debugging-port=9333",
                             f"--window-size={W},{H}", "--hide-scrollbars", "--use-angle=swiftshader",
                             "--enable-unsafe-swiftshader", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with aiohttp.ClientSession() as s:
            for _ in range(50):
                try:
                    async with s.get("http://127.0.0.1:9333/json") as r:
                        targets = await r.json()
                    page = next(t for t in targets if t["type"] == "page")
                    break
                except Exception:
                    await asyncio.sleep(0.3)
            async with s.ws_connect(page["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                n = 0

                async def call(method, **params):
                    nonlocal n
                    n += 1
                    await ws.send_str(json.dumps({"id": n, "method": method, "params": params}))
                    while True:
                        msg = json.loads((await ws.receive()).data)
                        if msg.get("id") == n:
                            return msg.get("result", {})

                await call("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
                await call("Page.navigate", url=url)
                await asyncio.sleep(WAIT)
                shot = await call("Page.captureScreenshot", format="png")
                open(out, "wb").write(base64.b64decode(shot["data"]))
                print("wrote", out)
    finally:
        proc.terminate()


asyncio.run(main())
