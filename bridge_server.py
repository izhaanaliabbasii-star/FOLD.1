"""
Fold AI <-> Jarvis Bridge
=========================
A tiny local helper that gives Fold AI (which runs in your browser, sandboxed,
with no access to your computer) a safe way to ask YOUR OWN PC to:
  - open an app
  - open a website in your default browser
  - take a screenshot, so Fold AI can describe what's on your screen

Why this exists
----------------
Websites can never be given real OS-level power (open apps, watch your
screen) -- browsers block that on purpose, for everyone's safety. Jarvis
already HAS that power because it's a real desktop app. This script is the
small, deliberately narrow bridge between the two: it runs locally, does
only these 3 things, and only ever listens on 127.0.0.1 (your own machine --
never reachable from the internet or from anyone else's computer).

Setup
-----
    pip install mss psutil pyautogui
    python bridge_server.py

`pyautogui` is optional but recommended — without it, open_app only works
for apps in the built-in alias list (chrome, spotify, notepad, etc). With
it, Fold AI can open genuinely ANY installed app by typing its name into
your Start Menu (Windows) or Spotlight (macOS) search, the same way you'd
do it yourself.

It will print a TOKEN the first time you run it (and remember it after
that, in a ".bridge_token" file next to this script). Paste that token into
Fold AI -> sidebar -> "Jarvis Bridge" -> Bridge token -> Save & connect.

Keep the terminal window open while you want to use screen-scan / open-app /
open-website from Fold AI. Close it, and those features simply go offline --
your Fold AI chat itself keeps working normally either way.

Security notes
---------------
- Binds to 127.0.0.1 only -- not visible to your network or the internet.
- Every request must include the exact token printed below, in the
  X-Bridge-Token header. Without it, every request is rejected.
- If you want to be extra careful, open the CORS line below (search for
  "Access-Control-Allow-Origin") and replace the "*" with your actual
  deployed Fold AI URL, e.g. "https://fold-ai.vercel.app", so only your own
  site's tab can talk to this bridge, not just any open tab.
"""

import base64
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

try:
    import mss
    import mss.tools
    _MSS_OK = True
except ImportError:
    _MSS_OK = False

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False

try:
    import pyautogui
    pyautogui.PAUSE = 0.1
    _PYAUTOGUI_OK = True
except Exception:
    _PYAUTOGUI_OK = False

PORT = 8765
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, ".bridge_token")

# A larger alias list, taken from Jarvis's actions/open_app.py, PLUS a fuzzy
# match and a real "type it into the Start Menu / Spotlight and press Enter"
# fallback below — that fallback is what actually makes "any app" work,
# since it doesn't need to know about the app ahead of time, same as a
# person pressing the Windows key and typing.
APP_ALIASES = {
    "whatsapp":           {"Windows": "WhatsApp",               "Darwin": "WhatsApp",             "Linux": "whatsapp"},
    "chrome":             {"Windows": "chrome",                 "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                 "Darwin": "Google Chrome",        "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                "Darwin": "Firefox",              "Linux": "firefox"},
    "spotify":            {"Windows": "Spotify",                "Darwin": "Spotify",              "Linux": "spotify"},
    "vscode":             {"Windows": "code",                   "Darwin": "Visual Studio Code",   "Linux": "code"},
    "visual studio code": {"Windows": "code",                   "Darwin": "Visual Studio Code",   "Linux": "code"},
    "discord":            {"Windows": "Discord",                "Darwin": "Discord",              "Linux": "discord"},
    "telegram":           {"Windows": "Telegram",               "Darwin": "Telegram",             "Linux": "telegram"},
    "notepad":            {"Windows": "notepad.exe",            "Darwin": "TextEdit",             "Linux": "gedit"},
    "calculator":         {"Windows": "calc.exe",               "Darwin": "Calculator",           "Linux": "gnome-calculator"},
    "terminal":           {"Windows": "cmd.exe",                "Darwin": "Terminal",             "Linux": "gnome-terminal"},
    "cmd":                {"Windows": "cmd.exe",                "Darwin": "Terminal",             "Linux": "bash"},
    "explorer":           {"Windows": "explorer.exe",           "Darwin": "Finder",               "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",           "Darwin": "Finder",               "Linux": "nautilus"},
    "paint":              {"Windows": "mspaint.exe",            "Darwin": "Preview",              "Linux": "gimp"},
    "word":               {"Windows": "winword",                "Darwin": "Microsoft Word",       "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                  "Darwin": "Microsoft Excel",      "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",               "Darwin": "Microsoft PowerPoint", "Linux": "libreoffice --impress"},
    "vlc":                {"Windows": "vlc",                    "Darwin": "VLC",                  "Linux": "vlc"},
    "zoom":               {"Windows": "Zoom",                   "Darwin": "zoom.us",              "Linux": "zoom"},
    "slack":              {"Windows": "Slack",                  "Darwin": "Slack",                "Linux": "slack"},
    "steam":              {"Windows": "steam",                  "Darwin": "Steam",                "Linux": "steam"},
    "task manager":       {"Windows": "taskmgr.exe",            "Darwin": "Activity Monitor",     "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",           "Darwin": "System Preferences",   "Linux": "gnome-control-center"},
    "powershell":         {"Windows": "powershell.exe",         "Darwin": "Terminal",             "Linux": "bash"},
    "edge":               {"Windows": "msedge",                 "Darwin": "Microsoft Edge",       "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                  "Darwin": "Brave Browser",        "Linux": "brave-browser"},
    "obsidian":           {"Windows": "Obsidian",               "Darwin": "Obsidian",             "Linux": "obsidian"},
    "notion":             {"Windows": "Notion",                 "Darwin": "Notion",               "Linux": "notion"},
    "blender":            {"Windows": "blender",                "Darwin": "Blender",              "Linux": "blender"},
    "figma":              {"Windows": "Figma",                  "Darwin": "Figma",                "Linux": "figma"},
}


def load_or_create_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    token = secrets.token_hex(16)
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    return token


TOKEN = load_or_create_token()


def _normalize_app_name(raw):
    system = platform.system()
    key = raw.lower().strip()
    if key in APP_ALIASES:
        return APP_ALIASES[key].get(system, raw)
    for alias_key, os_map in APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(system, raw)
    return raw


def _search_and_launch(app_name):
    """The real 'any app' fallback: type the name into the Start Menu
    (Windows) or Spotlight (macOS) and press Enter, exactly like a person
    would. Needs `pip install pyautogui`."""
    if not _PYAUTOGUI_OK:
        return False
    system = platform.system()
    try:
        if system == "Windows":
            pyautogui.press("win")
            time.sleep(0.6)
        elif system == "Darwin":
            pyautogui.hotkey("command", "space")
            time.sleep(0.6)
        else:
            return False  # Linux desktop search shortcuts vary too much to guess
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception:
        return False


def open_app(name):
    name = (name or "").strip()
    if not name:
        return False, "No app name given"

    system = platform.system()
    target = _normalize_app_name(name)

    # 1) Try it as a direct launch (registered app name / .app bundle)
    try:
        if system == "Windows":
            os.startfile(target)  # noqa
        elif system == "Darwin":
            result = subprocess.run(["open", "-a", target], capture_output=True, timeout=8)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode(errors="ignore") or "open -a failed")
        else:
            binary = shutil.which(target) or shutil.which(target.lower())
            if binary:
                subprocess.Popen([binary])
            else:
                subprocess.run(["xdg-open", target], capture_output=True, timeout=5)
        return True, f"Opened {name}"
    except Exception:
        pass

    # 2) Try it as a binary directly on PATH (covers a huge range of apps
    #    that aren't in APP_ALIASES at all, e.g. anything installed via a
    #    package manager)
    binary = shutil.which(name) or shutil.which(name.lower()) or shutil.which(name.lower().replace(" ", "-"))
    if binary:
        try:
            subprocess.Popen([binary])
            return True, f"Opened {name}"
        except Exception:
            pass

    # 3) True "any app" fallback: type it into the OS's own search
    if _search_and_launch(name):
        return True, f"Opened {name} via search"

    hint = "" if _PYAUTOGUI_OK else " (run 'pip install pyautogui' to enable searching for apps not in the known list)"
    return False, f"Couldn't find or launch '{name}'.{hint}"


def open_url(url):
    url = (url or "").strip()
    if not url:
        return False, "No URL given"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return True, f"Opened {url}"


def take_screenshot_b64():
    if not _MSS_OK:
        return None, "The 'mss' package isn't installed. Run: pip install mss"
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(monitor)
            png_bytes = mss.tools.to_png(shot.rgb, shot.size)
        return base64.b64encode(png_bytes).decode("utf-8"), None
    except Exception as e:
        return None, str(e)


def get_system_stats():
    if not _PSUTIL_OK:
        return None, "The 'psutil' package isn't installed. Run: pip install psutil"
    try:
        battery = psutil.sensors_battery()
        disk = psutil.disk_usage(os.path.abspath(os.sep))
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.3),
            "ram_percent": psutil.virtual_memory().percent,
            "battery_percent": (battery.percent if battery else None),
            "battery_plugged": (battery.power_plugged if battery else None),
            "disk_free_gb": round(disk.free / (1024 ** 3), 1),
            "disk_total_gb": round(disk.total / (1024 ** 3), 1),
        }, None
    except Exception as e:
        return None, str(e)


def open_path(path):
    path = (path or "").strip()
    if not path:
        return False, "No path given"
    if not os.path.exists(path):
        return False, f"That path doesn't exist on this computer: {path}"
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(path)  # noqa
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, f"Opened {path}"
    except Exception as e:
        return False, str(e)


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        # Tighten this to your real Fold AI URL when you're ready, e.g.
        # "https://fold-ai.vercel.app" instead of "*".
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        return self.headers.get("X-Bridge-Token") == TOKEN

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self._json(200, {"ok": True})
        if not self._authorized():
            return self._json(401, {"error": "Missing or wrong bridge token"})
        if path == "/screenshot":
            img, err = take_screenshot_b64()
            if err:
                return self._json(500, {"error": err})
            return self._json(200, {"image_base64": img})
        if path == "/system-stats":
            stats, err = get_system_stats()
            if err:
                return self._json(500, {"error": err})
            return self._json(200, stats)
        self._json(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if not self._authorized():
            return self._json(401, {"error": "Missing or wrong bridge token"})
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            data = {}
        path = urlparse(self.path).path
        if path == "/open-app":
            ok, msg = open_app(data.get("name", ""))
            return self._json(200 if ok else 500, {"ok": ok, "message": msg})
        if path == "/open-url":
            ok, msg = open_url(data.get("url", ""))
            return self._json(200 if ok else 500, {"ok": ok, "message": msg})
        if path == "/open-path":
            ok, msg = open_path(data.get("path", ""))
            return self._json(200 if ok else 500, {"ok": ok, "message": msg})
        self._json(404, {"error": "Unknown endpoint"})

    def log_message(self, format, *args):
        pass  # keep the terminal quiet


if __name__ == "__main__":
    if not _MSS_OK:
        print("NOTE: 'mss' isn't installed yet, so screen-scan won't work until you run:")
        print("      pip install mss\n")
    if not _PSUTIL_OK:
        print("NOTE: 'psutil' isn't installed yet, so system-stats won't work until you run:")
        print("      pip install psutil\n")
    if not _PYAUTOGUI_OK:
        print("NOTE: 'pyautogui' isn't installed, so open_app only works for apps in the")
        print("      built-in alias list. For genuinely ANY app, run: pip install pyautogui\n")
    print("=" * 56)
    print(" Fold AI <-> Jarvis Bridge")
    print("=" * 56)
    print(f" Listening on: http://127.0.0.1:{PORT}  (this device only)")
    print(f" Your token:   {TOKEN}")
    print(" Paste this token into Fold AI -> sidebar -> Jarvis Bridge.")
    print(" Leave this window open while using screen-scan / open-app / open-website.")
    print("=" * 56)
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nBridge stopped.")
        sys.exit(0)
