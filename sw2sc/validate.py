"""Check a design against the rules SolidCraft enforces when it opens one.

Mirrors (in Python) the checks in SolidCraft's crates/doc/src/format.rs,
assembly.rs and metadata.rs that apply to what this converter writes. Returns a
list of problems; empty means the design should open.
"""
from __future__ import annotations

import json
import math

MAX_KEY_BYTES, MAX_TEXT_BYTES, MAX_VALUE_BYTES = 128, 4096, 64 * 1024
MAX_KEYS, MAX_TOTAL_BYTES, MAX_VALUE_DEPTH = 256, 256 * 1024, 32
WELL_KNOWN = {"project", "part_number", "revision", "author", "organization", "description", "license", "bom_type"}


def _depth(v, d=0):
    if isinstance(v, dict):
        return max([_depth(x, d + 1) for x in v.values()] or [d + 1])
    if isinstance(v, list):
        return max([_depth(x, d + 1) for x in v] or [d + 1])
    return d


def is_placement(m) -> bool:
    try:
        ax = [m[i][:3] for i in range(3)]
        dot = lambda a, b: sum(x * y for x, y in zip(a, b))
        cross = [ax[0][1] * ax[1][2] - ax[0][2] * ax[1][1], ax[0][2] * ax[1][0] - ax[0][0] * ax[1][2],
                 ax[0][0] * ax[1][1] - ax[0][1] * ax[1][0]]
        return (len(m) == 4 and all(len(r) == 4 for r in m)
                and all(isinstance(v, (int, float)) and math.isfinite(v) for r in m for v in r)
                and all(abs(v) <= 1e9 for v in m[3][:3])
                and all(abs(dot(a, a) - 1) < 1e-6 for a in ax)
                and abs(dot(ax[0], ax[1])) < 1e-6 and abs(dot(ax[0], ax[2])) < 1e-6
                and abs(dot(ax[1], ax[2])) < 1e-6 and dot(cross, ax[2]) > 0)
    except (TypeError, IndexError):
        return False


def _metadata(meta, where, problems):
    if not isinstance(meta, dict):
        problems.append(f"{where}: metadata is not an object")
        return
    if len(meta) > MAX_KEYS:
        problems.append(f"{where}: more than {MAX_KEYS} metadata keys")
    if len(json.dumps(meta, ensure_ascii=False).encode()) > MAX_TOTAL_BYTES:
        problems.append(f"{where}: metadata larger than 256 KiB")
    for k, v in meta.items():
        if len(k.encode()) > MAX_KEY_BYTES:
            problems.append(f"{where}: metadata key too long: {k[:40]}")
        if k in WELL_KNOWN:
            if not isinstance(v, str) or len(v.encode()) > MAX_TEXT_BYTES:
                problems.append(f"{where}: `{k}` must be text up to 4096 bytes")
        elif "." in k:
            if not isinstance(v, dict):
                problems.append(f"{where}: `{k}` must hold an object")
            elif len(json.dumps(v, ensure_ascii=False).encode()) > MAX_VALUE_BYTES:
                problems.append(f"{where}: `{k}` larger than 64 KiB")
            elif _depth(v) > MAX_VALUE_DEPTH:
                problems.append(f"{where}: `{k}` nested too deep")
        else:
            problems.append(f"{where}: unknown unprefixed metadata key `{k}`")


def validate(d: dict) -> list[str]:
    p: list[str] = []
    if not str(d.get("format", "")).startswith("solidcraft/"):
        p.append("missing or wrong `format`")
    for key in ("features", "components", "occurrences"):
        ids = [x.get("id") for x in d.get(key, [])]
        if len(ids) != len(set(ids)):
            p.append(f"duplicate {key} ids")
        if any(not isinstance(i, int) or i <= 0 for i in ids):
            p.append(f"{key}: ids must be positive integers")
    comps = {c["id"]: c for c in d.get("components", [])}
    occs = {o["id"]: o for o in d.get("occurrences", [])}
    for c in comps.values():
        if c.get("parent", 0) not in comps and c.get("parent", 0) != 0:
            p.append(f"component {c['id']} has unknown parent {c.get('parent')}")
        if "metadata" in c:
            _metadata(c["metadata"], f"component {c['name']}", p)
        for k, v in (c.get("properties") or {}).items():
            if not isinstance(v, str):
                p.append(f"component {c['name']}: property {k} is not text")
        seen, cur = set(), c["id"]
        while cur and cur not in seen:
            seen.add(cur)
            cur = comps.get(cur, {}).get("parent", 0)
        if cur:
            p.append(f"component {c['id']}: cyclic parents")
    if "metadata" in d:
        _metadata(d["metadata"], "design", p)
    for o in occs.values():
        if o.get("component") not in comps:
            p.append(f"occurrence {o['id']} places unknown component {o.get('component')}")
        if o.get("parent", 0) != 0 and o.get("parent") not in comps:
            p.append(f"occurrence {o['id']} sits in unknown component {o.get('parent')}")
        if o.get("component") == o.get("parent"):
            p.append(f"occurrence {o['id']} places a component inside itself")
        if not is_placement(o.get("transform")):
            p.append(f"occurrence `{o.get('name')}` is not placed by a rigid motion")
    # Component placement graph must be acyclic.
    children: dict[int, set[int]] = {}
    for o in occs.values():
        children.setdefault(o.get("parent", 0), set()).add(o.get("component"))
    state: dict[int, int] = {}

    def dfs(n, depth=0):
        if depth > 200:
            return True
        state[n] = 1
        for c in children.get(n, ()):
            if state.get(c) == 1 or (state.get(c) is None and dfs(c, depth + 1)):
                return True
        state[n] = 2
        return False
    if dfs(0):
        p.append("components are placed inside themselves (cycle)")
    for path in (d.get("visibility") or {}).get("hidden_occurrences", []):
        cur = 0
        for oid in path:
            o = occs.get(oid)
            if o is None or o.get("parent", 0) != cur:
                p.append(f"hidden path {path} does not lead from the root")
                break
            cur = o["component"]
    feats = {f.get("id"): f for f in d.get("features", [])}
    for cid, link in (d.get("links") or {}).items():
        if not str(cid).isdigit() or int(cid) not in comps:
            p.append(f"link on unknown component {cid}")
        f = feats.get(link.get("feature"))
        if f is None or f.get("type") != "import" or f.get("component") != int(cid):
            p.append(f"link on component {cid} does not name its own Import feature")
        path = link.get("path", "")
        if not path or "\\" in path or path.startswith("/") or ":" in path:
            p.append(f"link path must be relative with / separators: {path!r}")
    largest = max([x["id"] for k in ("features", "components", "occurrences") for x in d.get(k, [])] or [0])
    if d.get("next_id", 0) <= largest:
        p.append("next_id is not above every id")
    return p
