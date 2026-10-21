"""Run Gambito's built-in self-test (index.html?selftest=1) in headless Edge and print the result and any
JS errors. It checks every band's data, plays two auto lessons per colour and two engine games, and tests
the streak logic.

Usage:  py -B site_selftest.py [file|http|both]     (default both)
  file : opened straight from disk, the way the launcher opens it
  http : served by a throwaway local web server, the way a host would serve it
Exit code 0 only if every run says SELFTEST PASS with no JS errors.
"""
import os, pathlib, socket, subprocess, sys, time
from cdp import Browser

HERE = os.path.dirname(os.path.abspath(__file__))
from paths import SITE_DIR
SITE = SITE_DIR


def run(url, port):
    b = Browser(port=port)
    try:
        b.goto(url)
        title = b.wait("document.title.startsWith('SELFTEST') && document.title", timeout=900) or "TIMEOUT"
        text = b.eval("(document.getElementById('selftest') || {}).textContent || document.body.innerText.slice(0, 400)")
        return title, text, b.errors()
    finally:
        b.close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    runs = []
    if mode in ("file", "both"):
        t0 = time.time()
        runs.append(("file", run(pathlib.Path(SITE, "index.html").as_uri() + "?selftest=1", 9333), time.time() - t0))
    if mode in ("http", "both"):
        port = free_port()
        srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=SITE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)
            t0 = time.time()
            runs.append(("http", run(f"http://127.0.0.1:{port}/?selftest=1", 9334), time.time() - t0))
        finally:
            srv.terminate()
    good = True
    for name, (title, text, errs), secs in runs:
        print(f"===== {name}: {title}  ({secs:.0f}s)")
        print(text)
        print("JS errors:", errs if errs else "none")
        good = good and title.startswith("SELFTEST PASS") and not errs
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
