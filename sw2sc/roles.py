"""Who may do what in a vault.

* **Identity** is the account you are logged in as (Windows: DOMAIN\\user), not a name you
  type. The window and the command line take it from the system.
* `roles.json` in the vault lists the **admins** (they change the roles) and the
  **approvers** (they release and reject). Anyone can submit and start a new revision.
* **four_eyes**: an approver can't release an item they submitted themselves.
* A vault without `roles.json` is open: anyone can do anything, as before roles existed.
  The first person to set roles up becomes the first admin.

This guards against mistakes, not against someone determined: whoever can write the vault's
files can edit them. Every change to the roles is a Git commit, so the history shows it.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess

ROLES = "roles.json"
MAX_PEOPLE = 500
APPROVER_ACTIONS = ("release", "reject")


class RolesError(Exception):
    pass


def identity() -> str:
    """The logged-in account, as DOMAIN\\user on Windows (lower case)."""
    try:
        user = getpass.getuser()
    except Exception:  # no login name available
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    domain = os.environ.get("USERDOMAIN", "") if os.name == "nt" else ""
    return normal(f"{domain}\\{user}" if domain else user)


def normal(name: str) -> str:
    return " ".join(str(name).strip().split()).lower()[:200]


def load(vault: str) -> dict | None:
    """The vault's roles, or None when it has none (open vault)."""
    try:
        with open(os.path.join(vault, ROLES), encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise RolesError(f"{ROLES} can't be read ({e}); nobody can release until it is fixed") from e
    if not isinstance(data, dict):
        raise RolesError(f"{ROLES} is damaged; nobody can release until it is fixed")
    return {
        "admins": sorted({normal(x) for x in data.get("admins", []) if isinstance(x, str) and x.strip()}),
        "approvers": sorted({normal(x) for x in data.get("approvers", []) if isinstance(x, str) and x.strip()}),
        "four_eyes": bool(data.get("four_eyes", False)),
    }


def describe(vault: str, user: str) -> dict:
    """What the window shows: the user, their roles, and the vault's roles."""
    r = load(vault)
    if r is None:
        return {"user": user, "open": True, "admin": True, "approver": True, "roles": None}
    return {"user": user, "open": False, "admin": user in r["admins"], "approver": user in r["approvers"], "roles": r}


def may(vault: str, user: str, action: str) -> tuple[bool, str]:
    """Whether `user` may do a workflow action; when not, why."""
    try:
        r = load(vault)
    except RolesError as e:
        return (action not in APPROVER_ACTIONS), str(e)
    if r is None or action not in APPROVER_ACTIONS:
        return True, ""
    if user in r["approvers"]:
        return True, ""
    return False, f"only an approver can {action}; you are {user}. Ask an admin ({', '.join(r['admins']) or 'none set'})"


def four_eyes(vault: str) -> bool:
    try:
        r = load(vault)
    except RolesError:
        return True
    return bool(r and r["four_eyes"])


def _save(vault: str, r: dict, by: str, what: str) -> None:
    path = os.path.join(vault, ROLES)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"format": "sw2sc-roles/1", **r}, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)
    if shutil.which("git") and os.path.isdir(os.path.join(vault, ".git")):
        subprocess.run(["git", "-C", vault, "add", ROLES], capture_output=True)
        ident = []
        if not subprocess.run(["git", "-C", vault, "config", "user.email"], capture_output=True).stdout.strip():
            ident = ["-c", f"user.name={by}", "-c", "user.email=vault@localhost"]
        c = subprocess.run(["git", "-C", vault, *ident, "commit", "-q", "-m", f"Roles: {what}\n\nBy: {by}"],
                           capture_output=True)
        if c.returncode != 0:
            raise RolesError("the roles were saved but Git could not record the change")


def edit(vault: str, user: str, op: str, name: str = "", value: bool | None = None) -> dict:
    """Change the roles. op: add-admin, remove-admin, add-approver, remove-approver,
    four-eyes (value on/off). In an open vault the first edit makes `user` an admin too."""
    r = load(vault)
    first = r is None
    if first:
        r = {"admins": [user], "approvers": [], "four_eyes": False}
    elif user not in r["admins"]:
        raise RolesError(f"only an admin can change the roles; you are {user}")
    who = normal(name)
    if op in ("add-admin", "remove-admin", "add-approver", "remove-approver") and not who:
        raise RolesError("give the account, for example PC-NAME\\jane")
    if op == "add-admin":
        if who not in r["admins"]:
            r["admins"] = sorted(r["admins"] + [who])
        what = f"{who} is an admin"
    elif op == "remove-admin":
        if who not in r["admins"]:
            raise RolesError(f"{who} isn't an admin")
        if len(r["admins"]) == 1:
            raise RolesError("a vault with roles needs at least one admin")
        r["admins"] = [x for x in r["admins"] if x != who]
        what = f"{who} is no longer an admin"
    elif op == "add-approver":
        if who not in r["approvers"]:
            r["approvers"] = sorted(r["approvers"] + [who])
        what = f"{who} is an approver"
    elif op == "remove-approver":
        if who not in r["approvers"]:
            raise RolesError(f"{who} isn't an approver")
        r["approvers"] = [x for x in r["approvers"] if x != who]
        what = f"{who} is no longer an approver"
    elif op == "four-eyes":
        r["four_eyes"] = bool(value)
        what = "four-eyes " + ("on: approvers can't release what they submitted" if value else "off")
    else:
        raise RolesError(f"unknown change {op!r}")
    if len(r["admins"]) + len(r["approvers"]) > MAX_PEOPLE:
        raise RolesError("too many people in the roles")
    if first:
        what = f"roles set up; {user} is the first admin; " + what
    _save(vault, r, user, what)
    return r
