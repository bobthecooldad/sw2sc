"""The vault window: a small local web app (standard library only).

`python -m sw2sc gui` serves the page on 127.0.0.1 and opens it in the browser. Only this
PC can reach it, and every request must carry a token made for this run. The Browse buttons
open Windows' own folder dialog (through PowerShell); elsewhere the folder is typed.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, folders, roles, vault, workflow

PAGE = os.path.join(os.path.dirname(__file__), "gui.html")
SETTINGS = os.path.join(os.path.expanduser("~"), ".sw2sc-gui.json")
MAX_BODY = 1 << 16


def pick_folder(title: str, start: str = "") -> str | None:
    """Windows folder dialog, in front of other windows. None when cancelled or unavailable."""
    if os.name != "nt":
        return None
    start = start if start and os.path.isdir(start) else ""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$o = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false};"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = $env:SW2SC_TITLE; $d.ShowNewFolderButton = $true;"
        "if ($env:SW2SC_START) { $d.SelectedPath = $env:SW2SC_START };"
        "if ($d.ShowDialog($o) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.SelectedPath }"
    )
    env = dict(os.environ, SW2SC_TITLE=title, SW2SC_START=start)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                           capture_output=True, env=env, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.decode("utf-8", "replace").strip()
    return out or None


_VERSIONS: dict[str, tuple] = {}


def app_version(exe: str) -> tuple:
    """The app's file version, as numbers ((0,) when unknown). Read once per file and date."""
    key = f"{exe}|{os.path.getmtime(exe) if os.path.exists(exe) else 0}"
    if key not in _VERSIONS:
        v = ""
        if os.name == "nt":
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                    "(Get-Item -LiteralPath $env:SW2SC_EXE).VersionInfo.ProductVersion"],
                                   capture_output=True, timeout=30, env=dict(os.environ, SW2SC_EXE=exe))
                v = r.stdout.decode("utf-8", "replace").strip()
            except (OSError, subprocess.TimeoutExpired):
                v = ""
        nums = tuple(int(x) for x in v.split("+")[0].split("-")[0].split(".") if x.isdigit())
        _VERSIONS[key] = nums or (0,)
    return _VERSIONS[key]


def find_solidcraft() -> str | None:
    """The SolidCraft desktop app. The setting `solidcraft` in the settings file wins;
    otherwise the newest of the copies found on the PATH and in the usual places (an install,
    or a build in C:\\dev\\solidcraft)."""
    configured = load_settings().get("solidcraft")
    if isinstance(configured, str) and os.path.isfile(configured):
        return configured
    local = os.environ.get("LOCALAPPDATA", "")
    found = []
    for c in (shutil.which("solidcraft"),
              os.path.join(local, "Programs", "SolidCraft", "solidcraft.exe"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "SolidCraft", "solidcraft.exe"),
              r"C:\dev\solidcraft\target\release\solidcraft.exe"):
        if c and os.path.isfile(c) and os.path.normcase(os.path.abspath(c)) not in {os.path.normcase(os.path.abspath(f)) for f in found}:
            found.append(c)
    if not found:
        return None
    return max(found, key=app_version)


def control_dir() -> str | None:
    """Where a running SolidCraft app writes its control port and token (docs/control-protocol.md
    in SolidCraft): %LOCALAPPDATA%\SolidCraft\control, or SOLIDCRAFT_CONTROL_DIR."""
    custom = os.environ.get("SOLIDCRAFT_CONTROL_DIR")
    if custom:
        return custom
    local = os.environ.get("LOCALAPPDATA")
    return os.path.join(local, "SolidCraft", "control") if local else None


def open_in_running_solidcraft(path: str, timeout: float = 60.0) -> bool:
    """Ask a SolidCraft window that is already open to open `path` (F-029), through its
    localhost control channel. SolidCraft puts it in a tab of its own unless the window shows
    a blank design, and a design already open comes forward in its tab, so nothing unsaved is
    replaced. False when no window answers (none running, an older app, the channel off)."""
    import socket
    folder = control_dir()
    if not folder:
        return False
    try:
        with open(os.path.join(folder, "current.port"), encoding="utf-8") as fh:
            port = int(fh.read(64).strip())
        with open(os.path.join(folder, f"{port}.token"), encoding="utf-8") as fh:
            token = fh.read(256).strip()
    except (OSError, ValueError):
        return False
    if not token or not 0 < port < 65536:
        return False
    request = {"id": 1, "method": "engine.execute", "token": token,
               "params": {"command": "doc.open", "params": {"path": os.path.abspath(path)}}}
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
            conn.settimeout(timeout)  # answered once the file has loaded
            conn.sendall((json.dumps(request) + "\n").encode("utf-8"))
            reply = b""
            while not reply.endswith(b"\n") and len(reply) < (1 << 20):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                reply += chunk
    except OSError:
        return False
    try:
        answer = json.loads(reply.decode("utf-8", "replace").strip().splitlines()[0])
    except (ValueError, IndexError):
        return False
    if answer.get("ok"):
        return True
    error = str(answer.get("error", ""))
    if error.startswith("unauthorized") or "unknown method" in error:
        return False  # a stale token file or an app that can't do this: start a window instead
    raise RuntimeError("SolidCraft couldn't open it: " + error)


def open_in_solidcraft(path: str) -> None:
    if load_settings().get("reuse_window", True) and open_in_running_solidcraft(path):
        return
    exe = find_solidcraft()
    if not exe:
        raise FileNotFoundError("SolidCraft isn't installed or wasn't found. Set \"solidcraft\" to its path in "
                                + SETTINGS)
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    # its own process: closing the vault window leaves SolidCraft open
    subprocess.Popen([exe, os.path.normpath(path)], cwd=os.path.dirname(path) or None, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


class Job:
    """One import running in the background, with its log."""

    def __init__(self):
        self.lines: list[str] = []
        self.running = False
        self.result: dict | None = None
        self.lock = threading.Lock()

    def log(self, msg: str) -> None:
        with self.lock:
            self.lines.append(str(msg))

    def start(self, source: str, target: str, originals: bool, git: bool, subassemblies: bool,
              other: bool = True) -> None:
        with self.lock:
            if self.running:
                raise ValueError("an import is already running")
            self.lines, self.result, self.running = [], None, True

        def work():
            try:
                self.log(f"Importing {source}")
                self.log(f"into {target}")
                r = vault.import_tree(source, target, originals, git, self.log, subassemblies, other)
                res = {"ok": True, "converted": r.converted, "unchanged": r.unchanged, "copied": r.copied,
                       "removed": r.removed, "failed": [list(x) for x in r.failed], "warnings": r.warnings,
                       "commit": r.commit}
                self.log(f"Done: {r.converted} converted, {r.unchanged} unchanged, {r.copied} other files copied, "
                         f"{r.removed} removed, {len(r.failed)} failed.")
            except Exception as e:  # shown in the window, never a crash
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                self.log(f"Stopped: {res['error']}")
            with self.lock:
                self.result, self.running = res, False
        threading.Thread(target=work, daemon=True).start()

    def state(self, since: int) -> dict:
        with self.lock:
            return {"running": self.running, "lines": self.lines[since:], "next": len(self.lines), "result": self.result}


def load_settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(d: dict) -> None:
    keep = load_settings()
    keep.update({k: d[k] for k in ("source", "vault") if isinstance(d.get(k), str)})
    try:
        with open(SETTINGS, "w", encoding="utf-8") as fh:
            json.dump({k: v for k, v in keep.items()
                       if (k in ("source", "vault", "solidcraft") and isinstance(v, str))
                       or (k == "reuse_window" and isinstance(v, bool))}, fh)
    except OSError:
        pass


def make_handler(token: str, job: Job):
    class Handler(BaseHTTPRequestHandler):
        server_version = "sw2sc"

        def log_message(self, *_):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

        def _allowed(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False
            return secrets.compare_digest(self.headers.get("X-Token", ""), token)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                q = parse_qs(u.query)
                if q.get("t", [""])[0] != token:
                    return self._send(403, b"Open the link sw2sc printed.", "text/plain")
                with open(PAGE, "rb") as fh:
                    page = fh.read().replace(b"__TOKEN__", token.encode()).replace(b"__VERSION__", __version__.encode())
                return self._send(200, page, "text/html; charset=utf-8")
            if not self._allowed():
                return self._json({"error": "not allowed"}, 403)
            q = parse_qs(u.query)
            if u.path == "/api/settings":
                return self._json(load_settings())
            if u.path == "/api/job":
                return self._json(job.state(int(q.get("since", ["0"])[0] or 0)))
            if u.path == "/api/vault":
                path = q.get("path", [""])[0]
                index = os.path.join(path, vault.INDEX)
                if not path or not os.path.isfile(index):
                    return self._json({"error": "no vault here yet"}, 404)
                with open(index, encoding="utf-8") as fh:
                    data = json.load(fh)
                data["history"] = _history(path)
                exe = find_solidcraft()
                data["solidcraft"] = ".".join(map(str, app_version(exe))) if exe else ""
                data["workflow"] = workflow.status(path)
                try:
                    data["folders"] = folders.view(path)
                except folders.FolderError as e:
                    data["folders"] = {"folders": [], "items": {}, "error": str(e)}
                try:
                    data["access"] = roles.describe(path, roles.identity())
                except roles.RolesError as e:
                    data["access"] = {"user": roles.identity(), "open": False, "admin": False, "approver": False,
                                      "roles": None, "error": str(e)}
                return self._json(data)
            return self._json({"error": "unknown"}, 404)

        def do_POST(self):
            if not self._allowed():
                return self._json({"error": "not allowed"}, 403)
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._json({"error": "too large"}, 413)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json({"error": "bad request"}, 400)
            path = urlparse(self.path).path
            if path == "/api/pick":
                title = "Choose the folder to import" if body.get("what") == "source" else "Choose the vault folder"
                return self._json({"path": pick_folder(title, body.get("start", ""))})
            if path == "/api/import":
                src, dst = str(body.get("source", "")).strip(), str(body.get("vault", "")).strip()
                if not os.path.isdir(src):
                    return self._json({"error": "The folder to import doesn't exist."}, 400)
                if not dst:
                    return self._json({"error": "Choose a vault folder."}, 400)
                a, b = os.path.abspath(src), os.path.abspath(dst)
                if a == b or os.path.commonpath([a, b]) == a:
                    return self._json({"error": "The vault must be outside the folder being imported."}, 400)
                if not body.get("confirm"):
                    why = vault.check_source(src, dst)
                    if why:
                        return self._json({"error": "Check the folder first.", "confirm": why}, 409)
                save_settings({"source": src, "vault": dst})
                try:
                    job.start(src, dst, bool(body.get("originals", True)), bool(body.get("git", True)),
                              bool(body.get("subassemblies", True)), bool(body.get("other", True)))
                except ValueError as e:
                    return self._json({"error": str(e)}, 409)
                return self._json({"started": True})
            if path == "/api/open":
                target = str(body.get("vault", ""))
                item = str(body.get("item", ""))
                index = os.path.join(target, vault.INDEX)
                if not os.path.isfile(index):
                    return self._json({"error": "No vault there."}, 404)
                with open(index, encoding="utf-8") as fh:
                    known = json.load(fh).get("items", {})
                if item not in known:  # only designs the vault lists: never an arbitrary path
                    return self._json({"error": "Not in this vault."}, 404)
                rev = str(body.get("revision", ""))
                try:
                    if rev:
                        folder = os.path.join(tempfile.gettempdir(), "sw2sc-releases",
                                              "".join(c if c.isalnum() or c in "-_." else "_" for c in f"{item}-{rev}"))
                        shutil.rmtree(folder, ignore_errors=True)
                        workflow.get_release(target, item, rev, folder)
                        design = os.path.join(folder, *item.split("/"))
                    else:
                        design = os.path.join(target, *item.split("/"))
                    if not os.path.isfile(design):
                        return self._json({"error": "The design file is missing."}, 404)
                    open_in_solidcraft(design)
                except (workflow.WorkflowError, OSError) as e:
                    return self._json({"error": str(e)}, 409)
                return self._json({"ok": True})
            if path in ("/api/workflow", "/api/get-release", "/api/plan", "/api/workflow-tree", "/api/roles"):
                if job.state(0)["running"]:
                    return self._json({"error": "Wait for the import to finish."}, 409)
                target = str(body.get("vault", ""))
                if not os.path.isfile(os.path.join(target, vault.INDEX)):
                    return self._json({"error": "No vault there."}, 404)
                try:
                    me = roles.identity()  # who is acting comes from the login, never from the page
                    if path == "/api/roles":
                        try:
                            on = bool(body.get("value"))
                            roles.edit(target, me, str(body.get("op", "")), str(body.get("who", "")), on)
                        except roles.RolesError as e:
                            return self._json({"error": str(e)}, 409)
                        return self._json({"ok": True})
                    if path == "/api/plan":
                        return self._json(workflow.plan_tree(target, str(body.get("item", "")), str(body.get("action", "")), me))
                    if path == "/api/workflow-tree":
                        plan = workflow.change_tree(target, str(body.get("item", "")), str(body.get("action", "")),
                                                    me, str(body.get("comment", "")))
                        return self._json({"ok": True, "changed": len(plan["steps"])})
                    if path == "/api/workflow":
                        w = workflow.change(target, str(body.get("item", "")), str(body.get("action", "")),
                                            me, str(body.get("comment", "")))
                        return self._json({"ok": True, "state": w["state"], "revision": w["revision"]})
                    dest = pick_folder("Choose where to put this release")
                    if not dest:
                        return self._json({"cancelled": True})
                    files = workflow.get_release(target, str(body.get("item", "")), str(body.get("revision", "")), dest)
                    return self._json({"ok": True, "files": len(files), "to": dest})
                except workflow.WorkflowError as e:
                    return self._json({"error": str(e)}, 409)
            if path == "/api/folders":
                if job.state(0)["running"]:
                    return self._json({"error": "Wait for the import to finish."}, 409)
                target = str(body.get("vault", ""))
                if not os.path.isfile(os.path.join(target, vault.INDEX)):
                    return self._json({"error": "No vault there."}, 404)
                me, op = roles.identity(), str(body.get("op", ""))
                try:
                    if op == "create":
                        return self._json({"ok": True, "folder": folders.create(target, me, str(body.get("name", "")))})
                    if op == "rename":
                        return self._json({"ok": True, "folder": folders.rename(target, me, str(body.get("folder", "")),
                                                                                str(body.get("name", "")))})
                    if op == "remove":
                        return self._json({"ok": True, "moved": folders.remove(target, me, str(body.get("folder", "")))})
                    if op == "move":
                        designs = body.get("items")
                        if not isinstance(designs, list) or len(designs) > 5000:
                            return self._json({"error": "bad request"}, 400)
                        n = folders.move(target, me, [str(d) for d in designs], str(body.get("folder", "")))
                        return self._json({"ok": True, "moved": n})
                except folders.FolderError as e:
                    return self._json({"error": str(e)}, 409)
                return self._json({"error": "unknown"}, 404)
            if path == "/api/show":
                target = str(body.get("path", ""))
                if os.name == "nt" and os.path.exists(target):
                    if os.path.isfile(target):
                        subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
                    else:
                        os.startfile(target)  # noqa: S606 - a folder the user chose
                    return self._json({"ok": True})
                return self._json({"error": "not found"}, 404)
            return self._json({"error": "unknown"}, 404)
    return Handler


def _history(path: str) -> list[dict]:
    if not os.path.isdir(os.path.join(path, ".git")):
        return []
    try:
        r = subprocess.run(["git", "-C", path, "log", "-20", "--format=%h%x09%ad%x09%s", "--date=format:%Y-%m-%d %H:%M"],
                           capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            out.append({"commit": parts[0], "date": parts[1], "message": parts[2]})
    return out


def serve(port: int = 0, open_browser: bool = True) -> None:
    token = secrets.token_urlsafe(24)
    job = Job()
    ThreadingHTTPServer.allow_reuse_address = False  # on Windows reuse lets two servers share a port
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(token, job))
    url = f"http://127.0.0.1:{httpd.server_address[1]}/?t={token}"
    print(f"sw2sc {__version__} vault window: {url}")
    print("Keep this window open while you use it; press Ctrl+C to stop.")
    sys.stdout.flush()
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
