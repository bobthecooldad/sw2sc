"""Folders in a vault: a way to sort its designs, kept in `folders.json`.

Folders organise what the vault window shows; they don't move files. A design's file stays
where the import put it, so assembly links, releases in Git and the next import all keep
working. `folders.json` names the folders (`Bobbin`, `Bobbin/Idlers`) and which folder each
design is in. A design it doesn't name is in the folder its SolidWorks file came from, or at
the top. Every change is a Git commit, like the roles.
"""
from __future__ import annotations

import json
import os
import posixpath
import shutil
import subprocess

FOLDERS = "folders.json"
MAX_FOLDERS = 2000
MAX_NAME = 80
BAD_CHARS = set('\\:*?"<>|') | {chr(c) for c in range(32)}


class FolderError(Exception):
    pass


def _items(vault: str) -> dict:
    from . import vault as v
    try:
        with open(os.path.join(vault, v.INDEX), encoding="utf-8") as fh:
            return json.load(fh).get("items", {}) or {}
    except (OSError, ValueError):
        return {}


def load(vault: str) -> dict:
    """{"folders": [...], "items": {design: folder}} as saved; empty when there's none."""
    try:
        with open(os.path.join(vault, FOLDERS), encoding="utf-8") as fh:
            d = json.load(fh)
    except FileNotFoundError:
        return {"folders": [], "items": {}}
    except (OSError, ValueError) as e:
        raise FolderError(f"{FOLDERS} can't be read: {e}")
    folders = [f for f in d.get("folders", []) if isinstance(f, str)]
    items = {k: f for k, f in (d.get("items") or {}).items() if isinstance(k, str) and isinstance(f, str)}
    return {"folders": folders, "items": items}


def clean(name: str) -> str:
    """A folder path in the vault's spelling (`a/b`), or FolderError."""
    parts = [p.strip() for p in str(name).replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    if not parts:
        raise FolderError("Give the folder a name.")
    for p in parts:
        if p in (".", "..") or any(c in BAD_CHARS for c in p) or len(p) > MAX_NAME or p.endswith("."):
            raise FolderError(f"\"{p}\" can't be a folder name.")
    return "/".join(parts)


def _parents(folder: str) -> list[str]:
    parts = folder.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def view(vault: str) -> dict:
    """Every folder (parents included, sorted) and the folder of every design."""
    saved = load(vault)
    items = _items(vault)
    where = {}
    for key, it in items.items():
        if key in saved["items"]:
            where[key] = saved["items"][key]
        else:  # where its SolidWorks file came from
            where[key] = posixpath.dirname(str(it.get("source") or key))
    names = set()
    for f in list(saved["folders"]) + [f for f in where.values() if f]:
        names.update(_parents(f))
    return {"folders": sorted(names, key=lambda f: f.lower()), "items": where}


def _save(vault: str, d: dict, by: str, what: str) -> None:
    path = os.path.join(vault, FOLDERS)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"format": "sw2sc-folders/1", "folders": sorted(set(d["folders"])), "items": d["items"]},
                  fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    if shutil.which("git") and os.path.isdir(os.path.join(vault, ".git")):
        subprocess.run(["git", "-C", vault, "add", FOLDERS], capture_output=True)
        ident = []
        if not subprocess.run(["git", "-C", vault, "config", "user.email"], capture_output=True).stdout.strip():
            ident = ["-c", f"user.name={by}", "-c", "user.email=vault@localhost"]
        c = subprocess.run(["git", "-C", vault, *ident, "commit", "-q", "-m", f"Folders: {what}\n\nBy: {by}"],
                           capture_output=True)
        if c.returncode != 0 and b"nothing to commit" not in c.stdout + c.stderr:
            raise FolderError("the folders were saved but Git could not record the change")


def _state(vault: str) -> dict:
    """What to save: every folder there is now kept by name, every design's folder pinned, so
    renaming or removing one folder never moves designs in another."""
    v = view(vault)
    return {"folders": list(v["folders"]), "items": dict(v["items"])}


def create(vault: str, user: str, name: str) -> str:
    folder = clean(name)
    d = _state(vault)
    if folder in d["folders"]:
        raise FolderError(f"There is already a folder {folder}.")
    if len(d["folders"]) >= MAX_FOLDERS:
        raise FolderError("This vault has as many folders as it can hold.")
    d["folders"].extend(_parents(folder))
    _save(vault, d, user, f"new folder {folder}")
    return folder


def move(vault: str, user: str, designs: list[str], folder: str) -> int:
    """Put designs in `folder` ("" is the top). Only designs the vault lists."""
    target = clean(folder) if str(folder).strip("/ \\") else ""
    d = _state(vault)
    known = _items(vault)
    designs = [k for k in dict.fromkeys(designs) if k in known]
    if not designs:
        raise FolderError("None of those designs is in this vault.")
    if target:
        d["folders"].extend(_parents(target))
    for k in designs:
        d["items"][k] = target
    _save(vault, d, user, f"{len(designs)} design{'s' * (len(designs) != 1)} to {target or 'the top'}")
    return len(designs)


def rename(vault: str, user: str, old: str, new: str) -> str:
    old, new = clean(old), clean(new)
    d = _state(vault)
    if old not in d["folders"]:
        raise FolderError(f"There is no folder {old}.")
    if new == old:
        return new
    if new in d["folders"]:
        raise FolderError(f"There is already a folder {new}.")
    if new.startswith(old + "/"):
        raise FolderError("A folder can't go inside itself.")
    swap = lambda f: new + f[len(old):] if f == old or f.startswith(old + "/") else f  # noqa: E731
    d["folders"] = [swap(f) for f in d["folders"]] + _parents(new)
    d["items"] = {k: swap(f) for k, f in d["items"].items()}
    _save(vault, d, user, f"{old} renamed {new}")
    return new


def remove(vault: str, user: str, name: str) -> int:
    """Remove a folder and the folders in it; their designs go to its parent folder. The
    designs themselves stay in the vault. How many designs moved."""
    folder = clean(name)
    d = _state(vault)
    if folder not in d["folders"]:
        raise FolderError(f"There is no folder {folder}.")
    parent = posixpath.dirname(folder)
    inside = lambda f: f == folder or f.startswith(folder + "/")  # noqa: E731
    d["folders"] = [f for f in d["folders"] if not inside(f)]
    moved = [k for k, f in d["items"].items() if inside(f)]
    for k in moved:
        d["items"][k] = parent
    _save(vault, d, user, f"folder {folder} removed")
    return len(moved)
