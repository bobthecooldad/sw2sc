"""Check a part's rebuilt feature tree against the solid SolidWorks saved (F-006).

The feature tree read by sw2sc.features is written as SolidCraft features and evaluated with
solidcraft-cli; it is used only when its volume, surface area and bounding box match the part's
own solid (converted as an import) within 0.1 %, and both geometric differences fit the same
relative volume tolerance. What the file leaves open, an extrude's direction or which of two
plane references a sketch uses, is settled by trying the candidates the file gives and keeping
the one that matches.
"""
from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
import tempfile

from . import features

REL = 1e-3
MAX_TRIES = 120
TIME_BUDGET = 300   # seconds a part's rebuild search may take; past it the part keeps its solid
_deadline = [float("inf")]
# the box check's two passes: strict first; a second pass lets a partial build lie outside the
# part's box when a cut still to come could trim it, only where the first pass found nothing and
# that check stopped such a build (an imported blank wider than the part)
_box = {"relax": False, "blocked": False}


def find_cli() -> str | None:
    """solidcraft-cli: SOLIDCRAFT_CLI, next to the SolidCraft app on the PATH, or a build in
    C:\\dev\\solidcraft."""
    env = os.environ.get("SOLIDCRAFT_CLI")
    if env and os.path.isfile(env):
        return env
    found = []
    for c in (shutil.which("solidcraft-cli"),
              os.path.join(os.path.dirname(shutil.which("solidcraft") or ""), "solidcraft-cli.exe"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "SolidCraft", "solidcraft-cli.exe"),
              r"C:\dev\solidcraft\target\release\solidcraft-cli.exe"):
        if c and os.path.isfile(c) and os.path.normcase(os.path.abspath(c)) not in [os.path.normcase(os.path.abspath(f)) for f in found]:
            found.append(c)
    if not found:
        return None
    return max(found, key=_cli_rank)  # the newest, and at that the checkout's own build


_KERNEL_CACHE: dict = {}


def _own_checkout(cli: str) -> str | None:
    """The checkout the CLI itself was built in (`<checkout>/target/release/solidcraft-cli`),
    or None for a copy installed elsewhere (the SolidCraft app)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(cli))))
    return root if os.path.isfile(os.path.join(root, "Cargo.toml")) else None


def _cli_rank(cli: str) -> tuple:
    """Newest version first; at the same version a build from a checkout outranks an installed
    copy (the app updates on its own, and its build may be anything behind the checkout), then
    the later build."""
    try:
        mtime = os.path.getmtime(cli)
    except OSError:
        mtime = 0.0
    return (cli_version(cli), 1 if _own_checkout(cli) else 0, mtime)


def _parse_version(text: str) -> tuple:
    """The release numbers of each dotted part, stopping at the suffix that follows them:
    "0.47.0-nightly.20261123.157.1" -> (0, 47, 0), "solidcraft-cli 0.44.1" -> (0, 44, 1). A
    nightly of today's main therefore compares equal to the release in its Cargo.toml, and the
    build time against the checkout's last commit is what tells them apart."""
    import re
    word = next((w for w in text.split() if re.match(r"\d", w)), "")
    nums = []
    for part in word.split("."):
        m = re.match(r"(\d+)(.*)", part)
        if not m:
            break
        nums.append(int(m.group(1)))
        if m.group(2):   # "0-nightly": the release ends here
            break
    return tuple(nums)


def fmt_version(v: tuple) -> str:
    return ".".join(str(x) for x in v) if v else "unknown"


_VERSION_CACHE: dict = {}


def cli_version(cli: str) -> tuple:
    """solidcraft-cli's version (`--version` prints e.g. "solidcraft-cli 0.44.1", and a nightly
    build "0.47.0-nightly.20261123.157.1"): the leading numbers of each dotted part, so a
    suffix doesn't send the newest build below an older release; (0,) if unknown. Cached by the
    binary's modification time, so a fresh build is read again."""
    try:
        key = (os.path.abspath(cli), os.path.getmtime(cli) if os.path.isfile(cli) else None)
    except OSError:
        key = (cli, None)
    if key in _VERSION_CACHE:
        return _VERSION_CACHE[key]
    try:
        out = subprocess.run([cli, "--version"], capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
        v = _parse_version(out) or (0,)
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        v = (0,)
    _VERSION_CACHE[key] = v
    return v


def checkout_dir(cli: str | None = None) -> str | None:
    """The SolidCraft source a CLI should have been built from: SOLIDCRAFT_SRC, the checkout the
    CLI sits in (`<checkout>/target/release/solidcraft-cli.exe`), or a checkout at
    C:\\dev\\solidcraft. None when there is no source on this machine to compare with."""
    env = os.environ.get("SOLIDCRAFT_SRC")
    if env and os.path.isfile(os.path.join(env, "Cargo.toml")):
        return env
    if cli:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(cli))))
        if os.path.isfile(os.path.join(root, "Cargo.toml")):
            return root
    for c in (r"C:\dev\solidcraft",):
        if os.path.isfile(os.path.join(c, "Cargo.toml")):
            return c
    return None


def checkout_version(src: str) -> tuple | None:
    """The version in the checkout's Cargo.toml (`[workspace.package] version = "0.47.0"`)."""
    import re
    try:
        with open(os.path.join(src, "Cargo.toml"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
                if m:
                    return _parse_version(m.group(1))
    except OSError:
        pass
    return None


def checkout_commit(src: str) -> tuple[str | None, float | None]:
    """The checkout's HEAD: (sha, committer time as epoch seconds), or (None, None) without git."""
    import datetime
    try:
        r = subprocess.run(["git", "-C", src, "log", "-1", "--format=%H %cI"], capture_output=True, timeout=30)
        sha, when = r.stdout.decode("utf-8", "replace").split()
        return sha, datetime.datetime.fromisoformat(when.replace("Z", "+00:00")).timestamp()
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None, None


def kernel_status(cli: str | None = None) -> dict:
    """Whether the solidcraft-cli a rebuild uses is the one the checkout would build: its version
    against the checkout's, and the binary's build time against the checkout's last commit. A
    result measured on a stale kernel means nothing for the code in the checkout, so the check
    tools record this and warn (F-006). Cached by the binary's modification time."""
    import time
    cli = cli if cli is not None else find_cli()
    try:
        key = (cli, os.path.getmtime(cli) if cli and os.path.isfile(cli) else None)
    except OSError:
        key = (cli, None)
    if key in _KERNEL_CACHE:
        return _KERNEL_CACHE[key]
    st = _kernel_status(cli)
    _KERNEL_CACHE[key] = st
    return st


def _kernel_status(cli: str | None) -> dict:
    import time
    st = {"cli": cli, "version": cli_version(cli) if cli else (0,), "checkout": None,
          "checkout_version": None, "commit": None, "commit_time": None, "stale": False, "why": ""}
    src = checkout_dir(cli)
    st["checkout"] = src
    if not src:
        st["why"] = "no SolidCraft checkout on this machine to compare with"
        return st
    st["checkout_version"] = checkout_version(src)
    st["commit"], st["commit_time"] = checkout_commit(src)
    if not cli:
        st.update(stale=True, why="no solidcraft-cli found")
        return st
    if _own_checkout(cli) is None:
        # an installed copy: it can report the same version and still not be the checkout's build
        st.update(stale=True, why=f"the CLI is an installed copy ({fmt_version(st['version'])}), "
                                 f"not a build of {src}" +
                                 (f" ({fmt_version(st['checkout_version'])})" if st["checkout_version"] else ""))
    elif st["checkout_version"] and st["version"] < st["checkout_version"]:
        st.update(stale=True, why=f"the CLI is {fmt_version(st['version'])}, the checkout "
                                 f"{fmt_version(st['checkout_version'])}")
    elif st["commit_time"] and os.path.isfile(cli) and os.path.getmtime(cli) < st["commit_time"] - 60:
        built = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(cli)))
        last = time.strftime("%Y-%m-%d %H:%M", time.localtime(st["commit_time"]))
        st.update(stale=True, why=f"the CLI was built {built}, before the checkout's last commit ({last})")
    return st


def kernel_line(st: dict) -> str:
    """The kernel status as one line for a report: which CLI, from which checkout and commit,
    and a STALE reason when there is one."""
    import time
    if not st.get("cli"):
        return "solidcraft-cli: none found, so no rebuild can be checked"
    s = f"solidcraft-cli {fmt_version(st['version'])} at {st['cli']}"
    if st.get("checkout"):
        s += f" (checkout {st['checkout']}"
        if st.get("commit"):
            s += f", commit {st['commit'][:9]}"
            if st.get("commit_time"):
                s += " of " + time.strftime("%Y-%m-%d %H:%M", time.localtime(st["commit_time"]))
        s += ")"
    if st.get("stale"):
        s += (f" STALE: {st['why']} - results do not describe the checkout; rebuild it"
              " (cargo build --release -p solidcraft-cli)")
    return s


def past_deadline() -> bool:
    """Whether a rebuild's time budget has run out (always False outside a rebuild)."""
    import time
    return time.time() > _deadline[0]


def evaluate(cli: str, path: str) -> dict | None:
    # past a rebuild's budget nothing more is evaluated: the loops still running in the search
    # then end at once (they evaluated every remaining option before, for minutes)
    if past_deadline():
        return None
    try:
        r = subprocess.run([cli, "eval", path], capture_output=True, timeout=180)
        d = json.loads(r.stdout.decode("utf-8", "replace"))
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None
    t = d.get("total") or {}
    boxes = [bd.get("bbox") for bd in d.get("bodies", []) if bd.get("bbox")]
    lo = [min(bx["min"][k] for bx in boxes) for k in range(3)] if boxes else None
    hi = [max(bx["max"][k] for bx in boxes) for k in range(3)] if boxes else None
    errors = [s.get("error") for s in d.get("timeline", []) if s.get("error")]
    coms = [bd.get("center_of_mass") for bd in d.get("bodies", []) if bd.get("center_of_mass")]
    return {"volume": t.get("volume_mm3"), "area": t.get("area_mm2"), "lo": lo, "hi": hi, "errors": errors,
            "com": coms[0] if coms else None}


def same(a: dict | None, b: dict | None) -> bool:
    if not a or not b or not a["volume"] or a["errors"] or not a["area"] or not b["area"]:
        return False
    close = lambda x, y: abs(x - y) <= REL * max(abs(x), abs(y), 1.0)  # noqa: E731
    # a reference imported as open faces has no volume: its area and box still say it all
    if b["volume"] and not close(a["volume"], b["volume"]):
        return False
    if not close(a["area"], b["area"]):
        return False
    if a["lo"] and b["lo"]:
        size = max(max(h - lo for lo, h in zip(b["lo"], b["hi"])), 1.0)
        return all(abs(x - y) <= REL * size for x, y in zip(a["lo"] + a["hi"], b["lo"] + b["hi"]))
    return True


def _raw_eval(cli: str, path: str, script: str | None = None) -> dict | None:
    args = [cli, "eval", script or path]
    if script:
        args += ["--in", path]
    try:
        result = subprocess.run(args, capture_output=True, timeout=180)
        return json.loads(result.stdout.decode("utf-8", "replace"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _difference_volume(cli: str, target_path: str, tool_path: str) -> float | None:
    """Volume of target minus tool through SolidCraft, or None if that difference cannot be checked."""
    target = _raw_eval(cli, target_path)
    tool = _raw_eval(cli, tool_path)
    target_names = [b.get("name") for b in (target or {}).get("bodies", []) if b.get("name")]
    tool_names = [b.get("name") for b in (tool or {}).get("bodies", []) if b.get("name")]
    if len(target_names) != 1 or len(tool_names) != 1:
        return None
    tmp = tempfile.mkdtemp(prefix="sw2sc-shape-")
    try:
        insert = os.path.join(tmp, "insert.json")
        combined = os.path.join(tmp, "combined.solidcraft")
        reply = os.path.join(tmp, "insert-result.json")
        script = {"commands": [{"command": "component.insert_design", "params": {"path": tool_path, "name": "Reference"}}]}
        with open(insert, "w", encoding="utf-8") as fh:
            json.dump(script, fh)
        result = subprocess.run([cli, "run", insert, "--in", target_path, "--results", "--json-out", reply,
                                 "--save", combined], capture_output=True, timeout=180)
        if result.returncode:
            return None
        with open(reply, encoding="utf-8") as fh:
            inserted = json.load(fh)
        created = inserted[-1].get("created_bodies", []) if inserted else []
        if len(created) != 1:
            return None
        cut = os.path.join(tmp, "cut.json")
        script = {"commands": [{"command": "solid.combine", "params": {"target": target_names[0], "tools": created, "operation": "cut"}}]}
        with open(cut, "w", encoding="utf-8") as fh:
            json.dump(script, fh)
        evaluated = _raw_eval(cli, combined, cut)
        if not evaluated or any(s.get("error") for s in evaluated.get("timeline", [])):
            return None
        volume = evaluated.get("total", {}).get("volume_mm3")
        return float(volume) if volume is not None else None
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def shape_differences_within(extra: float | None, missing: float | None, reference_volume: float) -> bool:
    """Both directions must be checked and within the same relative volume tolerance."""
    if extra is None or missing is None:
        return False
    return abs(extra) <= REL * max(abs(reference_volume), 1.0) and abs(missing) <= REL * max(abs(reference_volume), 1.0)


def same_shape(cli: str, reference_path: str, candidate_path: str) -> bool:
    """Metric agreement followed by actual geometric difference in both directions."""
    reference = _raw_eval(cli, reference_path)
    volume = (reference or {}).get("total", {}).get("volume_mm3")
    if not volume:
        return False
    extra = _difference_volume(cli, candidate_path, reference_path)
    missing = _difference_volume(cli, reference_path, candidate_path)
    return shape_differences_within(extra, missing, volume)


LAST: dict = {}   # the closest rebuild attempt yet: its numbers, against the reference


def _gap(a: dict, b: dict) -> float:
    """How far apart two evaluations are, for keeping the closest attempt: volume first, then
    area, and a design that doesn't build counts as far."""
    va, vb = a.get("volume") or 0.0, b.get("volume") or 0.0
    aa, ab = a.get("area") or 0.0, b.get("area") or 0.0
    gap = abs(va - vb) / max(abs(vb), 1e-9) + abs(aa - ab) / max(abs(ab), 1e-9)
    return gap + (1.0 if a.get("errors") else 0.0)


def _judge(cli: str, path: str, ref: dict) -> bool:
    """Evaluate a candidate, remember how close it came (LAST), and say whether it matches."""
    r = evaluate(cli, path)
    if r:
        if not LAST.get("eval") or _gap(r, LAST["ref"]) < _gap(LAST["eval"], LAST["ref"]):
            LAST["eval"] = r
    return same(r, ref)


def mismatch_signature(ours: dict | None, ref: dict | None) -> str:
    """Why a rebuild doesn't match, in the shape of a cause: which number is wrong and which way.
    The first thing to look at follows from it — an island or a cut that didn't take makes
    material, a missing feature takes it away, a missing fillet changes the area alone."""
    if not ours:
        return "no build to compare"
    if ours.get("errors"):
        msg = str(ours["errors"][0])
        msg = msg[len("not supported yet: "):] if msg.startswith("not supported yet: ") else msg
        return "does not build: " + msg.split(". ")[0]
    if not ours.get("volume") or not ref or not ref.get("volume"):
        return "no volume to compare"
    dv = (ours["volume"] - ref["volume"]) / abs(ref["volume"])
    da = (ours["area"] - ref["area"]) / abs(ref["area"]) if ref.get("area") else 0.0
    if abs(dv) <= REL and abs(da) > REL:
        return f"same volume, area {da:+.1%}: a fillet or chamfer is missing or wrong"
    if dv > REL:
        return f"too much material ({dv:+.1%}): a loop is an island, or a cut didn't take"
    if dv < -REL:
        return f"too little material ({dv:+.1%}): a feature is missing, or its direction is wrong"
    if ours.get("lo") and ref.get("lo"):
        d = [o - r for o, r in zip(ours["lo"] + ours["hi"], ref["lo"] + ref["hi"])]
        if any(abs(x) > 0.1 for x in d):
            return ("volume and area agree, the box doesn't: " +
                    ", ".join(f"{x:+.2f}" for x in d) + " mm (lo, hi)")
    return f"close but not within 0.1 %: volume {dv:+.2%}, area {da:+.2%}"


def fully_decoded(feats: list | None) -> bool:
    if not feats:
        return False
    if any(f.kind == "tbd" or (f.reason and f.kind != "absorbed") for f in feats):
        return False
    if any(f.kind == "sketch" and (not f.sketch.planes or f.sketch.problems) for f in feats):
        return False
    kinds = {f.kind for f in feats}
    # an import is a solid to build on when its body as imported is in the file
    if any(f.kind == "import" and not f.import_body for f in feats):
        return False
    return bool(kinds & {"boss", "cut", "revolve", "revcut", "sweep"})  # fillets need a solid first


def rebuild(feats: list, reference: dict, name: str, cli: str | None = None) -> dict | None:
    """The feature tree as a SolidCraft design whose rebuild matches `reference` (a design with
    the part's own solid), or None."""
    cli = cli or find_cli()
    if not cli or not fully_decoded(feats):
        return None
    tmp = tempfile.mkdtemp(prefix="sw2sc-verify-")
    LAST.clear()
    import time
    _deadline[0] = time.time() + TIME_BUDGET
    try:
        ref_path = os.path.join(tmp, "ref.solidcraft")
        with open(ref_path, "w", encoding="utf-8") as fh:
            json.dump(reference, fh)
        ref = evaluate(cli, ref_path)
        if not ref or not (ref["volume"] or ref["area"]):
            return None
        LAST["ref"] = ref
        extr = [f for f in feats if f.kind in ("boss", "cut")]
        revs = [f for f in feats if f.kind in ("revolve", "revcut")]
        sks = {f.name: f for f in feats if f.kind == "sketch"}
        sk_list = list(sks.values())
        options = ["positive", "negative", "symmetric"]
        rev_opts = [[(a, s) for a in range(min(8, len(features.revolve_axis_options(sks[f.profile].sketch)))) for s in (1, -1)]
                    for f in revs]
        path = os.path.join(tmp, "feat.solidcraft")
        _box.update(relax=False, blocked=False)
        for constraints in (True, False):   # without the sketches' constraints only if they spoil it
            tries = 0
            found = _search(name, feats, extr, revs, sk_list, options, rev_opts, path, cli, ref, constraints, ref_path)
            if found:
                return found
            if _box["blocked"]:
                _box["relax"] = True
                found = _search(name, feats, extr, revs, sk_list, options, rev_opts, path, cli, ref, constraints, ref_path)
                _box.update(relax=False, blocked=False)
                if found:
                    return found
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _deadline[0] = float("inf")


def _search(name, feats, extr, revs, sk_list, options, rev_opts, path, cli, ref, constraints, ref_path):
    """Try the candidates the file leaves open (sketch planes, revolve axes and sides, extrude
    directions); the first design whose rebuild matches `ref`, or None."""
    tries = 0
    done = set()
    # plane sets whose sequence stopped short: (arc and revolve choices, the planes of the
    # sketches before the feature it got stuck at). What is built up to there depends only on
    # those, so a later set with the same planes for them stops there too and is skipped
    stuck: list = []
    # arcs whose centre the file leaves open: none turned first, then each sketch's alone, then all
    alts = [f for f in sk_list if f.sketch.alt_centres]
    arc_opts = [{}]
    for f in alts:
        arc_opts.append({"arcs:" + f.name: frozenset(f.sketch.alt_centres)})
        if len(f.sketch.alt_centres) > 1:
            for n in f.sketch.alt_centres:
                arc_opts.append({"arcs:" + f.name: frozenset([n])})
    if len(alts) > 1:
        arc_opts.append({"arcs:" + f.name: frozenset(f.sketch.alt_centres) for f in alts})
    # every part is built in sequence: each extrude tried every way it changes the solid, as a
    # boss or a cut where its kind is open, from a face of the body so far, without a stray loop.
    # (Plain extrude-and-cut parts used to try direction sets only, and missed all of those.)
    seq = True
    # built in sequence, each extrude's direction is chosen as it is built: one set of directions
    # is enough here. (Every other set was skipped one by one: 3 ** extrudes turns of the loop,
    # billions for a part with 20 extrudes, which spun until the time budget ran out.)
    one_set = [tuple(options[0] for _ in extr)]
    # each sketch's planes, those that put its points inside the part's box first (a sketch on a
    # face of the part lies on the part; a cut's outline may reach past it, so it only orders)
    def outside(f, k):
        if not ref or not ref.get("lo"):
            return 0
        (x, y, _n), t = f.sketch.planes[k][0], f.sketch.planes[k][1]
        tol = REL * max(max(h - lo for lo, h in zip(ref["lo"], ref["hi"])), 1.0) + 1e-6
        n_out = 0
        for u, v in f.sketch.points.values():
            w = [(t[i] + u * x[i] + v * y[i]) * 1000 for i in range(3)]
            n_out += any(w[i] < ref["lo"][i] - tol or w[i] > ref["hi"][i] + tol for i in range(3))
        return n_out
    plane_orders = [sorted(range(len(f.sketch.planes)), key=lambda k, f=f: outside(f, k)) for f in sk_list]
    for pc, rc, ac, dc in ((pc, rc, ac, dc)
                           for pc in itertools.product(*plane_orders)
                           for ac in arc_opts
                           for rc in itertools.product(*rev_opts)
                           for dc in (one_set if seq else itertools.product(options, repeat=len(extr)))):
            if __import__("time").time() > _deadline[0]:
                return None
            if True:
                key = (pc, tuple(sorted((k, tuple(sorted(v))) for k, v in ac.items())), rc)
                if seq and key in done:
                    continue          # directions are chosen in _sequential: once per plane/arc/revolve choice
                if seq and any(k0 == key[1:] and all(pc[j] == v for j, v in fixed) for k0, fixed in stuck):
                    continue
                tries += 1
                if tries > MAX_TRIES:
                    return None
                choices = dict(ac, **{f.name: (c, None) for f, c in zip(extr, dc)})
                choices.update({f.name: c for f, c in zip(revs, rc)})
                planes = {f.name: i for f, i in zip(sk_list, pc)}
                if seq:
                    done.add(key)
                    # features in order: each extrude only the ways it changes the solid, each
                    # fillet or chamfer on the edges that fit (one pass, not every combination)
                    reach = [-1]
                    for d in _sequential(name, feats, dict(choices), planes, constraints, cli, os.path.dirname(path), ref, reach):
                        with open(path, "w", encoding="utf-8") as fh:
                            json.dump(d, fh)
                        if _judge(cli, path, ref) and same_shape(cli, ref_path, path):
                            return d
                        tries += 1
                        if tries > MAX_TRIES:
                            return None
                    if 0 <= reach[0] < len(feats) and __import__("time").time() <= _deadline[0]:
                        before = {x.name for x in feats[:reach[0]]}
                        stuck.append((key[1:], tuple((j, pc[j]) for j, f in enumerate(sk_list) if f.name in before)))
                    continue
                for d in _with_fillets(name, feats, choices, planes, constraints, cli, os.path.dirname(path), {}):
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(d, fh)
                    if _judge(cli, path, ref) and same_shape(cli, ref_path, path):
                        return d
                    tries += 1
                    if tries > MAX_TRIES:
                        return None
    return None


MAX_FILLET_CHOICES = 10


def _mirror_planes(f, feats, choices, planes, constraints, picked, name, cli, tmp):
    """Planes a mirror may be about: those its record names, then the planar faces of the body
    built so far whose SolidCraft name fits the face SolidWorks names (a side or an end face of
    that feature), then every other planar face, then the three planes through the origin."""
    from . import fillets
    out = []

    def add(origin, x, y):
        pl = {"origin": [round(c, 9) for c in origin], "x_dir": [round(c, 12) for c in x], "y_dir": [round(c, 12) for c in y]}
        if pl not in out:
            out.append(pl)
    for (x, y, _n), t in f.mirror_planes:
        add([c * 1000 for c in t], x, y)
    d = features.design(name, feats, choices, planes, constraints, picked)
    d.pop("pending", None)
    faces = fillets.body_faces(d, cli, tmp) or []
    by_name = {g["name"]: g["id"] for g in d["features"]}
    want = None
    if f.mirror_face:
        kind, fid, _v = f.mirror_face
        src = next((x.name for x in feats if x.fid == fid), None)
        if src in by_name:
            want = (kind, by_name[src])

    def fits(face):
        fc = fillets._faces(face["name"] + "|" + face["name"]) if face.get("name") else None
        return bool(fc and want and fc[0][0] == want[0] and fc[0][1] == want[1])
    planar = [x for x in faces if x.get("plane_normal")]
    for face in sorted(planar, key=lambda x: not fits(x)):
        n = face["plane_normal"]
        a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
        dot = sum(p * q for p, q in zip(a, n))
        x = [p - dot * q for p, q in zip(a, n)]
        ln = sum(c * c for c in x) ** 0.5
        x = [c / ln for c in x]
        y = [n[1] * x[2] - n[2] * x[1], n[2] * x[0] - n[0] * x[2], n[0] * x[1] - n[1] * x[0]]
        add(face["centroid"], x, y)
    for x, y in (((1, 0, 0), (0, 1, 0)), ((0, 1, 0), (0, 0, 1)), ((0, 0, 1), (1, 0, 0))):
        add((0, 0, 0), x, y)
    return out[:24]
SAME = 1e-6


def face_moves(f, faces, lo=None, hi=None) -> list:
    """The ways a draft or a move face can have been made, most faces first, found by where its
    faces end up: each flat face of the body so far (`faces`, as model.faces gives them) whose
    plane, drafted by the angle about an axis direction or moved by the distance along its normal,
    is one of the part's own flat faces (`f.final_planes`). A draft: (face points, a point of its
    neutral plane, its pull); the neutral plane is where each face's plane and its drafted plane
    meet, so the faces that share one are one draft. A move face: (face points, +1 out / -1 in)."""
    import math as _m
    fin = f.final_planes
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))  # noqa: E731
    near = lambda a, b: max(abs(x - y) for x, y in zip(a, b)) < 1e-5  # noqa: E731
    size = max([h - l for l, h in zip(lo, hi)] + [1.0]) if lo and hi else 1000.0
    tol = 1e-6 * size + 1e-4
    groups: dict = {}
    if f.kind == "draft":
        t = _m.radians(f.draft_deg)
        for x in faces:
            m, q = x["plane_normal"], x["point"]
            for ax in range(3):
                if abs(m[ax]) > 1e-6:
                    continue
                for s in (1, -1):
                    e = [0.0, 0.0, 0.0]
                    e[ax] = float(s)
                    n = [c * _m.cos(t) + d * _m.sin(t) for c, d in zip(m, e)]
                    for nn, r in fin:
                        if not near(nn, n):
                            continue
                        h = dot(n, [a - b for a, b in zip(r, q)]) / _m.sin(t)   # along the pull
                        level = q[ax] + s * h
                        if lo and hi and not (lo[ax] - tol <= level <= hi[ax] + tol):
                            continue
                        key = (ax, s, round(level, 4))
                        pts = groups.setdefault(key, [])
                        if not any(near(p, q) for p in pts):
                            pts.append(list(q))
        out = []
        for (ax, s, level), pts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            o = [0.0, 0.0, 0.0]
            o[ax] = level
            pull = [0.0, 0.0, 0.0]
            pull[ax] = float(s)
            out.append((pts, o, pull))
        return out
    d = f.move_mm
    strict: dict = {1: [], -1: []}
    loose: dict = {1: [], -1: []}
    for x in faces:
        m, q = x["plane_normal"], x["point"]
        here = dot(m, q)
        stays = any(near(nn, m) and abs(dot(nn, r) - here) < tol for nn, r in fin)
        for sgn in (1, -1):
            if any(near(nn, m) and abs(dot(nn, r) - here - sgn * d) < tol for nn, r in fin):
                loose[sgn].append(list(q))
                if not stays:
                    strict[sgn].append(list(q))
    out = []
    for sgn in (1, -1):
        for pts in (strict[sgn], loose[sgn]):
            if pts and (pts, sgn) not in out:
                out.append((pts, sgn))
    return sorted(out, key=lambda o: (o[0] is not strict[o[1]], -len(o[0])))


def _prefix(name, feats, choices, planes, constraints, picked, upto, cli, tmp):
    d = features.design(name, feats, choices, planes, constraints, picked, upto)
    d.pop("pending", None)
    p = os.path.join(tmp, "prefix.solidcraft")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return d, evaluate(cli, p)


def outside_loops(sk, plane, ref) -> list:
    """The curves of the sketch's loops that reach past the part's box, the sketch on `plane`."""
    if not ref or not ref.get("lo"):
        return []
    (ax, ay, _n), t = plane[0], plane[1]
    tol = REL * max(max(h - lo for lo, h in zip(ref["lo"], ref["hi"])), 1.0) + 1e-6
    out_ids = []
    for ids, poly in features._loops(sk):
        for u, v in poly:
            w = [(t[k] + u * ax[k] + v * ay[k]) * 1000 for k in range(3)]
            if any(w[k] < ref["lo"][k] - tol or w[k] > ref["hi"][k] + tol for k in range(3)):
                out_ids += ids
                break
    return sorted(set(out_ids))


def _sequential(name, feats, choices, planes, constraints, cli, tmp, ref=None, progress=None):
    """Complete designs, built feature by feature: an extrude takes each direction that changes
    the solid built so far (a boss adds to it, a cut takes from it; a way that does nothing or
    fails is no way SolidWorks built it), a fillet or chamfer each edge set that fits (both
    sides for a one-sided chamfer). Revolves keep the choice in `choices`."""
    from . import fillets
    import math as _m
    order = [f for f in feats if f.kind in ("boss", "cut", "revolve", "revcut", "fillet", "chamfer", "hole", "mirror", "thread", "pattern", "dome", "rib", "split",
                                            "sweep", "sweepcut", "shell", "scale", "draft", "moveface")]
    # a scale changes the solid's size and place: before it, neither the volume bounds nor the
    # part's box say anything about the solid built so far
    first_scale = next((k for k, f in enumerate(order) if f.kind == "scale"), len(order))

    def most(f):
        """The most an extrude can add or take away: its profile's area (its loops, arcs bulging
        their full half-disc and circles whole, so never less than the truth) times its depth;
        None when unbounded (through all, or not read)."""
        sk = next((x.sketch for x in feats if x.name == f.profile), None)
        if f.kind not in ("boss", "cut") or not sk or f.through_all or not f.depth_mm:
            return None
        area = 0.0
        for ids, poly in features._loops(sk):
            a = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]))) / 2
            area += a * 1e6
        P = sk.points
        area += sum(_m.pi * (_m.dist(P[a], P[c]) * 1000) ** 2 / 2 for a, _b, c in sk.arcs)
        area += sum(_m.pi * (r * 1000) ** 2 for _c, r in sk.circles)
        return area * f.depth_mm * 1.05

    # what the features after each step can still add (bosses) and take away (cuts) at most
    adds, takes = [], []
    for i in range(len(order) + 1):
        rest = order[i:]
        a = [most(f) for f in rest if f.kind in ("boss", "revolve") or getattr(f, "alt_kind", None) == "boss"]
        t = [most(f) for f in rest if f.kind in ("cut", "revcut", "hole") or getattr(f, "alt_kind", None) == "cut"]
        adds.append(None if any(x is None for x in a) else sum(a))
        takes.append(None if any(x is None for x in t) or any(f.kind in ("hole", "split") for f in rest) else sum(t))

    def reachable(r, i):
        """Can the solid after step i still become the part? The bosses still to come add at
        most adds[i+1]; cuts, holes, chamfers and fillets only take material away."""
        if not ref or not ref.get("volume") or i < first_scale:
            return True
        v, target = r["volume"], ref["volume"]
        if adds[i + 1] is not None and v + adds[i + 1] < target * (1 - REL):
            return False
        if takes[i + 1] is not None and not any(f.kind in ("fillet", "chamfer") for f in order[i + 1:]) \
                and v - takes[i + 1] > target * (1 + REL):
            return False
        return True

    # whether a cut is still to come after step i: material outside the part's box can still go
    # a split still to come may throw away a piece: the build before it can reach past the part
    split_after = [any(x.kind == "split" for x in feats[feats.index(f) + 1:]) for f in order]
    cut_after = [any(x.kind in ("cut", "hole", "revcut", "sweepcut", "split") or getattr(x, "alt_kind", None) == "cut"
                     for x in feats[feats.index(f) + 1:]) for f in order]

    # whether anything still to come after step i can add material (and so grow the solid's box):
    # cuts, holes, fillets, chamfers and shells never reach past the solid they work on
    add_after = [any(x.kind in ("boss", "revolve", "sweep", "mirror", "pattern", "thread", "dome", "rib", "scale", "import")
                     or getattr(x, "alt_kind", None) == "boss" for x in feats[feats.index(f) + 1:]) for f in order]

    def ok(r, i):
        """A partial build that can still become the part: it built, and it lies inside the
        part's box (later bosses only add, fillets and chamfers don't reach past it) unless a
        cut still to come can trim it (an imported blank wider than the part)."""
        if not r or r["errors"] or not r["volume"]:
            return False
        if ref and ref.get("lo") and r.get("lo") and first_scale == len(order) and not (_box["relax"] and cut_after[i])                 and not split_after[i]:
            size = max(max(h - lo for lo, h in zip(ref["lo"], ref["hi"])), 1.0)
            tol = REL * size
            if any(a < b - tol for a, b in zip(r["lo"], ref["lo"])) or any(a > b + tol for a, b in zip(r["hi"], ref["hi"])):
                if cut_after[i]:
                    _box["blocked"] = True
                return False
        # with nothing left that adds material, a build that falls short of the part's box can't
        # become the part (a boss read as a cut: the part goes on past it)
        if ref and ref.get("lo") and r.get("lo") and first_scale == len(order) and not add_after[i] and not split_after[i]:
            tol = REL * max(max(h - lo for lo, h in zip(ref["lo"], ref["hi"])), 1.0)
            if any(a > b + tol for a, b in zip(r["lo"], ref["lo"])) or any(a < b - tol for a, b in zip(r["hi"], ref["hi"])):
                return False
        return True

    def step(i, choices, picked, vol):
        if __import__("time").time() > _deadline[0]:
            return
        if progress is not None:
            progress[0] = max(progress[0], feats.index(order[i]) if i < len(order) else len(feats))
        if i == len(order):
            d = features.design(name, feats, choices, planes, constraints, picked)
            d.pop("pending", None)
            yield d
            return
        f = order[i]
        if f.kind in ("boss", "cut"):
            seen = []
            first = not any(x.kind in ("boss", "cut", "revolve", "revcut", "sweep") for x in order[:i]) and \
                not any(x.kind == "import" for x in feats[:feats.index(f)])
            ops = [None] + ([("join" if f.alt_kind == "boss" else "cut")] if f.alt_kind and not first else [])
            if getattr(f, "from_face", False):
                # its sketch has no curves of its own (model edges it selects): an extrude of a face
                # of the body so far, each flat one tried, both ways
                if first:
                    return
                from . import fillets as _fl
                d_pre = features.design(name, feats, choices, planes, constraints, picked, feats[feats.index(f) - 1].name)
                d_pre.pop("pending", None)
                faces = [x for x in (_fl.body_faces(d_pre, cli, tmp) or []) if x.get("plane_normal")][:16]
                unchanged = None
                for x in faces:
                    for opt in ("positive", "negative"):
                        for op in ops:
                            c2 = dict(choices, **{f.name: (opt, op)})
                            p2 = dict(picked, **{"face:" + f.name: [list(x["point"]), list(x["plane_normal"])]})
                            _d, r = _prefix(name, feats, c2, planes, constraints, p2, f.name, cli, tmp)
                            if not ok(r, i):
                                continue
                            if vol is not None and abs(r["volume"] - vol) <= SAME * max(1.0, vol):
                                if unchanged is None:
                                    unchanged = (c2, p2, r["volume"])
                                continue
                            if not reachable(r, i):
                                continue
                            key = (round(r["volume"], 6), round(r["area"], 6), tuple(round(v, 6) for v in (r["lo"] or []) + (r["hi"] or [])))
                            if key in seen:
                                continue
                            seen.append(key)
                            yield from step(i + 1, c2, p2, r["volume"])
                if not seen and unchanged is not None:
                    yield from step(i + 1, *unchanged)
                return
            # no depth in the file: through all, or up to a flat face of the body so far
            tos = [None]
            if f.through_all and not first:
                from . import fillets as _fl
                d0 = features.design(name, feats, choices, planes, constraints, picked)
                d0.pop("pending", None)
                tos += [tuple(x["point"]) for x in (_fl.body_faces(d0, cli, tmp) or []) if x.get("plane_normal")][:16]
            # a boss through all reaches as far as the body does (SolidCraft's through all, made
            # for cuts, runs past it): the distance from its sketch plane to the body's box
            spans = {}
            if f.through_all and not first and f.kind == "boss":
                _d0, r0 = _prefix(name, feats, choices, planes, constraints, picked, order[i - 1].name, cli, tmp)
                sk_f = next((x for x in feats if x.name == f.profile), None)
                if r0 and r0.get("lo") and sk_f and sk_f.sketch.planes:
                    pl = sk_f.sketch.planes[min((planes or {}).get(sk_f.name, 0), len(sk_f.sketch.planes) - 1)]
                    (_x, _y, n), t = pl[0], pl[1]
                    o = [c * 1000 for c in t]
                    corners = [(a, b, c) for a in (r0["lo"][0], r0["hi"][0]) for b in (r0["lo"][1], r0["hi"][1])
                               for c in (r0["lo"][2], r0["hi"][2])]
                    reach = [sum((p - q) * m for p, q, m in zip(cn, o, n)) for cn in corners]
                    up, down = max(reach), -min(reach)
                    spans = {"positive": up, "negative": down, "symmetric": 2 * max(up, down)}
            # a sketch whose plane reads through the origin may be on a face of the body so far
            # whose plane wasn't stored: it is tried from each side of the body's box along its normal
            starts = []
            if not first and not f.through_all and f.depth_mm:
                sk_f = next((x for x in feats if x.name == f.profile), None)
                pl = sk_f.sketch.planes[min((planes or {}).get(sk_f.name, 0), len(sk_f.sketch.planes) - 1)] \
                    if sk_f and sk_f.sketch.planes else None
                if pl and all(abs(c) < 1e-12 for c in pl[1]):
                    d_pre, r0 = _prefix(name, feats, choices, planes, constraints, picked, order[i - 1].name, cli, tmp)
                    if r0 and r0.get("lo"):
                        n = pl[0][2]
                        corners = [(a, b, c) for a in (r0["lo"][0], r0["hi"][0]) for b in (r0["lo"][1], r0["hi"][1])
                                   for c in (r0["lo"][2], r0["hi"][2])]
                        along = [sum(p * m for p, m in zip(cn, n)) for cn in corners]
                        # the sides of the body's box, then its flat faces parallel to the sketch (a
                        # pocket's floor), at most 8
                        cands = [max(along), min(along)]
                        from . import fillets as _fl
                        for x in (_fl.body_faces(d_pre, cli, tmp) or []) if d_pre else []:
                            pn = x.get("plane_normal")
                            if pn and abs(sum(p * m for p, m in zip(pn, n))) > 1 - 1e-9:
                                cands.append(sum(p * m for p, m in zip(x["point"], n)))
                        for v in cands:
                            if abs(v) > 1e-6 and all(abs(v - w) > 1e-6 for w in starts) and len(starts) < 8:
                                starts.append(v)
            # a boss can't reach past the part: loops of its sketch that do (a stray circle read
            # with the outline) are also tried left out, all together
            drops = [None]
            if f.kind == "boss" and not getattr(f, "thin_mm", None):
                sk_f = next((x for x in feats if x.name == f.profile), None)
                if sk_f and sk_f.sketch.planes:
                    pl = sk_f.sketch.planes[min((planes or {}).get(sk_f.name, 0), len(sk_f.sketch.planes) - 1)]
                    out_ids = outside_loops(sk_f.sketch, pl, ref)
                    if out_ids and any(not set(ids) & set(out_ids) for ids, _p in features._loops(sk_f.sketch)):
                        drops.append(out_ids)
            sides = ["center", "inside", "outside"] if getattr(f, "thin_mm", None) else [None]
            # a cut may keep its profile and take the rest (SolidWorks' flip side to cut): tried last
            flips = [False, True] if f.kind == "cut" and not first and not getattr(f, "thin_mm", None) else [False]
            unchanged = None
            for opt, op, to, side, sp, st, dr, fl in ((o, p, t, sd, s_, s2, d2, fs) for fs in flips for sd in sides for t in tos for p in ops
                                                  for o in (("symmetric",) if f.mid_plane else ("positive", "negative", "symmetric"))
                                                  for s_ in ([None] + ([spans[o]] if o in spans and spans[o] > 1e-6 else []))
                                                  for s2 in [None] + starts for d2 in drops):
                if fl and (to is not None or dr is not None):
                    continue
                if to is not None and (opt == "symmetric" or sp is not None):
                    continue
                if st is not None and (to is not None or sp is not None):
                    continue
                if dr is not None and to is not None:
                    continue
                c2 = dict(choices, **{f.name: (opt, op)})
                p_to = dict(picked, **{"to:" + f.name: to}) if to is not None else picked
                if sp is not None:
                    p_to = dict(p_to, **{"span:" + f.name: sp})
                if st is not None:
                    p_to = dict(p_to, **{"start:" + f.name: st})
                if dr is not None:
                    p_to = dict(p_to, **{"drop:" + f.name: dr})
                if side:
                    p_to = dict(p_to, **{"thin:" + f.name: side})
                if fl:
                    p_to = dict(p_to, **{"flipside:" + f.name: True})
                _d, r = _prefix(name, feats, c2, planes, constraints, p_to, f.name, cli, tmp)
                if not ok(r, i):
                    continue
                if vol is not None and abs(r["volume"] - vol) <= SAME * max(1.0, vol):
                    if unchanged is None:
                        unchanged = (c2, p_to, r["volume"])
                    continue
                if not reachable(r, i):
                    continue
                key = (round(r["volume"], 6), round(r["area"], 6), tuple(round(x, 6) for x in (r["lo"] or []) + (r["hi"] or [])))
                if key in seen:
                    continue      # the same solid another way (a through-all cut): one is enough
                seen.append(key)
                yield from step(i + 1, c2, p_to, r["volume"])
            # no way of it changes the solid (a boss inside one before it, from the same sketch): it
            # adds nothing, and the rest goes on from the solid as it was
            if not seen and unchanged is not None:
                yield from step(i + 1, *unchanged)
            return
        if f.kind in ("revolve", "revcut"):
            # the sketch, axis and angle come from the feature and its sketch; the outer search
            # chooses between the axes the sketch records and the two directions
            _d, r = _prefix(name, feats, choices, planes, constraints, picked, f.name, cli, tmp)
            if not ok(r, i) or not reachable(r, i):
                return
            yield from step(i + 1, choices, picked, r["volume"])
            return
        if f.kind == "shell":
            # open at each flat face of the body so far (those fitting the face SolidWorks names first)
            from . import fillets as _fl
            d0 = features.design(name, feats, choices, planes, constraints, picked)
            d0.pop("pending", None)
            by_name = {g["name"]: g["id"] for g in d0["features"]}
            want = None
            if f.mirror_face:
                src = next((x.name for x in feats if x.fid == f.mirror_face[1]), None)
                want = (f.mirror_face[0], by_name.get(src))
            faces = [x for x in (_fl.body_faces(d0, cli, tmp) or []) if x.get("plane_normal")]
            fits = lambda x: bool(want and (lambda fc: fc and fc[0][0] == want[0] and fc[0][1] == want[1])(  # noqa: E731
                _fl._faces(x["name"] + "|" + x["name"]) if x.get("name") else None))
            seen = []
            for face in sorted(faces, key=lambda x: not fits(x))[:16]:
                p2 = dict(picked, **{"shell:" + f.name: [face["point"]]})
                _d, res = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(res, i) or not reachable(res, i):
                    continue
                key = (round(res["volume"], 6), round(res["area"], 6))
                if key in seen:
                    continue
                seen.append(key)
                yield from step(i + 1, choices, p2, res["volume"])
            return
        if f.kind in ("draft", "moveface"):
            # the faces of the body so far that end up as the part's own faces once drafted or moved
            from . import fillets as _fl
            d0, r0 = _prefix(name, feats, choices, planes, constraints, picked, f.name, cli, tmp)
            faces = [x for x in (_fl.body_faces(d0, cli, tmp) or []) if x.get("plane_normal")]
            seen = []
            for opt in face_moves(f, faces, (r0 or {}).get("lo"), (r0 or {}).get("hi"))[:8]:
                p2 = dict(picked, **{f.kind + ":" + f.name: opt})
                _d, res = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(res, i) or not reachable(res, i):
                    continue
                if r0 and r0.get("volume") and abs(res["volume"] - r0["volume"]) <= SAME * max(1.0, r0["volume"]):
                    continue   # it changed nothing: not those faces
                key = (round(res["volume"], 6), round(res["area"], 6))
                if key in seen:
                    continue
                seen.append(key)
                yield from step(i + 1, choices, p2, res["volume"])
            return
        if f.kind in ("sweep", "sweepcut"):
            seen = []
            for swap in (False, True):
                p2 = dict(picked, **{"swap:" + f.name: swap})
                _d, res = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(res, i) or not reachable(res, i):
                    continue
                key = (round(res["volume"], 6), round(res["area"], 6))
                if key in seen:
                    continue
                seen.append(key)
                yield from step(i + 1, choices, p2, res["volume"])
            return
        if f.kind == "scale":
            # about the origin, the centre of mass or the middle of the box of the solid so far
            _d0, r0 = _prefix(name, feats, choices, planes, constraints, picked, order[i - 1].name, cli, tmp) if i else (None, None)
            origins = [[0.0, 0.0, 0.0]]
            if r0 and r0.get("com"):
                origins.append(list(r0["com"]))
            if r0 and r0.get("lo"):
                origins.append([(a + c) / 2 for a, c in zip(r0["lo"], r0["hi"])])
            seen = []
            for o in origins:
                p2 = dict(picked, **{"scale:" + f.name: o})
                _d, res = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(res, i) or not reachable(res, i):
                    continue
                key = (round(res["volume"], 6), round(res["area"], 6), tuple(round(x, 6) for x in (res["lo"] or [])))
                if key in seen:
                    continue
                seen.append(key)
                yield from step(i + 1, choices, p2, res["volume"])
            return
        if f.kind == "rib":
            # which side of its free edge the wall fills, and whether the ends run on to the body
            seen = []
            for flip, extend in ((False, True), (True, True), (False, False), (True, False)):
                p2 = dict(picked, **{"rib:" + f.name: (flip, extend)})
                _d, res = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(res, i) or not reachable(res, i):
                    continue
                key = (round(res["volume"], 6), round(res["area"], 6))
                if key in seen:
                    continue
                seen.append(key)
                yield from step(i + 1, choices, p2, res["volume"])
            return
        if f.kind == "dome":
            # on a flat face that is a whole disc (its area that of the circle through its edge)
            from . import fillets as _fl
            d0 = features.design(name, feats, choices, planes, constraints, picked)
            d0.pop("pending", None)
            seen = []
            for face in _fl.body_faces(d0, cli, tmp) or []:
                n = face.get("plane_normal")
                if not n:
                    continue
                c, pt = face["centroid"], face["point"]
                r = (face["area"] / 3.141592653589793) ** 0.5
                if not (0.98 * r <= max(sum((p - q) ** 2 for p, q in zip(pt, c)) ** 0.5, 1e-9) <= 1.02 * r) and r > 0:
                    pass   # (the pick point need not be on the rim: the area decides)
                for sgn in (1, -1):
                    nn = [sgn * x for x in n]
                    p2 = dict(picked, **{"dome:" + f.name: (c, nn, r)})
                    _d, res = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                    if not ok(res, i) or not reachable(res, i):
                        continue
                    key = (round(res["volume"], 6), round(res["area"], 6))
                    if key in seen:
                        continue
                    seen.append(key)
                    yield from step(i + 1, choices, p2, res["volume"])
            return
        if f.kind == "pattern":
            from . import fillets as _fl
            solid = [x for x in order[:i] if x.kind in ("boss", "cut", "hole", "fillet", "chamfer")]
            last_boss = max((k for k, x in enumerate(solid) if x.kind == "boss"), default=0)
            sets = [[x.name for x in solid[-1:]], [x.name for x in solid[last_boss + 1:]], [x.name for x in solid[last_boss:]]]
            whats = [tuple(s) for k, s in enumerate(sets) if s and s not in sets[:k]]
            pt = f.pattern
            pats = []
            if pt["kind"] == "linear":
                axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
                if f.path:
                    path = next((x.sketch for x in feats if x.name == f.path), None)
                    axes = features.straight_pattern_directions(path, planes.get(f.path, 0)) if path else []
                for a in axes:
                    p = {"type": "rectangular", "dir1": list(a), "count1": repr(int(pt["count1"])), "spacing1": repr(pt["spacing1"])}
                    if pt.get("count2") and pt.get("spacing2"):
                        for a2 in axes:
                            if abs(sum(x * y for x, y in zip(a, a2))) < 1e-9:
                                pats.append(dict(p, dir2=list(a2), count2=repr(int(pt["count2"])), spacing2=repr(pt["spacing2"])))
                    else:
                        pats.append(p)
            else:
                d0 = features.design(name, feats, choices, planes, constraints, picked)
                d0.pop("pending", None)
                lines = [(c["cylinder"]["origin"], c["cylinder"]["axis"]) for c in (_fl.body_faces(d0, cli, tmp) or []) if c.get("cylinder")]
                lines += [((0, 0, 0), (1, 0, 0)), ((0, 0, 0), (0, 1, 0)), ((0, 0, 0), (0, 0, 1))]
                n = int(pt["count1"])
                totals = [pt["angle"]] + ([pt["angle"] * (n - 1)] if pt["angle"] * (n - 1) <= 360 and n > 1 and pt["angle"] < 360 else [])
                for o, a in lines:
                    for tot in totals:
                        pc = {"type": "circular", "origin": [round(c, 9) for c in o], "axis": [round(c, 12) for c in a],
                              "count": repr(n), "angle": f"{tot:g} deg"}
                        if pc not in pats:
                            pats.append(pc)
            # every way first, then the ways that change the solid most: a direction that puts
            # copies off the part changes it less (FTC 09's LPattern1: 2 of its 4 holes)
            seen, ways = [], []
            for what in whats:
                for p in pats[:40]:
                    p2 = dict(picked, **{"pattern:" + f.name: (p, what)})
                    _d, r = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                    if not ok(r, i) or not reachable(r, i):
                        continue
                    key = (round(r["volume"], 6), round(r["area"], 6))
                    if key in seen:
                        continue
                    seen.append(key)
                    ways.append((abs(r["volume"] - vol) if vol is not None and r["volume"] is not None else 0.0, p2, r["volume"]))
            for _change, p2, v in sorted(ways, key=lambda w: -w[0]):
                yield from step(i + 1, choices, p2, v)
            return
        if f.kind == "thread":
            # on a cylinder of the body so far about its size (the major diameter outside, about
            # the tap drill inside), from either end
            from . import fillets as _fl
            d0 = features.design(name, feats, choices, planes, constraints, picked)
            d0.pop("pending", None)
            r_major = f.thread["diameter"] / 2
            seen = []
            for face in _fl.body_faces(d0, cli, tmp) or []:
                cyl = face.get("cylinder")
                if not cyl or not (0.7 * r_major <= cyl["radius"] <= 1.05 * r_major):
                    continue
                ax, c, pt = cyl["axis"], face["centroid"], face["point"]
                h = face["area"] / (2 * 3.141592653589793 * cyl["radius"])
                along = sum((p - q) * a for p, q, a in zip(pt, c, ax))
                rim = [p - along * a for p, a in zip(pt, ax)]          # the point, moved to mid-height
                for sgn in (1, -1):
                    start = [p + sgn * (h / 2 - 1e-3) * a for p, a in zip(rim, ax)]
                    p2 = dict(picked, **{"thread:" + f.name: (pt, start)})
                    _d, r = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                    if not ok(r, i) or not reachable(r, i):
                        continue
                    key = (round(r["volume"], 6), round(r["area"], 6))
                    if key in seen:
                        continue
                    seen.append(key)
                    yield from step(i + 1, choices, p2, r["volume"])
            return
        if f.kind == "mirror":
            # the body so far mirrored about each plane it may be, and joined
            seen = []
            # what it mirrors: the cuts since the last boss, every feature after the first, the
            # feature before it, or the whole body (SolidWorks' list of features isn't read yet)
            solid = [x for x in order[:i] if x.kind in ("boss", "cut", "hole", "fillet", "chamfer")]
            last_boss = max((k for k, x in enumerate(solid) if x.kind == "boss"), default=0)
            sets = [[x.name for x in solid[last_boss + 1:]], [x.name for x in solid[1:]], [x.name for x in solid[-1:]]]
            whats = [tuple(s) for k, s in enumerate(sets) if s and s not in sets[:k]] + ["body"]
            mirror_choices = [(pl, w) for w in whats
                              for pl in _mirror_planes(f, feats, choices, planes, constraints, picked, name, cli, tmp)]
            for plane, what in mirror_choices:
                p2 = dict(picked, **{"mirror:" + f.name: (plane, what)})
                _d, r = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(r, i) or not reachable(r, i):
                    continue
                key = (round(r["volume"], 6), round(r["area"], 6))
                if key in seen:
                    continue
                seen.append(key)
                yield from step(i + 1, choices, p2, r["volume"])
            return
        if f.kind == "split":
            # each tool it may be (the planes its record names, else each straight line of its
            # sketch), keeping both pieces, the first or the second
            tools = []
            for (x, y, _n), t in f.mirror_planes:
                pl = {"origin": [round(c * 1000, 9) for c in t], "x_dir": [round(c, 12) for c in x], "y_dir": [round(c, 12) for c in y]}
                if {"plane": pl} not in tools:
                    tools.append({"plane": pl})
            if f.profile:
                sk = next(x.sketch for x in feats if x.name == f.profile)
                tools += [{"line": f"l{n + 1}"} for n in range(len(sk.lines)) if n not in sk.construction]
            seen = []
            for tool in tools:
                for keep in (None, 0, 1):
                    p2 = dict(picked, **{"split:" + f.name: (tool, keep)})
                    _d, r = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                    if not ok(r, i) or not reachable(r, i):
                        continue
                    key = (round(r["volume"], 6), round(r["area"], 6))
                    if key in seen:
                        continue
                    seen.append(key)
                    yield from step(i + 1, choices, p2, r["volume"])
            return
        if f.kind == "hole":
            # blind (its depth) or through all, drilled one way or the other: the ways that cut
            seen = []
            # which of its placement sketch's points it drills at: by their flag (the user's
            # points against those SolidWorks added), points at the same place once
            sk = next(x.sketch for x in feats if x.name == f.profile)
            flags = sk.point_flags
            uniq = {}
            for pid in sorted(sk.points):
                uniq.setdefault(tuple(round(c, 9) for c in sk.points[pid]), pid)
            keep = set(uniq.values())
            sets = [frozenset(p for p in keep if flags.get(p) == 2), frozenset(p for p in keep if flags.get(p) in (1, 2)),
                    frozenset(p for p in keep if flags.get(p) == 1), frozenset(keep)]
            sets = [s for k, s in enumerate(sets) if s and s not in sets[:k]]
            for opt in [(a, c, s) for s in sets for a, c in ((False, False), (False, True), (True, False), (True, True))]:
                if opt[0] and "depth" not in f.hole and seen:
                    break
                p2 = dict(picked, **{"hole:" + f.name: opt[:2], "holepts:" + f.name: opt[2]})
                _d, r = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(r, i) or (vol is not None and r["volume"] >= vol - SAME * max(1.0, vol)):
                    continue
                key = (round(r["volume"], 6), round(r["area"], 6))
                if key in seen:
                    continue
                seen.append(key)
                yield from step(i + 1, choices, p2, r["volume"])
            return
        d = features.design(name, feats, choices, planes, constraints, picked)
        if d.pop("pending", None) != f.name:
            return
        flips = [False, True] if f.kind == "chamfer" and (f.chamfer_mm2 is not None or abs(f.chamfer_deg - 45) > 1e-6) else [False]
        for edges, amaps in fillets.candidates(d, f, feats, cli, tmp, picked.get(""))[:MAX_FILLET_CHOICES]:
            for flip in flips:
                p2 = dict(picked, **{f.name: edges, "": amaps, "flip:" + f.name: flip})
                _d, r = _prefix(name, feats, choices, planes, constraints, p2, f.name, cli, tmp)
                if not ok(r, i) or not reachable(r, i):
                    continue
                yield from step(i + 1, choices, p2, r["volume"])

    yield from step(0, choices, {}, None)


def _with_fillets(name, feats, choices, planes, constraints, cli, tmp, picked):
    """Every complete design for these choices: each fillet's edges found in the design built
    up to it (sw2sc.fillets), trying the edge sets that fit (a few at most), in order."""
    d = features.design(name, feats, choices, planes, constraints, picked)
    pending = d.pop("pending", None)
    if pending is None:
        yield d
        return
    from . import fillets
    f = next(x for x in feats if x.name == pending)
    known = picked.get("")   # the assignments of SolidWorks faces earlier fillets left open
    # a chamfer whose two sides differ (an angle other than 45, two distances) is tried both ways
    flips = [False, True] if f.kind == "chamfer" and (f.chamfer_mm2 is not None or abs(f.chamfer_deg - 45) > 1e-9) else [False]
    for edges, amaps in fillets.candidates(d, f, feats, cli, tmp, known)[:MAX_FILLET_CHOICES]:
        for flip in flips:
            yield from _with_fillets(name, feats, choices, planes, constraints, cli, tmp,
                                     dict(picked, **{pending: edges, "": amaps, "flip:" + pending: flip}))


def tree_summary(feats: list | None) -> list[dict]:
    """The feature tree for the design's metadata: each feature's name, kind and whether it
    converted."""
    out = []
    for f in feats or []:
        status = "tbd" if f.kind == "tbd" or f.reason or (f.kind == "sketch" and (not f.sketch.planes or f.sketch.problems)) else "read"
        if f.kind == "absorbed":
            status = "kept"   # in the tree, making no solid (an unused sketch, a reference axis …): no blocker
        item = {"name": f.name, "kind": f.kind, "status": status}
        if status in ("tbd", "kept") and f.reason:
            item["why"] = f.reason
        if status == "tbd":
            item["why"] = f.reason or ("; ".join(f.sketch.problems) if f.kind == "sketch" and f.sketch.problems else
                                       "sketch plane not read" if f.kind == "sketch" else "")
            if f.kind == "tbd":
                item["solidworks_class"] = f.cls
        out.append(item)
    return out
