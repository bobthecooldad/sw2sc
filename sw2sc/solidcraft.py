"""Build a SolidCraft design (JSON) from a SolidWorks document.

Mapping (SolidCraft schema read from the open-source SolidCraft repository,
crates/doc):

* the opened assembly             -> the design root (component 0)
* each part/subassembly definition -> a component (shared by all its placements)
* each placed instance             -> an occurrence, in the component it sits in,
                                      transform converted from metres to mm
* suppressed / hidden instances    -> kept, listed in visibility.hidden_occurrences
* custom properties                -> component metadata (well-known keys) and
                                      properties (everything else)
* feature tree, configuration, material, source path
                                   -> component metadata under METADATA_KEY
* a part file                      -> one component placed once at the origin

Each part's solids come from its embedded Parasolid data, written as STEP text into an
Import feature in the part's component (see geometry.py).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import __version__, geometry, model
from .swfile import SwFile

FORMAT = "solidcraft/28"  # components with metadata/properties need format 28+
METADATA_KEY = "io.sw2sc.solidworks"
MAX_TEXT = 4096
MAX_VALUE_BYTES = 60 * 1024
MAX_DEPTH = 64
MAX_OCCURRENCES = 200_000

# SolidWorks custom property name (lower-case) -> SolidCraft well-known key.
WELL_KNOWN = {
    "description": "description",
    "partno": "part_number", "part number": "part_number", "partnumber": "part_number",
    "part_number": "part_number", "number": "part_number",
    "revision": "revision", "rev": "revision",
    "author": "author", "drawnby": "author", "drawn by": "author",
    "company": "organization", "companyname": "organization",
    "project": "project",
}


@dataclass
class Report:
    source: str
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    # component id -> the SolidWorks file it was read from (parts and subassemblies)
    component_files: dict[int, str] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)


class FileIndex:
    """Finds referenced files by name near the opened file (stored paths are absolute
    paths on the author's machine, so only the file name is used)."""

    def __init__(self, root_dir: str, limit: int = 20000):
        self.by_name: dict[str, list[str]] = {}
        n = 0
        for d, _dirs, files in os.walk(root_dir):
            for f in files:
                if f.lower().endswith((".sldprt", ".sldasm")):
                    self.by_name.setdefault(f.lower(), []).append(os.path.join(d, f))
                    n += 1
            if n > limit:
                break

    def find(self, sw_path: str, near: str | None = None) -> str | None:
        """The file with this name; when several folders hold one, the nearest to `near`."""
        found = self.by_name.get(model.basename(sw_path).lower())
        if not found:
            return None
        if len(found) == 1 or not near:
            return found[0]
        near = os.path.abspath(near)

        def closeness(p):
            return len(os.path.commonpath([near, os.path.abspath(os.path.dirname(p))]))
        return max(found, key=closeness)


def _text(v: str) -> str:
    v = "".join(ch for ch in v if ch >= " " or ch == "\t").strip()
    return v.encode("utf-8")[:MAX_TEXT].decode("utf-8", "ignore")


def _split_props(custom: dict[str, str]) -> tuple[dict, dict]:
    meta, free = {}, {}
    for k, v in custom.items():
        v = _text(v.strip('"').strip("“”"))
        if not v:
            continue
        key = WELL_KNOWN.get(k.strip().lower())
        if key and key not in meta:
            meta[key] = v
        else:
            free[_text(k)[:128] or "property"] = v
    return meta, free


def _source_meta(doc: model.SwDocument | None, sw_path: str, config: str, rep: Report) -> dict:
    info: dict = {"source_file": model.basename(sw_path) if sw_path else "", "configuration": config}
    if doc is None:
        return info
    info["solidworks_version"] = doc.sw_version
    info["container"] = doc.container
    if doc.material:
        info["material"] = doc.material
    if doc.configurations:
        info["configurations"] = doc.configurations[:256]
    feats = [{"id": f.id, "name": f.name, "type": f.type,
              **({"consumes": f.consumes} if f.consumes else {}),
              **({"dimensions": f.dimensions} if f.dimensions else {})} for f in doc.features]
    while feats and len(json.dumps(feats)) > MAX_VALUE_BYTES:
        feats = feats[: len(feats) * 3 // 4]
        rep.warn(f"{doc.name}: feature tree truncated to {len(feats)} entries (metadata size limit)")
    if feats:
        info["features"] = feats
    return info


def _matrix(t: list[float]) -> list[list[float]]:
    """SolidWorks stores 4 groups of 4: the images of X, Y, Z and the translation (metres).
    SolidCraft's Mat is the same layout (m[col][row]) in millimetres."""
    if len(t) != 16:
        return [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
    m = [[float(t[4 * c + r]) for r in range(4)] for c in range(4)]
    for c in range(3):
        m[c][3] = 0.0
    m[3] = [t[12] * 1000.0, t[13] * 1000.0, t[14] * 1000.0, 1.0]
    return m


def _is_placement(m) -> bool:
    import math
    ax = [m[i][:3] for i in range(3)]
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    cross = lambda a, b: [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    return (all(math.isfinite(v) for row in m for v in row)
            and all(abs(dot(a, a) - 1) < 1e-6 for a in ax)
            and abs(dot(ax[0], ax[1])) < 1e-6 and abs(dot(ax[0], ax[2])) < 1e-6 and abs(dot(ax[1], ax[2])) < 1e-6
            and dot(cross(ax[0], ax[1]), ax[2]) > 0 and all(abs(v) <= 1e9 for v in m[3][:3]))


def _orthonormalise(m):
    """Re-orthonormalise a nearly-rigid rotation (stored values carry float noise)."""
    import math
    x, y = m[0][:3], m[1][:3]
    n = lambda v: [c / (math.sqrt(sum(k * k for k in v)) or 1) for c in v]
    x = n(x)
    d = sum(a * b for a, b in zip(x, y))
    y = n([b - d * a for a, b in zip(x, y)])
    z = [x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]]
    return [x + [0.0], y + [0.0], z + [0.0], m[3]]


def convert(path: str, search_dir: str | None = None, with_geometry: bool = True,
            link_for=None, index: "FileIndex | None" = None, feature_tree: bool = True) -> tuple[dict, Report]:
    """Convert one SolidWorks file to a SolidCraft design.

    link_for(file_path) may return (path relative to the new design, SHA-256 of that design
    file, its STEP text) for a part or a subassembly: the component then links to that design
    file instead of owning a private copy. A linked subassembly is one component, as
    SolidCraft's Insert Design makes it; its own structure lives in the linked design."""
    rep = Report(source=path)
    top = model.load(path)
    for w in top.warnings:
        rep.warn(f"{top.name}: {w}")
    here = os.path.dirname(os.path.abspath(path))
    index = index or FileIndex(search_dir or here)
    loaded: dict[str, model.SwDocument | None] = {}

    def doc_for(sw_path: str) -> model.SwDocument | None:
        key = model.basename(sw_path).lower()
        if key not in loaded:
            found = index.find(sw_path, here)
            loaded[key] = None
            if found is None:
                rep.warn(f"referenced file not found next to the assembly: {model.basename(sw_path)} "
                         "(structure kept; its properties and feature tree are missing)")
            else:
                try:
                    loaded[key] = model.load(found)
                except Exception as e:  # hostile/corrupt input must not stop the whole run
                    rep.warn(f"{model.basename(sw_path)}: unreadable ({e})")
        return loaded[key]

    next_id = 1

    def nid() -> int:
        nonlocal next_id
        next_id += 1
        return next_id - 1

    design: dict = {
        "format": FORMAT,
        "name": top.name,
        "units": "mm",
        "params": [],
        "features": [],
        "components": [],
        "occurrences": [],
    }
    meta, free = _split_props(top.properties)
    design_meta = dict(meta)
    design_meta[METADATA_KEY] = {"converter": f"sw2sc {__version__}",
                                 **_source_meta(top, top.path, top.configurations[0] if top.configurations else "", rep)}
    if free:
        design_meta[METADATA_KEY]["properties"] = free
    design["metadata"] = design_meta

    hidden_paths: list[list[int]] = []

    if top.tree is None:
        # A part (or an assembly without a tree): one component placed at the origin.
        cid = nid()
        comp = {"id": cid, "name": top.name, "parent": 0}
        if meta:
            comp["metadata"] = dict(meta)
        if free:
            comp["properties"] = free
        comp.setdefault("metadata", {})[METADATA_KEY] = _source_meta(top, top.path, "", rep)
        design["components"].append(comp)
        part_files = {cid: (top.path, top.name)}
        design["occurrences"].append({"id": nid(), "component": cid, "parent": 0, "name": f"{top.name}:1",
                                      "transform": _matrix([]), "grounded": True})
        rep.stats.update(components=1, occurrences=1, features_listed=len(top.features))
    else:
        tree = top.tree
        part_files: dict[int, tuple[str, str]] = {}
        linked_asm: set[str] = set()  # subassembly models made into links (not expanded)
        comp_of: dict[str, int] = {tree.root: 0}
        components: dict[int, dict] = {}
        occ_count = 0

        def component_for(mid: str, parent_comp: int) -> int:
            if mid in comp_of:
                return comp_of[mid]
            md = tree.models[mid]
            cid = nid()
            comp_of[mid] = cid
            short = os.path.splitext(model.basename(md.file_path))[0] or md.name
            comp: dict = {"id": cid, "name": short, "parent": parent_comp}
            d = doc_for(md.file_path) if md.file_path else None
            found = index.find(md.file_path, here) if md.file_path else None
            if found:
                rep.component_files[cid] = found
            if found and d is not None and md.doc_type != "ASSEMBLY" and not found.lower().endswith(".sldasm"):
                part_files[cid] = (found, short)
            elif found and link_for and with_geometry and found.lower().endswith(".sldasm"):
                linked = link_for(found)
                if linked:
                    rel, sha, text = linked
                    fid = nid()
                    design["features"].append({"id": fid, "name": short, "suppressed": False, "component": cid,
                                               "type": "import", "file": rel, "step": text})
                    design.setdefault("links", {})[str(cid)] = {"path": rel, "feature": fid, "file_sha256": sha}
                    linked_asm.add(mid)
                    rep.stats["subassemblies_linked"] = rep.stats.get("subassemblies_linked", 0) + 1
            if d is not None:
                m, f = _split_props(d.properties)
                if m:
                    comp["metadata"] = m
                if f:
                    comp["properties"] = f
            src = _source_meta(d, md.file_path, md.configuration, rep)
            src["document_type"] = md.doc_type
            if md.bbox and len(md.bbox) == 6:
                src["bounding_box_mm"] = [round(v * 1000.0, 6) for v in md.bbox]
            comp.setdefault("metadata", {})[METADATA_KEY] = src
            components[cid] = comp
            return cid

        # Breadth-first so each component's parent is where it is first placed.
        queue = [(tree.root, 0, 0)]
        expanded: set[str] = set()
        while queue:
            mid, comp_id, depth = queue.pop(0)
            if mid in expanded:
                continue
            expanded.add(mid)
            if depth > MAX_DEPTH:
                rep.warn(f"assembly nested deeper than {MAX_DEPTH} levels; stopped there")
                continue
            md = tree.models.get(mid)
            if md is None:
                continue
            for r in md.refs:
                if r.model_ref not in tree.models:
                    rep.warn(f"{md.name}: instance {r.name}<{r.number}> points at a missing definition")
                    continue
                child_comp = component_for(r.model_ref, comp_id)
                m = _matrix(r.transform)
                if not _is_placement(m):
                    m = _orthonormalise(m)
                    if not _is_placement(m):
                        rep.warn(f"{md.name}: instance {r.name}<{r.number}> has a non-rigid transform; placed at origin")
                        m = _matrix([])
                oid = nid()
                occ_count += 1
                if occ_count > MAX_OCCURRENCES:
                    raise ValueError("too many occurrences")
                design["occurrences"].append({
                    "id": oid, "component": child_comp, "parent": comp_id,
                    "name": f"{r.name}:{r.number}", "transform": m, "grounded": True,
                })
                if r.suppressed:
                    rep.warn(f"{md.name}: {r.name}<{r.number}> is suppressed in SolidWorks; kept hidden")
                if r.suppressed or r.hidden:
                    hidden_paths.append(("pending", comp_id, oid))  # resolved below
                if r.virtual:
                    rep.warn(f"{md.name}: {r.name}<{r.number}> is a virtual component (stored inside the assembly)")
                if r.model_ref not in linked_asm:
                    queue.append((r.model_ref, child_comp, depth + 1))
        design["components"] = [components[k] for k in sorted(components)]

        # Hidden placements: SolidCraft wants full occurrence paths from the root, one per
        # placement (a hidden instance inside a subassembly placed twice is hidden twice).
        occ_into: dict[int, list[dict]] = {}
        for o in design["occurrences"]:
            occ_into.setdefault(o["component"], []).append(o)
        memo: dict[int, list[list[int]]] = {0: [[]]}

        def paths_to(c: int, depth: int = 0) -> list[list[int]]:
            if c in memo:
                return memo[c]
            out: list[list[int]] = []
            if depth <= MAX_DEPTH:
                for o in occ_into.get(c, []):
                    for p in paths_to(o["parent"], depth + 1):
                        if len(out) >= 10000:
                            break
                        out.append(p + [o["id"]])
            memo[c] = out
            return out

        out_hidden = []
        for _tag, comp_id, oid in hidden_paths:
            for p in paths_to(comp_id)[:10000]:
                out_hidden.append(p + [oid])
        hidden_paths = out_hidden
        rep.stats.update(components=len(design["components"]), occurrences=len(design["occurrences"]),
                         hidden=len(hidden_paths), definitions_read=sum(1 for v in loaded.values() if v),
                         definitions_missing=sum(1 for v in loaded.values() if v is None))

    if with_geometry:
        g = {"parts_with_geometry": 0, "bodies": 0, "faces": 0, "approx_faces": 0, "faces_left_out": 0}
        for cid, (fpath, pname) in sorted(part_files.items()):
            linked = link_for(fpath) if link_for else None
            if linked:
                rel, sha, text = linked
                fid = nid()
                design["features"].append({"id": fid, "name": pname, "suppressed": False, "component": cid,
                                           "type": "import", "file": rel, "step": text})
                design.setdefault("links", {})[str(cid)] = {"path": rel, "feature": fid, "file_sha256": sha}
                g["parts_linked"] = g.get("parts_linked", 0) + 1
                continue
            try:
                text, gw, st = geometry.part_to_step(SwFile(fpath), pname)
            except Exception as e:  # corrupt geometry must not lose the structure
                text, gw, st = None, [f"geometry unreadable: {type(e).__name__}: {e}"], {}
            for k in ("bodies", "faces", "approx_faces", "faces_left_out"):
                g[k] += st.get(k, 0)
            if st.get("approx_faces"):
                rep.warn(f"{pname}: {st['approx_faces']} of {st['faces']} faces are close fits, not exact "
                         "(blends, offsets, swept or spun surfaces)")
            if st.get("faces_left_out"):
                rep.warn(f"{pname}: {st['faces_left_out']} faces left out; the body will be open")
            for w in gw:
                if not w.startswith("face "):
                    rep.warn(f"{pname}: {w}")
            if text:
                g["parts_with_geometry"] += 1
                design["features"].append({"id": nid(), "name": pname, "suppressed": False, "component": cid,
                                           "type": "import", "file": model.basename(fpath), "step": text})
        rep.stats.update(g)
    else:
        rep.warn("geometry not converted (--no-geometry): components hold structure and properties only")
    if hidden_paths:
        design["visibility"] = {"hidden_occurrences": hidden_paths}
    design["next_id"] = next_id
    if feature_tree and with_geometry and top.tree is None and part_files:
        design = _feature_tree(design, top.path, top.name, rep)
    return design, rep


def _feature_tree(design: dict, path: str, name: str, rep: Report) -> dict:
    """A part's own feature tree (F-006): recorded in the metadata, and used in place of the
    imported solid when every feature is decoded and its rebuild in SolidCraft matches the solid
    SolidWorks saved. Otherwise the part keeps its imported solid."""
    from . import features as tree, verify
    try:
        feats = tree.read(SwFile(path))
    except Exception as e:  # noqa: BLE001 - an unreadable tree must not lose the part
        rep.warn(f"{name}: feature tree not read ({type(e).__name__}: {e})")
        return design
    if feats is None:
        rep.stats["feature_tree"] = "not read (this file's feature stream isn't numbered yet)"
        return design
    design["metadata"][METADATA_KEY]["feature_tree"] = verify.tree_summary(feats)
    tbd = [f.name for f in feats if f.kind == "tbd"]
    if tbd:
        rep.stats["features_tbd"] = len(tbd)
    cli = verify.find_cli()
    if not cli:
        rep.stats["feature_tree"] = "read; not rebuilt (solidcraft-cli not found to check it)"
        return design
    status = verify.kernel_status(cli)   # what checked the rebuild, and whether it is current
    design["metadata"][METADATA_KEY]["rebuild_check"] = verify.kernel_line(status)
    if status["stale"]:
        rep.warn(f"{name}: the rebuild was checked with a stale SolidCraft ({status['why']})")
    built = verify.rebuild(feats, design, name, cli)
    if not built:
        rep.stats["feature_tree"] = "read; kept the imported solid (not every feature converts yet)" \
            if not verify.fully_decoded(feats) else "read; kept the imported solid (rebuild didn't match)"
        return design
    # SolidWorks offsets as SolidCraft's own offsets, where that rebuilds the same solid
    from . import native
    nat = native.offsets(built, feats, cli)
    if nat:
        import json, tempfile
        with tempfile.TemporaryDirectory(prefix="sw2sc-offset-") as tmp:
            a, b_ = os.path.join(tmp, "a.solidcraft"), os.path.join(tmp, "b.solidcraft")
            json.dump(built, open(a, "w", encoding="utf-8"))
            json.dump(nat, open(b_, "w", encoding="utf-8"))
            if verify.same(verify.evaluate(cli, b_), verify.evaluate(cli, a)):
                built = nat
                rep.stats["sketch_offsets"] = "native SolidCraft offsets"
    cid = design["components"][0]["id"] if design.get("components") else None
    base = design["next_id"]
    remap = {f["id"]: base + i for i, f in enumerate(built["features"])}
    feats_out = []
    for f in built["features"]:
        g = dict(f, id=remap[f["id"]])
        if "sketch" in g and isinstance(g["sketch"], int):
            g["sketch"] = remap[g["sketch"]]
        if isinstance(g.get("points"), dict) and isinstance(g["points"].get("sketch"), int):
            g["points"] = dict(g["points"], sketch=remap[g["points"]["sketch"]])   # a hole's sketch
        if g.get("edge_names"):   # a fillet's edges are named after the features that made them
            import re as _re
            g["edge_names"] = [_re.sub(r"F(\d+):", lambda m: f"F{remap.get(int(m.group(1)), int(m.group(1)))}:", n)
                               for n in g["edge_names"]]
        if cid is not None:
            g["component"] = cid
        feats_out.append(g)
    final = dict(design, format=built["format"], features=feats_out, next_id=base + len(feats_out),
                 params=list(design.get("params", [])) + list(built.get("params", [])))
    # the final design, components and all, must still match the imported solid
    import json, tempfile
    with tempfile.TemporaryDirectory(prefix="sw2sc-tree-") as tmp:
        a, b_ = os.path.join(tmp, "a.solidcraft"), os.path.join(tmp, "b.solidcraft")
        json.dump(design, open(a, "w", encoding="utf-8"))
        json.dump(final, open(b_, "w", encoding="utf-8"))
        if not verify.same(verify.evaluate(cli, b_), verify.evaluate(cli, a)):
            rep.stats["feature_tree"] = "read; kept the imported solid (the rebuilt design didn't match)"
            return design
    rep.stats["feature_tree"] = f"rebuilt from its {len(feats_out)} features (matches the solid)"
    return final


def write(design: dict, out_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(design, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, out_path)
