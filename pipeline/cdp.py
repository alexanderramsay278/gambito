"""Tiny Chrome DevTools Protocol driver for headless Edge: navigate, evaluate JS, wait, click, screenshot,
and collect JS errors/console output."""
import base64, json, os, shutil, subprocess, time, urllib.request
import websocket

from paths import BROWSER as EDGE, DATA
PROFILE = os.path.join(DATA, "browser_profile")


class Browser:
    def __init__(self, port=9333, w=1366, h=900, fresh=True, mobile=False):
        if fresh and os.path.exists(PROFILE):
            shutil.rmtree(PROFILE, ignore_errors=True)
        self.p = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={port}", "--disable-gpu", "--no-first-run",
                                   "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required", f"--window-size={w},{h}",
                                   f"--user-data-dir={PROFILE}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tabs = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                if any(t["type"] == "page" for t in tabs):
                    break
            except Exception:
                pass
            time.sleep(0.2)
        page = next(t for t in tabs if t["type"] == "page")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=180, suppress_origin=True)
        self.n = 0
        self.events = []
        self.cmd("Page.enable")
        self.cmd("Runtime.enable")
        if mobile:
            self.cmd("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=2, mobile=True)

    def cmd(self, method, **params):
        self.n += 1
        my = self.n
        self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my:
                return msg.get("result", msg)
            self.events.append(msg)

    def errors(self):
        out = []
        for e in self.events:
            m = e.get("method")
            if m == "Runtime.exceptionThrown":
                d = e["params"]["exceptionDetails"]
                out.append("EXC " + (d.get("exception", {}).get("description") or d.get("text", ""))[:400])
            elif m == "Runtime.consoleAPICalled" and e["params"]["type"] in ("error", "warning"):
                out.append("CONSOLE " + " ".join(str(a.get("value", a.get("description", ""))) for a in e["params"]["args"])[:400])
        return out

    def eval(self, expr):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            return {"__error__": r["exceptionDetails"].get("text"), "detail": str(r["exceptionDetails"].get("exception", {}).get("description", ""))[:300]}
        return r.get("result", {}).get("value")

    def goto(self, url, settle=1.0):
        self.cmd("Page.navigate", url=url)
        time.sleep(settle)

    def wait(self, expr, timeout=120, every=0.5):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = self.eval(expr)
            if v and not (isinstance(v, dict) and "__error__" in v):
                return v
            time.sleep(every)
        return None

    def click(self, selector):
        return self.eval(f"(()=>{{const e=document.querySelector({json.dumps(selector)}); if(!e) return 'missing'; e.click(); return 'ok';}})()")

    def shot(self, path):
        data = self.cmd("Page.captureScreenshot", format="png")["data"]
        open(path, "wb").write(base64.b64decode(data))
        return path

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.p.terminate()
        try:
            self.p.wait(5)
        except Exception:
            self.p.kill()
