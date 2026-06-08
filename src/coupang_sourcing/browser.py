"""Headful-Chrome Akamai cookie minting via the DevTools Protocol.

The `/np/search` and `/vp/products/.../vendoritems/...` routes sit behind Akamai's JS
interstitial: curl_cffi alone (and even *headless* Chrome) gets a hard block, but a real
**headful** Chrome solves the sensor and mints a valid cookie set (`_abck`, `bm_*`,
`ak_bmsc`, `x-cp-s`). Those cookies then replay through curl_cffi for fast bulk fetches —
so the browser runs only occasionally to (re)mint, not per request.

Mechanism: Python launches/cleans up a headful Chrome; a tiny embedded Node CDP script
drives it (navigate → poll the page until the sensor solves → dump cookies). Node already
ships with most dev setups; the heavy bulk collection (`listing`, best100) stays pure
Python and needs neither Node nor a browser. Set COUPANG_CHROME / COUPANG_NODE to override
binary discovery.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time

from .config import BASE_WWW

# A search URL forces Akamai to run its sensor; once solved the full cookie set is minted.
DEFAULT_MINT_URL = f"{BASE_WWW}/np/search?q=%EC%9D%98%EC%9E%90&channel=user"

_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
]
_CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]

# Driven over CDP via Node's built-in WebSocket/fetch (no npm packages). Args: <port> <url> <ms>.
# Prints one JSON line: {"cookies":[{"name","value","domain"}, ...]}.
_NODE_MINT_JS = r"""
const PORT = +process.argv[2], URL0 = process.argv[3], MAX = +(process.argv[4] || "45000");
async function pageWs() {
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find(t => t.type === "page");
      if (page && page.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch (e) {}
    await new Promise(r => setTimeout(r, 250));
  }
  throw new Error("no page target");
}
const ws = new WebSocket(await pageWs());
let id = 0;
const pend = new Map();
const cmd = (m, p = {}) => new Promise(res => {
  const i = ++id;
  pend.set(i, res);
  ws.send(JSON.stringify({ id: i, method: m, params: p }));
});
await new Promise(r => ws.addEventListener("open", r));
ws.addEventListener("message", ev => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); }
});
await cmd("Page.enable"); await cmd("Network.enable"); await cmd("Runtime.enable");
await cmd("Page.navigate", { url: URL0 });
const deadline = Date.now() + MAX;
let cookies = [], reloaded = false;
const started = Date.now();
while (Date.now() < deadline) {
  await new Promise(r => setTimeout(r, 1500));
  await cmd("Runtime.evaluate", { expression: "document.title", returnByValue: true });
  const r = await cmd("Network.getAllCookies");
  cookies = (r.cookies || [])
    .filter(c => /coupang/.test(c.domain))
    .map(c => ({ name: c.name, value: c.value, domain: c.domain }));
  const names = new Set(cookies.map(c => c.name));
  if (names.has("x-cp-s") && names.has("_abck")) break;
  if (!reloaded && Date.now() - started > 14000) {
    reloaded = true;
    await cmd("Page.navigate", { url: URL0 });
  }
}
console.log(JSON.stringify({ cookies }));
process.exit(0);
"""


def find_chrome() -> str:
    """Locate a Chrome/Chromium binary or raise with guidance."""
    env = os.environ.get("COUPANG_CHROME")
    if env and os.path.exists(env):
        return env
    if platform.system() == "Darwin":
        for path in _CHROME_CANDIDATES:
            if os.path.exists(path):
                return path
    for name in _CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError(
        "Chrome/Chromium not found. Install Google Chrome, or set COUPANG_CHROME=/path/to/chrome."
    )


def chrome_major_version() -> int | None:
    """Best-effort major version of the installed Chrome (for UA/JA3 alignment)."""
    try:
        out = subprocess.run(
            [find_chrome(), "--version"], capture_output=True, text=True, timeout=10
        ).stdout
        m = re.search(r"(\d+)\.\d+\.\d+", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def find_node() -> str:
    """Locate a Node.js binary (used only to drive Chrome over CDP for the mint step)."""
    env = os.environ.get("COUPANG_NODE")
    if env and os.path.exists(env):
        return env
    found = shutil.which("node")
    if found:
        return found
    # nvm installs land outside the default PATH for non-interactive shells.
    nvm = os.path.expanduser("~/.nvm/versions/node")
    if os.path.isdir(nvm):
        for ver in sorted(os.listdir(nvm), reverse=True):
            cand = os.path.join(nvm, ver, "bin", "node")
            if os.path.exists(cand):
                return cand
    raise RuntimeError(
        "Node.js not found (needed only for the cookie-mint step). Install Node, or set "
        "COUPANG_NODE=/path/to/node."
    )


def _read_devtools_port(user_data_dir: str, timeout: float) -> int:
    path = os.path.join(user_data_dir, "DevToolsActivePort")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            try:
                return int(open(path).read().splitlines()[0])
            except (ValueError, IndexError):
                pass
        time.sleep(0.2)
    raise RuntimeError("Chrome did not expose a DevTools port")


def _profile_dir() -> str:
    # Persistent profile (real GPU, no automation flag) so the browser looks like an
    # established human session rather than a fresh bot: Akamai fingerprints the browser
    # (navigator.webdriver, WebGL vendor, profile age), not just the IP — a human on the
    # same IP never gets blocked.
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, "coupang-sourcing", "chrome-profile")
    os.makedirs(d, exist_ok=True)
    return d


def mint_cookies(
    url: str = DEFAULT_MINT_URL, *, timeout: float = 45.0, progress=None
) -> list[dict[str, str]]:
    """Mint Akamai cookies; on failure reset the (possibly corrupted) profile and retry once.

    An interrupted mint can leave the persistent Chrome profile in a state where the next
    launch fails ("0 cookies"), so we self-heal by wiping it and retrying.
    """
    try:
        return _mint_once(url, timeout=timeout, progress=progress)
    except RuntimeError:
        if progress:
            progress("mint 실패 — 브라우저 프로필 초기화 후 1회 재시도…")
        shutil.rmtree(_profile_dir(), ignore_errors=True)
        return _mint_once(url, timeout=timeout, progress=progress)


def _mint_once(
    url: str = DEFAULT_MINT_URL, *, timeout: float = 45.0, progress=None
) -> list[dict[str, str]]:
    """Launch a headful Chrome, solve Akamai, and return the minted coupang cookies.

    Each cookie is {"name","value","domain"}. Raises RuntimeError if Chrome/Node is missing
    or the sensor is not solved within `timeout`.
    """
    chrome = find_chrome()
    node = find_node()
    profile_dir = _profile_dir()
    # Drop any stale DevTools port file so we read the new instance's port.
    try:
        os.remove(os.path.join(profile_dir, "DevToolsActivePort"))
    except OSError:
        pass
    script_fd, script_path = tempfile.mkstemp(suffix=".mjs", prefix="coupang-mint-")
    with os.fdopen(script_fd, "w") as fh:
        fh.write(_NODE_MINT_JS)
    args = [
        chrome,
        "--remote-debugging-port=0",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        # Remove the automation fingerprint: forces navigator.webdriver=false and drops
        # the "controlled by automated software" surface Akamai keys on.
        "--disable-blink-features=AutomationControlled",
        "--window-size=1280,860",
        "--window-position=80,80",
        "about:blank",
    ]
    if progress:
        progress("launching Chrome to mint Akamai cookies…")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        port = _read_devtools_port(profile_dir, timeout=15)
        if progress:
            progress("solving Akamai sensor (this runs a brief Chrome window)…")
        result = subprocess.run(
            [node, script_path, str(port), url, str(int(timeout * 1000))],
            capture_output=True, text=True, timeout=timeout + 25,
        )
        line = (result.stdout or "").strip().splitlines()[-1] if result.stdout.strip() else ""
        cookies = json.loads(line).get("cookies", []) if line else []
        names = {c["name"] for c in cookies}
        if "x-cp-s" not in names:
            raise RuntimeError(
                f"Akamai sensor not solved within {timeout:.0f}s "
                f"(got {len(cookies)} cookies). node stderr: {(result.stderr or '')[:200]}"
            )
        if progress:
            progress(f"minted {len(cookies)} cookies")
        return cookies
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        try:
            os.remove(script_path)
        except OSError:
            pass
