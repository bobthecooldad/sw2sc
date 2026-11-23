"""Import a folder tree of CAD files into a vault of SolidCraft designs.

The vault is an ordinary folder kept in Git, in the style SolidCraft is moving towards
(designs as text, history in Git; no server and no locks):

* the source tree's folders are mirrored;
* every SolidWorks part becomes its own design, `<name>.solidcraft`;
* every assembly becomes a design whose part components are *linked* to those part designs
  (SolidCraft's Insert Design link: relative path + SHA-256 of the linked file), so a part
  used by ten assemblies is stored once;
* every other file (drawings, PDFs, STEP, pictures ...) is copied unchanged;
* `vault.json` is the index: properties, revision, what each assembly uses, where each item
  is used, and what the conversion could not carry over. `VAULT.md` is the same for reading.

Running the import again converts only what changed and makes a new Git commit, so the
vault's Git history is the revision history of the imported data.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from . import __version__, model, solidcraft, stepasm, validate, workflow

INDEX = "vault.json"
REPORT = "VAULT.md"
SW_EXT = (".sldprt", ".sldasm")
SKIP_DIRS = {".git"}
SKIP_PREFIX = ("~$", ".~")  # SolidWorks and SolidCraft lock files


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _posix(p: str) -> str:
    return p.replace("\\", "/")


def _design_rel(src_rel: str) -> str:
    """Vault path of the design made from a SolidWorks file. The source extension stays in
    the name so `Bracket.SLDPRT` and `Bracket.SLDASM` cannot collide."""
    base, ext = os.path.splitext(src_rel)
    return _posix(f"{base}.{ext[1:].lower()}.solidcraft")


@dataclass
class ImportResult:
    converted: int = 0
    unchanged: int = 0
    copied: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    removed: int = 0
    commit: str | None = None
    warnings: int = 0


def _scan(source: str) -> tuple[list[str], list[str]]:
    sw, other = [], []
    for d, dirs, files in os.walk(source):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS)
        for f in sorted(files):
            if f.startswith(SKIP_PREFIX):
                continue
            rel = os.path.relpath(os.path.join(d, f), source)
            (sw if f.lower().endswith(SW_EXT) else other).append(rel)
    return sw, other


CHECK_FILES = 20000           # stop counting a source folder after this many files
MANY_OTHER, BIG_BYTES = 200, 2 << 30


def check_source(source: str, vault: str) -> list[str]:
    """What looks wrong with importing `source` into `vault`, in words for a person: a
    personal or whole-drive folder, a folder that is mostly not SolidWorks files, a very
    large one, or a different project than the vault holds (its designs would be removed).
    Empty when it looks like a SolidWorks project."""
    source, vault = os.path.abspath(source), os.path.abspath(vault)
    why = []
    home = os.path.expanduser("~")
    personal = {os.path.normcase(os.path.abspath(p)) for p in
                [home] + [os.path.join(home, d) for d in ("Documents", "Desktop", "Downloads", "OneDrive", "Pictures",
                                                         "Videos", "Music")]}
    if os.path.normcase(source) in personal or os.path.dirname(source) == source:
        why.append(f"{source} is a personal or whole-drive folder, not a SolidWorks project: everything in it "
                   "would be copied into the vault.")
    sw = other = size = 0
    stopped = False
    for d, dirs, files in os.walk(source):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.startswith(SKIP_PREFIX):
                continue
            if f.lower().endswith(SW_EXT):
                sw += 1
            else:
                other += 1
            try:
                size += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
        if sw + other >= CHECK_FILES:
            stopped = True
            break
    more = "+" if stopped else ""
    if not sw:
        why.append("There are no SolidWorks files in it.")
    elif other >= MANY_OTHER and other > 4 * sw:
        why.append(f"Only {sw} of its {sw + other}{more} files are SolidWorks files; the other {other}{more} "
                   "would be copied into the vault as they are.")
    if size >= BIG_BYTES or stopped:
        why.append(f"It holds {size / (1 << 30):.1f} GB{more} in {sw + other}{more} files.")
    old = _load_index(vault)
    if old.get("items") and old.get("source") and old["source"] != os.path.basename(source):
        why.append(f"This vault holds {len(old['items'])} designs imported from \"{old['source']}\". Importing "
                   f"\"{os.path.basename(source)}\" replaces them: designs not in it are removed from the vault.")
    return why


def _load_index(vault: str) -> dict:
    try:
        with open(os.path.join(vault, INDEX), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and isinstance(data.get("items"), dict) else {"items": {}}
    except (OSError, ValueError):
        return {"items": {}}


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _design_text(design: dict) -> str:
    # one value per line and sorted keys: small, readable differences between revisions
    return json.dumps(design, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def _bottom_up(source: str, assemblies: list[str], index, log) -> list[str]:
    """Assemblies ordered so every subassembly comes before the assemblies that use it."""
    uses: dict[str, set[str]] = {}
    for rel in assemblies:
        uses[rel] = set()
        try:
            doc = model.load(os.path.join(source, rel))
        except Exception:
            continue
        if not doc.tree:
            continue
        here = os.path.dirname(os.path.join(source, rel))
        for md in doc.tree.models.values():
            if md.id != doc.tree.root and md.doc_type == "ASSEMBLY" and md.file_path:
                f = index.find(md.file_path, here)
                if f and os.path.commonpath([source, os.path.abspath(f)]) == source:
                    uses[rel].add(os.path.relpath(os.path.abspath(f), source))
    order, state = [], {}

    def visit(rel, depth=0):
        if state.get(rel) == 2:
            return
        if state.get(rel) == 1 or depth > 64:
            log(f"  assemblies use each other in a loop at {rel}; that link is left embedded")
            return
        state[rel] = 1
        for child in sorted(uses.get(rel, ())):
            if child in uses and child != rel:
                visit(child, depth + 1)
        state[rel] = 2
        order.append(rel)
    for rel in assemblies:
        visit(rel)
    return order


def import_tree(source: str, vault: str, keep_originals: bool = True, use_git: bool = True,
                log=print, link_subassemblies: bool = True, copy_other: bool = True) -> ImportResult:
    source, vault = os.path.abspath(source), os.path.abspath(vault)
    if not os.path.isdir(source):
        raise ValueError(f"not a folder: {source}")
    if source == vault or os.path.commonpath([source, vault]) == source:
        raise ValueError("the vault must be outside the folder being imported")
    os.makedirs(vault, exist_ok=True)
    res = ImportResult()
    old = _load_index(vault)["items"]
    items: dict[str, dict] = {}
    sw_files, other_files = _scan(source)
    if not copy_other:
        other_files = []
    index = solidcraft.FileIndex(source)
    parts = [r for r in sw_files if r.lower().endswith(".sldprt")]
    assemblies = [r for r in sw_files if r.lower().endswith(".sldasm")]
    step_cache: dict[str, tuple[str, str]] = {}  # design rel -> (sha, step text)

    def part_link(design_rel: str):
        if design_rel not in step_cache:
            path = os.path.join(vault, design_rel)
            try:
                with open(path, encoding="utf-8") as fh:
                    d = json.load(fh)
                step = next((f["step"] for f in d.get("features", []) if f.get("type") == "import"), None)
                step_cache[design_rel] = (sha256_file(path), step) if step else (None, None)
            except (OSError, ValueError):
                step_cache[design_rel] = (None, None)
        return step_cache[design_rel]

    def record(rel, kind, src_sha, design, rep, deps):
        meta = design.get("metadata", {})
        sw = meta.get(solidcraft.METADATA_KEY, {})
        comp_meta = (design.get("components") or [{}])[0].get("metadata", {}) if kind == "part" else meta
        uses: dict[str, int] = {}
        for o in design.get("occurrences", []):
            if o.get("parent", 0) == 0 and kind == "assembly":
                f = rep.component_files.get(o["component"])
                if f and os.path.commonpath([source, os.path.abspath(f)]) == source:
                    child = _design_rel(os.path.relpath(f, source))
                    uses[child] = uses.get(child, 0) + 1
        hidden = {p[0] for p in (design.get("visibility") or {}).get("hidden_occurrences", []) if len(p) == 1}
        del hidden  # hidden and suppressed instances still count as used
        return {
            "type": kind,
            "name": design.get("name", ""),
            "source": _posix(rel),
            "source_sha256": src_sha,
            "converter": __version__,
            "part_number": comp_meta.get("part_number", ""),
            "description": comp_meta.get("description", ""),
            "revision": comp_meta.get("revision", ""),
            "material": sw.get("material", ""),
            "configurations": sw.get("configurations", []),
            "solidworks_version": sw.get("solidworks_version"),
            "uses": [{"item": k, "quantity": v} for k, v in sorted(uses.items())],
            "depends": deps,
            "stats": dict(rep.stats),
            "warnings": list(rep.warnings)[:100],
        }

    def up_to_date(rel, src_sha, deps=None):
        prev = old.get(_design_rel(rel))
        return (prev is not None and prev.get("source_sha256") == src_sha and prev.get("converter") == __version__
                and (deps is None or prev.get("depends") == deps)
                and os.path.isfile(os.path.join(vault, _design_rel(rel))))

    def convert_one(rel, kind, link_for=None, deps=None):
        src = os.path.join(source, rel)
        drel = _design_rel(rel)
        src_sha = sha256_file(src)
        if keep_originals:
            dst = os.path.join(vault, rel)
            if not os.path.isfile(dst) or sha256_file(dst) != src_sha:
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                shutil.copy2(src, dst)
        if up_to_date(rel, src_sha, deps):
            items[drel] = old[drel]
            res.unchanged += 1
            return
        try:
            design, rep = solidcraft.convert(src, None, True, link_for, index)
            problems = validate.validate(design)
            if problems:
                raise ValueError("; ".join(problems[:3]))
            _write_text(os.path.join(vault, drel), _design_text(design))
            step_cache.pop(drel, None)
            items[drel] = record(rel, kind, src_sha, design, rep, deps or {})
            res.converted += 1
            res.warnings += len(rep.warnings)
            log(f"  converted {rel}")
        except Exception as e:  # one bad file must not stop the import
            res.failed.append((rel, f"{type(e).__name__}: {e}"))
            items[drel] = {"type": kind, "name": os.path.splitext(os.path.basename(rel))[0], "source": _posix(rel),
                           "source_sha256": src_sha, "converter": __version__, "failed": f"{type(e).__name__}: {e}",
                           "uses": [], "depends": {}, "stats": {}, "warnings": []}
            log(f"  FAILED    {rel}: {e}")

    log(f"Parts: {len(parts)}")
    for rel in parts:
        convert_one(rel, "part")

    assemblies = _bottom_up(source, assemblies, index, log) if link_subassemblies else assemblies
    asm_steps: dict[str, tuple[str, str] | None] = {}  # design rel -> (sha, assembled STEP)

    def design_leaves(drel: str, depth: int = 0):
        """Part placements of a vault design, by its file (for nested subassembly links)."""
        try:
            with open(os.path.join(vault, drel), encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return None
        base = os.path.dirname(drel)

        def inner(link):
            child = _posix(os.path.normpath(os.path.join(base, link["path"])))
            if not child.endswith(".sldasm.solidcraft") or depth > 32:
                return None
            return design_leaves(child, depth + 1) or None
        return stepasm.leaf_placements(d, inner)

    def asm_link(drel: str):
        if drel not in asm_steps:
            path = os.path.join(vault, drel)
            asm_steps[drel] = None
            if os.path.isfile(path) and "failed" not in items.get(drel, {"failed": 1}):
                try:
                    leaves = design_leaves(drel)
                    if leaves:
                        name = os.path.basename(drel).split(".")[0]
                        asm_steps[drel] = (sha256_file(path), stepasm.StepAssembly(name).write(leaves))
                except (ValueError, KeyError, IndexError, TypeError) as e:
                    log(f"  subassembly {drel} kept unlinked: {e}")
        return asm_steps[drel]

    log(f"Assemblies: {len(assemblies)}")
    for rel in assemblies:
        adir = os.path.dirname(_design_rel(rel))
        deps: dict[str, str] = {}

        def link_for(part_path, adir=adir, deps=deps):
            part_path = os.path.abspath(part_path)
            if os.path.commonpath([source, part_path]) != source:
                return None
            drel = _design_rel(os.path.relpath(part_path, source))
            if part_path.lower().endswith(".sldasm"):
                got = asm_link(drel)
                if not got:
                    return None
                sha, step = got
            else:
                sha, step = part_link(drel)
            if not sha:
                return None
            deps[drel] = sha
            return _posix(os.path.relpath(os.path.join(vault, drel), os.path.join(vault, adir))), sha, step
        # which part designs this assembly would link to, to decide whether it is up to date
        probe: dict[str, str] = {}
        prev = old.get(_design_rel(rel))
        if prev:
            for drel in prev.get("depends", {}):
                p = os.path.join(vault, drel)
                if os.path.isfile(p):
                    probe[drel] = sha256_file(p)
        convert_one(rel, "assembly", link_for, probe if prev else None)
        if _design_rel(rel) in items and "failed" not in items[_design_rel(rel)] and deps:
            items[_design_rel(rel)]["depends"] = dict(sorted(deps.items()))

    for rel in other_files:
        src, dst = os.path.join(source, rel), os.path.join(vault, rel)
        # the vault's own files (folders, roles, releases) are never overwritten by a source file
        if os.path.normcase(os.path.abspath(dst)) in {os.path.normcase(os.path.abspath(os.path.join(vault, f)))
                                                      for f in (INDEX, REPORT, "folders.json", "roles.json", "workflow.json")}:
            continue
        if not os.path.isfile(dst) or os.path.getsize(dst) != os.path.getsize(src) or sha256_file(dst) != sha256_file(src):
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copy2(src, dst)
            res.copied += 1

    # designs whose source has gone
    for drel in old:
        if drel not in items:
            for p in (os.path.join(vault, drel), os.path.join(vault, old[drel].get("source", "\0"))):
                if os.path.isfile(p):
                    os.remove(p)
            res.removed += 1

    where: dict[str, list[dict]] = {}
    for drel, it in items.items():
        for u in it.get("uses", []):
            where.setdefault(u["item"], []).append({"item": drel, "quantity": u["quantity"]})
    for drel, it in items.items():
        it["where_used"] = sorted(where.get(drel, []), key=lambda x: x["item"])

    index_doc = {"format": "sw2sc-vault/1", "source": os.path.basename(source),
                 "other_files": [_posix(r) for r in other_files],
                 "items": dict(sorted(items.items()))}
    _write_text(os.path.join(vault, INDEX), json.dumps(index_doc, indent=1, ensure_ascii=False) + "\n")
    for note in workflow.sync(vault, index_doc["items"]):
        log(f"  workflow: {note}")
    _write_text(os.path.join(vault, REPORT), _report(index_doc, workflow.status(vault)))
    if use_git:
        res.commit = _git_commit(vault, source, res, log)
    return res


def _report(doc: dict, wf: dict | None = None) -> str:
    items = doc["items"]
    wf = wf or {}
    out = [f"# Vault: {doc['source']}", "",
           f"{sum(1 for i in items.values() if i['type'] == 'part')} parts, "
           f"{sum(1 for i in items.values() if i['type'] == 'assembly')} assemblies, "
           f"{len(doc.get('other_files', []))} other files. Details are in `{INDEX}`.", "",
           "| Item | Type | State | Rev | Part number | Description | Uses | Used in | Notes |",
           "|---|---|---|---|---|---|---|---|---|"]
    for drel, it in items.items():
        note = "FAILED: " + it["failed"][:60] if it.get("failed") else (f"{len(it.get('warnings', []))} warnings" if it.get("warnings") else "")
        cell = lambda s: str(s).replace("|", "/")
        w = wf.get(drel, {})
        out.append(f"| {cell(drel)} | {it['type']} | {workflow.LABELS.get(w.get('state'), '')} | {cell(w.get('revision', ''))} | "
                   f"{cell(it.get('part_number', ''))} | "
                   f"{cell(it.get('description', ''))[:60]} | {len(it.get('uses', []))} | {len(it.get('where_used', []))} | {cell(note)} |")
    return "\n".join(out) + "\n"


def _git(vault: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", vault, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def _git_commit(vault: str, source: str, res: ImportResult, log) -> str | None:
    if shutil.which("git") is None:
        log("git not found: the vault was written without history")
        return None
    if not os.path.isdir(os.path.join(vault, ".git")):
        if _git(vault, "init", "-q").returncode != 0:
            return None
        _write_text(os.path.join(vault, ".gitattributes"),
                    "*.solidcraft text eol=lf\n*.json text eol=lf\n*.md text eol=lf\n"
                    "*.SLDPRT binary\n*.SLDASM binary\n*.sldprt binary\n*.sldasm binary\n")
    _git(vault, "add", "-A")
    if _git(vault, "diff", "--cached", "--quiet").returncode == 0:
        log("No changes since the last import.")
        return None
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = (f"Import {os.path.basename(source)} ({stamp})\n\n"
           f"{res.converted} converted, {res.unchanged} unchanged, {res.copied} other files copied, "
           f"{res.removed} removed, {len(res.failed)} failed. sw2sc {__version__}.")
    c = _git(vault, "commit", "-q", "-m", msg)
    if c.returncode != 0:
        log("git commit failed: " + (c.stderr or c.stdout).strip()[:300])
        return None
    return _git(vault, "rev-parse", "--short", "HEAD").stdout.strip()


# --- queries ------------------------------------------------------------------------------
def find_items(vault: str, name: str) -> list[tuple[str, dict]]:
    items = _load_index(vault)["items"]
    n = name.lower()
    exact = [(k, v) for k, v in items.items() if n in (k.lower(), v.get("name", "").lower(), v.get("part_number", "").lower())]
    return exact or [(k, v) for k, v in items.items() if n in k.lower()]


def where_used(vault: str, name: str, all_levels: bool = True) -> list[tuple[int, str, int]]:
    """(level, item, quantity) for every assembly that uses the item, upwards."""
    items = _load_index(vault)["items"]
    out, seen = [], set()

    def walk(drel, level):
        for w in items.get(drel, {}).get("where_used", []):
            out.append((level, w["item"], w["quantity"]))
            if all_levels and w["item"] not in seen and level < 64:
                seen.add(w["item"])
                walk(w["item"], level + 1)
    for drel, _ in find_items(vault, name)[:1]:
        walk(drel, 1)
    return out


def bom(vault: str, name: str, all_levels: bool = True) -> list[tuple[int, str, int, dict]]:
    """(level, item, quantity, index entry) for what an assembly contains."""
    items = _load_index(vault)["items"]
    out = []

    def walk(drel, level, mult):
        for u in items.get(drel, {}).get("uses", []):
            out.append((level, u["item"], u["quantity"] * mult, items.get(u["item"], {})))
            if all_levels and level < 64:
                walk(u["item"], level + 1, u["quantity"] * mult)
    for drel, _ in find_items(vault, name)[:1]:
        walk(drel, 1, 1)
    return out
