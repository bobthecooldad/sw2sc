"""Command line: convert, inspect, survey."""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import traceback

from . import __version__, model, roles, solidcraft, validate, vault, workflow


def _out_path(src: str, out: str | None) -> str:
    if out and not os.path.isdir(out):
        return out
    name = os.path.splitext(os.path.basename(src))[0] + ".solidcraft"
    return os.path.join(out or os.path.dirname(os.path.abspath(src)), name)


def cmd_convert(a) -> int:
    rc = 0
    for src in a.inputs:
        try:
            design, rep = solidcraft.convert(src, a.search_dir, not a.no_geometry)
            dst = _out_path(src, a.output)
            solidcraft.write(design, dst)
            print(f"{src} -> {dst}  {rep.stats}")
            for problem in validate.validate(design):
                rc = 1
                print(f"  INVALID: {problem}")
            for w in rep.warnings:
                print(f"  warning: {w}")
        except Exception as e:
            rc = 1
            print(f"{src}: FAILED: {e}", file=sys.stderr)
    return rc


def cmd_inspect(a) -> int:
    d = model.load(a.input)
    print(f"{d.name}  type={d.doc_type} container={d.container} sw={d.sw_version}")
    print(f"configurations: {d.configurations}  material: {d.material}")
    if d.properties:
        print("properties:")
        for k, v in d.properties.items():
            print(f"  {k} = {v}")
    if d.features:
        print("features:")
        for f in d.features:
            extra = f" uses {f.consumes}" if f.consumes else ""
            dims = f" {f.dimensions}" if f.dimensions else ""
            print(f"  [{f.id}] {f.name} ({f.type}){extra}{dims}")
    if d.tree:
        t = d.tree

        def walk(mid, indent, depth=0):
            for r in t.models[mid].refs:
                flags = "".join([" [suppressed]" if r.suppressed else "", " [hidden]" if r.hidden else ""])
                print(f"{'  ' * indent}{r.name}<{r.number}>{flags}")
                sub = t.models.get(r.model_ref)
                if sub and sub.refs and depth < 64:
                    walk(sub.id, indent + 1, depth + 1)
        print("assembly tree:")
        walk(t.root, 1)
    for w in d.warnings:
        print(f"warning: {w}")
    return 0


def cmd_survey(a) -> int:
    """Convert every SolidWorks file under the given folders and write a log."""
    files = []
    for root in a.roots:
        for d, _dirs, fs in os.walk(root):
            files += [os.path.join(d, f) for f in fs if f.lower().endswith((".sldprt", ".sldasm"))]
    files.sort()
    os.makedirs(a.out, exist_ok=True)
    rows, ok, warn_total = [], 0, 0
    t0 = time.time()
    for f in files:
        try:
            design, rep = solidcraft.convert(f, None, not a.no_geometry)
            dst = os.path.join(a.out, os.path.relpath(f, os.path.commonpath(a.roots) if len(a.roots) > 1 else a.roots[0]))
            dst = os.path.splitext(dst)[0] + ".solidcraft"
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            solidcraft.write(design, dst)
            d = model.load(f)
            ok += 1
            extra = list(rep.warnings)
            problems = validate.validate(design)
            if problems:
                ok -= 1
                rows.append((f, "INVALID", d.container, d.doc_type, rep.stats, problems[:20] + extra))
                continue
            warn_total += len(extra)
            rows.append((f, "ok", d.container, d.doc_type, rep.stats, extra))
        except Exception as e:
            rows.append((f, "FAILED", "", "", {}, [f"{type(e).__name__}: {e}"] +
                         ([traceback.format_exc(limit=2)] if a.verbose else [])))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Survey run - sw2sc {__version__}", "",
             f"- Date: {stamp}", f"- Files: {len(files)}", f"- Converted: {ok}",
             f"- Failed: {len(files) - ok}", f"- Warnings: {warn_total}",
             f"- Time: {time.time() - t0:.1f}s", "",
             "| File | Result | Container | Type | Components | Occurrences | Hidden | Bodies | Faces | Fitted | Left out | Warnings |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f, res, cont, typ, st, w in rows:
        name = os.path.relpath(f).replace("|", "/")
        lines.append(f"| {name} | {res} | {cont} | {typ} | {st.get('components', '')} | "
                     f"{st.get('occurrences', '')} | {st.get('hidden', '')} | {st.get('bodies', '')} | {st.get('faces', '')} | "
                     f"{st.get('approx_faces', '')} | {st.get('faces_left_out', '')} | {len(w)} |")
    lines += ["", "## Warnings and failures", ""]
    for f, res, _c, _t, _s, w in rows:
        if w:
            lines.append(f"### {os.path.relpath(f)}")
            lines += [f"- {x}" for x in w[:50]]
            lines.append("")
    with open(a.log, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"{ok}/{len(files)} converted, {warn_total} warnings; log: {a.log}")
    return 0 if ok == len(files) else 1


def cmd_vault(a) -> int:
    if a.action == "import":
        why = [] if a.yes else vault.check_source(a.source, a.vault)
        if why:
            print("Not imported. Check this first (or pass --yes):", *("  - " + w for w in why), sep="\n")
            return 2
        r = vault.import_tree(a.source, a.vault, not a.no_originals, not a.no_git,
                              link_subassemblies=not a.embed_subassemblies, copy_other=not a.designs_only)
        print(f"{r.converted} converted, {r.unchanged} unchanged, {r.copied} other files copied, "
              f"{r.removed} removed, {len(r.failed)} failed, {r.warnings} warnings"
              + (f"; commit {r.commit}" if r.commit else ""))
        for f, why in r.failed:
            print(f"  FAILED {f}: {why}")
        return 1 if r.failed else 0
    if a.action == "roles":
        try:
            if a.op != "show":
                r = roles.edit(a.vault, roles.identity(), a.op, a.who, a.op == "four-eyes" and a.who.lower() in ("on", "yes", "true", "1"))
                print("saved")
            info = roles.describe(a.vault, roles.identity())
        except roles.RolesError as e:
            print(f"refused: {e}")
            return 1
        print(f"you are {info['user']}" + ("" if info["open"] else
              f" ({', '.join(x for x, y in (('admin', info['admin']), ('approver', info['approver'])) if y) or 'no role'})"))
        if info["open"]:
            print("this vault has no roles: anyone can release. `vault roles <vault> add-approver <account>` sets them up,"
                  " and makes you the first admin.")
        else:
            r = info["roles"]
            print("admins:    " + (", ".join(r["admins"]) or "-"))
            print("approvers: " + (", ".join(r["approvers"]) or "-"))
            print("four-eyes: " + ("on (approvers can't release what they submitted)" if r["four_eyes"] else "off"))
        return 0
    if a.action == "status":
        wf = workflow.status(a.vault)
        rows = sorted(wf.items())
        if a.name:
            rows = [(k, v) for k, v in rows if k in {f for f, _ in vault.find_items(a.vault, a.name)}]
        for k, w in rows:
            print(f"{workflow.LABELS.get(w.get('state'), w.get('state')):10} rev {w.get('revision', ''):4} {k}")
            if a.name:
                for h in w.get("history", []):
                    print(f"    {h['date']}  {h['by']}: {h['action']} -> {workflow.LABELS.get(h['to'], h['to'])}"
                          f" (rev {h.get('revision', '')})" + (f"  {h['comment']}" if h.get("comment") else ""))
                for r in w.get("releases", []):
                    print(f"    released rev {r['revision']} {r['date']} by {r['by']}" + (f"  tag {r['tag']}" if r.get("tag") else ""))
        if not rows:
            print("nothing matches")
        return 0
    found = vault.find_items(a.vault, a.name)
    if not found:
        print(f"nothing in the vault matches {a.name!r}")
        return 1
    if a.action in ("submit-all", "release-all"):
        if len(found) > 1 and found[0][0].lower() != a.name.lower():
            print(f"{a.name!r} matches {len(found)} items; give the item's path, for example {found[0][0]}")
            return 1
        action = a.action.split("-")[0]
        try:
            plan = workflow.plan_tree(a.vault, found[0][0], action)
            print(f"as {roles.identity()}")
        except workflow.WorkflowError as e:
            print(f"refused: {e}")
            return 1
        print(f"{found[0][0]}: {len(plan['steps'])} to {action}, {len(plan['skip'])} unchanged")
        for st in plan["steps"]:
            print(f"  {st['do']:15} rev {st['revision']:4} {st['item']}")
        for b in plan["blockers"]:
            print(f"  BLOCKED: {b}")
        if a.dry_run:
            return 1 if plan["blockers"] else 0
        try:
            workflow.change_tree(a.vault, found[0][0], action, "", a.message)
        except workflow.WorkflowError as e:
            print(f"refused: {e}")
            return 1
        print("done" + (" (one commit, a tag for each release)" if action == "release" else ""))
        return 0
    if a.action in workflow.ACTIONS or a.action == "get":
        if len(found) > 1 and found[0][0].lower() != a.name.lower():
            print(f"{a.name!r} matches {len(found)} items; give the item's path, for example {found[0][0]}")
            return 1
        try:
            if a.action == "get":
                files = workflow.get_release(a.vault, found[0][0], a.revision, a.to)
                print(f"{found[0][0]} rev {a.revision}: {len(files)} files written to {a.to}")
                return 0
            w = workflow.change(a.vault, found[0][0], a.action, "", a.message)
        except workflow.WorkflowError as e:
            print(f"refused: {e}")
            return 1
        print(f"{found[0][0]}: {workflow.LABELS[w['state']]}, rev {w['revision']}")
        return 0
    print(found[0][0])
    if a.action == "where-used":
        rows = vault.where_used(a.vault, a.name)
        for level, item, qty in rows:
            print(f"{'  ' * level}{item}  x{qty}")
        if not rows:
            print("  not used in any assembly")
    else:
        for level, item, qty, it in vault.bom(a.vault, a.name):
            extra = " ".join(x for x in (it.get("part_number", ""), it.get("revision", ""), it.get("description", "")) if x)
            print(f"{'  ' * level}{qty} x {item}  {extra}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sw2sc", description="Clean-room SolidWorks to SolidCraft converter")
    p.add_argument("--version", action="version", version=f"sw2sc {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert .sldprt/.sldasm files to .solidcraft designs")
    c.add_argument("inputs", nargs="+")
    c.add_argument("-o", "--output", help="output file or folder (default: next to the input)")
    c.add_argument("--search-dir", help="folder to look in for referenced parts (default: the input's folder)")
    c.add_argument("--no-geometry", action="store_true", help="structure and properties only")
    c.set_defaults(fn=cmd_convert)
    i = sub.add_parser("inspect", help="print what the converter reads from a file")
    i.add_argument("input")
    i.set_defaults(fn=cmd_inspect)
    s = sub.add_parser("survey", help="convert every file under folders and write a log")
    s.add_argument("roots", nargs="+")
    s.add_argument("--out", default="out")
    s.add_argument("--log", default=os.path.join("logs", f"survey-{__version__}.md"))
    s.add_argument("-v", "--verbose", action="store_true")
    s.add_argument("--no-geometry", action="store_true")
    s.set_defaults(fn=cmd_survey)
    g = sub.add_parser("gui", help="open the vault window in the browser")
    g.add_argument("--port", type=int, default=0)
    g.add_argument("--no-browser", action="store_true", help="print the address instead of opening it")
    g.set_defaults(fn=lambda a: (__import__("sw2sc.gui", fromlist=["serve"]).serve(a.port, not a.no_browser), 0)[1])
    v = sub.add_parser("vault", help="import a folder tree into a Git vault of linked SolidCraft designs")
    vs = v.add_subparsers(dest="action", required=True)
    vi = vs.add_parser("import", help="convert a folder tree; run again to pick up changes")
    vi.add_argument("source")
    vi.add_argument("vault")
    vi.add_argument("--no-originals", action="store_true", help="do not copy the SolidWorks files into the vault")
    vi.add_argument("--no-git", action="store_true", help="do not record the import as a Git commit")
    vi.add_argument("--designs-only", action="store_true", help="copy only SolidWorks files, not the folder's other files")
    vi.add_argument("--yes", action="store_true", help="import even when the folder doesn't look like a SolidWorks project")
    vi.add_argument("--embed-subassemblies", action="store_true",
                    help="keep subassemblies inside each assembly instead of linking their designs")
    for name, text in (("where-used", "assemblies that use an item"), ("bom", "what an assembly contains")):
        q = vs.add_parser(name, help=text)
        q.add_argument("vault")
        q.add_argument("name", help="item path, name or part number")
    st = vs.add_parser("status", help="state and revision of every item, or one item's history")
    st.add_argument("vault")
    st.add_argument("name", nargs="?", default="")
    for name, text in (("submit", "In Work -> In Review"), ("reject", "In Review -> In Work (needs -m)"),
                       ("release", "In Review -> Released (everything it contains must be Released)"),
                       ("revise", "Released -> next revision In Work")):
        q = vs.add_parser(name, help=text)
        q.add_argument("vault")
        q.add_argument("name", help="item path, name or part number")
        q.add_argument("-m", "--message", default="", help="comment recorded with the change")
    for name, text in (("submit-all", "submit an assembly and everything in it that is In Work"),
                       ("release-all", "release an assembly and everything in it, parts first, all or nothing")):
        q = vs.add_parser(name, help=text)
        q.add_argument("vault")
        q.add_argument("name", help="item path, name or part number")
        q.add_argument("-m", "--message", default="", help="comment recorded with every item")
        q.add_argument("--dry-run", action="store_true", help="show what would change, change nothing")
    ro = vs.add_parser("roles", help="show or change who may release (admins only change them)")
    ro.add_argument("vault")
    ro.add_argument("op", nargs="?", default="show",
                    choices=["show", "add-admin", "remove-admin", "add-approver", "remove-approver", "four-eyes"])
    ro.add_argument("who", nargs="?", default="", help="account (PC-OR-DOMAIN\\user), or on/off for four-eyes")
    g2 = vs.add_parser("get", help="write a released revision and everything it contained to a folder")
    g2.add_argument("vault")
    g2.add_argument("name")
    g2.add_argument("revision")
    g2.add_argument("to")
    v.set_defaults(fn=cmd_vault)
    a = p.parse_args(argv)
    return a.fn(a)
