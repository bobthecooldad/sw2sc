"""Release states for the items in a vault.

Every part and assembly design in a vault has a state and a revision:

    In Work --submit--> In Review --release--> Released
                ^           |                     |
                +--reject---+                     |
                +-----------revise (next revision)+

* Releasing needs the item to be In Review and everything it contains to be Released.
* A released item that changes on import, or that is revised, starts the next revision
  (A -> B) In Work. An item that changes while In Review goes back to In Work.
* Every change is recorded with who, when and a comment, and is a Git commit. A release is
  also a Git tag, so the exact released designs can be got back (`get_release`).

The record is `workflow.json` in the vault. Import never overwrites it; it only adds new
items and moves changed ones back to In Work.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import re
import shutil
import subprocess
import tarfile

from . import roles

WORKFLOW = "workflow.json"
IN_WORK, IN_REVIEW, RELEASED, OBSOLETE = "in_work", "in_review", "released", "obsolete"
LABELS = {IN_WORK: "In Work", IN_REVIEW: "In Review", RELEASED: "Released", OBSOLETE: "Obsolete"}
# action -> (states it may start from, state it leads to)
ACTIONS = {
    "submit": ((IN_WORK,), IN_REVIEW),
    "reject": ((IN_REVIEW,), IN_WORK),
    "release": ((IN_REVIEW,), RELEASED),
    "revise": ((RELEASED,), IN_WORK),
}
MAX_COMMENT = 2000


class WorkflowError(Exception):
    pass


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _git(vault: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", vault, *args], capture_output=True)


def _git_ok(vault: str) -> bool:
    return shutil.which("git") is not None and os.path.isdir(os.path.join(vault, ".git"))


def default_user(vault: str | None = None) -> str:
    if shutil.which("git"):
        args = ["git"] + (["-C", vault] if vault and os.path.isdir(vault) else []) + ["config", "user.name"]
        r = subprocess.run(args, capture_output=True)
        name = r.stdout.decode("utf-8", "replace").strip()
        if name:
            return name
    return os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"


def next_revision(rev: str) -> str:
    """A -> B, Z -> AA, 3 -> 4, 1.2 -> 1.3; anything else gets '.1' added."""
    rev = (rev or "").strip()
    if not rev:
        return "A"
    if re.fullmatch(r"[A-Z]+", rev):
        digits = [ord(c) - 65 for c in rev]
        i = len(digits) - 1
        while i >= 0:
            digits[i] += 1
            if digits[i] < 26:
                break
            digits[i] = 0
            i -= 1
        if i < 0:
            digits.insert(0, 0)
        return "".join(chr(65 + d) for d in digits)
    m = re.fullmatch(r"(.*?)(\d+)", rev)
    if m:
        return m.group(1) + str(int(m.group(2)) + 1).zfill(len(m.group(2)))
    return rev + ".1"


def _first_revision(item: dict) -> str:
    rev = str(item.get("revision") or "").strip()
    # a revision property from SolidWorks, if it is a plain label
    return rev if re.fullmatch(r"[A-Za-z0-9.\-]{1,12}", rev) else "A"


def load(vault: str) -> dict:
    try:
        with open(os.path.join(vault, WORKFLOW), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("items"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"format": "sw2sc-workflow/1", "items": {}}


def save(vault: str, data: dict) -> None:
    path = os.path.join(vault, WORKFLOW)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _index(vault: str) -> dict:
    try:
        with open(os.path.join(vault, "vault.json"), encoding="utf-8") as fh:
            return json.load(fh).get("items", {})
    except (OSError, ValueError):
        return {}


def _fingerprint(it: dict) -> str:
    """What an item's content depends on: its own source file and the exact designs it links
    to. A change in either changes the item."""
    import hashlib
    key = json.dumps([it.get("source_sha256"), sorted((it.get("depends") or {}).items())])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def sync(vault: str, items: dict, by: str = "import") -> list[str]:
    """After an import: add new items In Work, move changed ones back. Returns what moved."""
    data = load(vault)
    wf = data["items"]
    notes = []
    for drel, it in items.items():
        if it.get("failed"):
            continue
        src = it.get("source_sha256")
        fp = _fingerprint(it)
        w = wf.get(drel)
        if w is None:
            rev = _first_revision(it)
            wf[drel] = {"state": IN_WORK, "revision": rev, "source_sha256": src, "fingerprint": fp, "releases": [],
                        "history": [{"date": _now(), "by": by, "action": "add", "to": IN_WORK, "revision": rev,
                                     "comment": "added by import"}]}
            continue
        if w.get("fingerprint", fp) == fp and w.get("source_sha256") == src and w.get("state") != OBSOLETE:
            w.setdefault("fingerprint", fp)
            continue
        own = w.get("source_sha256") != src
        old_state = w.get("state")
        w["source_sha256"] = src
        w["fingerprint"] = fp
        why = "changed by import" if own else "a part or subassembly it contains changed"
        if old_state == RELEASED:
            w["revision"] = next_revision(w.get("revision", ""))
            note = f"{why} after release; revision {w['revision']} started"
        elif old_state == IN_REVIEW:
            note = f"{why} during review; back to In Work"
        elif old_state == OBSOLETE:
            note = "back in the source folder"
        else:
            note = why
        w["state"] = IN_WORK
        w["history"].append({"date": _now(), "by": by, "action": "change", "from": old_state, "to": IN_WORK,
                             "revision": w["revision"], "comment": note})
        if old_state != IN_WORK:
            notes.append(f"{drel}: {note}")
    for drel, w in wf.items():
        if drel not in items and w.get("state") != OBSOLETE:
            w["history"].append({"date": _now(), "by": by, "action": "remove", "from": w.get("state"),
                                 "to": OBSOLETE, "revision": w.get("revision"), "comment": "gone from the source folder"})
            w["state"] = OBSOLETE
            notes.append(f"{drel}: obsolete (gone from the source folder)")
    save(vault, data)
    return notes


def _tag_name(drel: str, rev: str) -> str:
    base = drel[:-len(".solidcraft")] if drel.endswith(".solidcraft") else drel
    raw = f"release/{base}/{rev}"
    t = re.sub(r"[\x00-\x20\x7f~^:?*\[\\]+", "-", raw)
    t = re.sub(r"\.\.+", ".", t).replace("@{", "-").strip("/.")
    t = "/".join(p.lstrip(".").rstrip(".") or "-" for p in t.split("/"))
    return re.sub(r"\.lock(?=/|$)", "-lock", t)


def _design_sha(vault: str, drel: str) -> str | None:
    import hashlib
    try:
        with open(os.path.join(vault, drel), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def submitter(w: dict) -> str | None:
    """Who submitted the item's current revision for review (None if nobody has)."""
    for h in reversed(w.get("history", [])):
        if h.get("revision") != w.get("revision"):
            break
        if h.get("action") == "submit":
            return roles.normal(h.get("by", ""))
        if h.get("action") in ("reject", "revise", "change"):
            return None
    return None


def _check(data: dict, items: dict, drel: str, action: str, comment: str, will_release: set | None = None,
           user: str = "", vault: str = "") -> None:
    """Raise WorkflowError if `action` can't be applied to `drel` now. `will_release`: items
    released in the same step (a tree release), which count as Released for the rule."""
    if action not in ACTIONS:
        raise WorkflowError(f"unknown action {action!r}; use one of {', '.join(ACTIONS)}")
    if vault:
        ok, why = roles.may(vault, user, action)
        if not ok:
            raise WorkflowError(why)
    w = data["items"].get(drel)
    if w is None:
        raise WorkflowError(f"{drel} is not in this vault's workflow")
    allowed, _ = ACTIONS[action]
    state = w.get("state")
    if state not in allowed:
        raise WorkflowError(f"can't {action} {drel}: it is {LABELS.get(state, state)}, "
                            f"and {action} needs {' or '.join(LABELS[s] for s in allowed)}")
    if action == "release":
        if items.get(drel, {}).get("failed"):
            raise WorkflowError(f"can't release {drel}: it failed to convert")
        will_release = will_release or set()
        blockers = []
        for u in items.get(drel, {}).get("uses", []):
            cw = data["items"].get(u["item"], {})
            if cw.get("state") != RELEASED and u["item"] not in will_release:
                blockers.append(f"{u['item']} ({LABELS.get(cw.get('state'), 'not in the workflow')})")
        if blockers:
            raise WorkflowError(f"can't release {drel}: everything it contains must be Released first. Not yet: "
                                + "; ".join(blockers[:20]) + (" ..." if len(blockers) > 20 else ""))
    if action == "reject" and not comment:
        raise WorkflowError("say why it is rejected (a comment is needed)")
    if action == "release" and vault and roles.four_eyes(vault) and submitter(w) == roles.normal(user):
        raise WorkflowError(f"{drel}: you submitted it, so someone else must release it (four-eyes rule)")


def _apply(vault: str, data: dict, drel: str, action: str, by: str, comment: str, date: str) -> str | None:
    """Apply a checked action in memory. Returns the release tag to make, if any."""
    w = data["items"][drel]
    _, target = ACTIONS[action]
    state = w.get("state")
    if action == "revise":
        w["revision"] = next_revision(w.get("revision", "A"))
    w["state"] = target
    w["history"].append({"date": date, "by": by, "action": action, "from": state, "to": target,
                         "revision": w["revision"], "comment": comment})
    if action != "release":
        return None
    tag = _tag_name(drel, w["revision"]) if _git_ok(vault) else None
    w["releases"].append({"revision": w["revision"], "date": date, "by": by, "comment": comment, "tag": tag,
                          "design_sha256": _design_sha(vault, drel), "source_sha256": w.get("source_sha256")})
    return tag


def _record(vault: str, data: dict, title: str, by: str, comment: str, tags: list[str]) -> None:
    """Save the workflow, then commit it and tag the releases (one commit for the whole step)."""
    save(vault, data)
    if not _git_ok(vault):
        return
    body = f"{title}\n\nBy: {by}" + (f"\n\n{comment}" if comment else "")
    _git(vault, "add", WORKFLOW)
    c = _git(vault, *_identity(vault), "commit", "-q", "-m", body)
    if c.returncode != 0:
        raise WorkflowError("the change was saved but Git could not record it: "
                            + (c.stderr or c.stdout).decode("utf-8", "replace").strip()[:300])
    failed = []
    for tag in tags:
        t = _git(vault, *_identity(vault), "tag", "-a", tag, "-m", body)
        if t.returncode != 0:
            failed.append(tag)
    if failed:
        raise WorkflowError("released, but these Git tags could not be made: " + ", ".join(failed[:10]))


def change(vault: str, drel: str, action: str, by: str = "", comment: str = "") -> dict:
    """Apply one action to one item; records it and commits. Returns the item's record."""
    data = load(vault)
    comment = (comment or "").strip()[:MAX_COMMENT]
    by = roles.normal(by) if (by or "").strip() else roles.identity()
    _check(data, _index(vault), drel, action, comment, user=by, vault=vault)
    old_rev = data["items"][drel].get("revision", "A")
    tag = _apply(vault, data, drel, action, by, comment, _now())
    w = data["items"][drel]
    name = os.path.basename(drel)
    title = {"submit": f"Submit {name} rev {w['revision']} for review",
             "reject": f"Reject {name} rev {w['revision']}",
             "release": f"Release {name} rev {w['revision']}",
             "revise": f"Start {name} rev {w['revision']} (after {old_rev})"}[action]
    _record(vault, data, title, by, comment, [tag] if tag else [])
    return w


# --- a whole assembly at once ---------------------------------------------------------------
TREE_ACTIONS = ("submit", "release")


def tree_items(items: dict, drel: str) -> list[str]:
    """The item and everything it contains, each once, children before the assemblies that
    use them (the order they must be released in)."""
    order, state = [], {}

    def visit(k, depth):
        if state.get(k) == 2 or depth > 64:
            return
        if state.get(k) == 1:
            raise WorkflowError(f"assemblies contain each other in a loop at {k}")
        state[k] = 1
        for u in items.get(k, {}).get("uses", []):
            visit(u["item"], depth + 1)
        state[k] = 2
        order.append(k)
    visit(drel, 0)
    return order


def plan_tree(vault: str, drel: str, action: str, user: str = "") -> dict:
    """What a tree action would do, without doing it:
    {"steps": [{"item", "from", "revision", "do"}], "skip": [...], "blockers": [...]}.
    do is "submit", "release" or "submit+release" (an In Work item released in one step)."""
    if action not in TREE_ACTIONS:
        raise WorkflowError(f"a whole assembly can only be submitted or released, not {action!r}")
    data, items = load(vault), _index(vault)
    if drel not in data["items"]:
        raise WorkflowError(f"{drel} is not in this vault's workflow")
    user = roles.normal(user) if (user or "").strip() else roles.identity()
    steps, skip, blockers = [], [], []
    ok, why = roles.may(vault, user, action)
    if not ok:
        blockers.append(why)
    four = action == "release" and roles.four_eyes(vault)
    for k in tree_items(items, drel):
        w = data["items"].get(k)
        if w is None:
            blockers.append(f"{k} is not in the workflow (it may have failed to convert)")
            continue
        st = w.get("state")
        if items.get(k, {}).get("failed"):
            blockers.append(f"{k} failed to convert")
        elif st == OBSOLETE:
            blockers.append(f"{k} is Obsolete (its file left the source folder)")
        elif st == RELEASED:
            skip.append({"item": k, "revision": w.get("revision"), "why": "already Released"})
        elif action == "submit" and st == IN_REVIEW:
            skip.append({"item": k, "revision": w.get("revision"), "why": "already In Review"})
        else:
            do = "submit" if action == "submit" else ("release" if st == IN_REVIEW else "submit+release")
            if four and do == "submit+release":
                blockers.append(f"{k} is In Work: with the four-eyes rule it must be submitted first, "
                                "and released by someone else")
            elif four and submitter(w) == user:
                blockers.append(f"{k}: you submitted it, so someone else must release it (four-eyes rule)")
            steps.append({"item": k, "from": st, "revision": w.get("revision"), "do": do})
    return {"item": drel, "action": action, "steps": steps, "skip": skip, "blockers": blockers}


def change_tree(vault: str, drel: str, action: str, by: str = "", comment: str = "") -> dict:
    """Submit or release an assembly with everything it contains, all or nothing, in one
    commit (and a tag for each release). Returns the plan that was carried out."""
    by = roles.normal(by) if (by or "").strip() else roles.identity()
    plan = plan_tree(vault, drel, action, by)
    if plan["blockers"]:
        raise WorkflowError("nothing was changed. " + "; ".join(plan["blockers"][:20])
                            + (" ..." if len(plan["blockers"]) > 20 else ""))
    if not plan["steps"]:
        raise WorkflowError("nothing to do: everything is already "
                            + ("Released" if action == "release" else "In Review or Released"))
    data, items = load(vault), _index(vault)
    comment = (comment or "").strip()[:MAX_COMMENT]
    top_rev = data["items"][drel].get("revision", "")
    note = comment or f"with {os.path.basename(drel)} rev {top_rev}"
    releasing = {s["item"] for s in plan["steps"] if "release" in s["do"]}
    date = _now()
    tags = []
    # check every step first against the state the step before it leaves behind
    for s in plan["steps"]:
        for a in s["do"].split("+"):
            _check(data, items, s["item"], a, note, releasing, user=by, vault=vault)
            tag = _apply(vault, data, s["item"], a, by, note, date)
            if tag:
                tags.append(tag)
    n = len(plan["steps"])
    name = os.path.basename(drel)
    title = (f"Release {name} rev {top_rev} and {n - 1} items it contains" if action == "release"
             else f"Submit {name} rev {top_rev} and {n - 1} items it contains for review")
    if n == 1:
        title = f"{'Release' if action == 'release' else 'Submit'} {name} rev {top_rev}"
    _record(vault, data, title, by, comment, tags)
    return plan


def _identity(vault: str) -> list[str]:
    """Commit as the configured Git user; fall back to a local name only if none is set."""
    r = _git(vault, "config", "user.email")
    if r.stdout.strip():
        return []
    return ["-c", f"user.name={default_user(vault)}", "-c", "user.email=vault@localhost"]


def status(vault: str) -> dict:
    data = load(vault)
    return data["items"]


def get_release(vault: str, drel: str, revision: str, dest: str) -> list[str]:
    """Write the released designs of an item, and everything it contained then, into dest
    (from the release's Git tag). Returns the files written."""
    w = load(vault)["items"].get(drel)
    if not w:
        raise WorkflowError(f"{drel} is not in this vault's workflow")
    rel = next((r for r in w.get("releases", []) if r["revision"] == revision), None)
    if rel is None:
        raise WorkflowError(f"{drel} has no released revision {revision}")
    if not rel.get("tag") or not _git_ok(vault):
        raise WorkflowError("this release has no Git tag to get it back from")
    tag = rel["tag"]
    shown = _git(vault, "show", f"{tag}:vault.json")
    if shown.returncode != 0:
        raise WorkflowError(f"tag {tag} is missing")
    items = json.loads(shown.stdout.decode("utf-8")).get("items", {})
    want, stack = set(), [drel]
    while stack:
        cur = stack.pop()
        if cur in want or cur not in items:
            continue
        want.add(cur)
        stack.extend(u["item"] for u in items[cur].get("uses", []))
    arc = _git(vault, "archive", "--format=tar", tag, "--", *sorted(want))
    if arc.returncode != 0:
        raise WorkflowError("git archive failed: " + arc.stderr.decode("utf-8", "replace")[:300])
    os.makedirs(dest, exist_ok=True)
    root = os.path.abspath(dest)
    written = []
    with tarfile.open(fileobj=io.BytesIO(arc.stdout)) as tar:
        for m in tar.getmembers():
            target = os.path.abspath(os.path.join(root, m.name))
            if not m.isfile() or os.path.commonpath([root, target]) != root:
                continue  # only regular files inside dest
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tar.extractfile(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            written.append(m.name)
    return written
