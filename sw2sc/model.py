"""A SolidWorks document's structure, read from the file's own XML streams.

* ``swXmlContents/COMPINSTANCETREE`` - an assembly's whole component tree:
  referenced files, every (sub)assembly definition and each placed instance
  with its 4x4 transform (metres) and suppressed/hidden flags. The top-level
  file holds the full nested tree, so subassembly files are not required.
* ``swXmlContents/KeyWords`` - the feature tree: features, sketches, the
  sketch each feature consumes, dimension values and material.
* custom properties - see props.py.
"""
from __future__ import annotations

import ntpath
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from . import props
from .swfile import SwFile

MAX_FEATURES = 5000
# KeyWords entries that are always present and are not modelling features.
_SYSTEM_TYPES = {
    "Annotations", "Surface Bodies", "Solid Bodies", "SOLIDWORKS Materials", "Ambient",
    "Directional", "Notes", "Markups", "Equations", "Exploded Views", "Sensors", "Favorites",
    "History", "Selection Sets", "Lights, Cameras and Scene", "Design Binder", "Comments",
    "ConfigurationManager", "Mates", "Point Light", "Spot Light", "Camera", "Origin",
    "Live Section Planes", "MateGroup",
}
_STANDARD_PLANES = {"front plane", "top plane", "right plane"}


def _tag(e: ET.Element) -> str:
    return e.tag.split("}")[-1]


@dataclass
class Reference:
    """One placed instance inside an assembly definition."""
    id: str
    name: str
    number: int
    model_ref: str
    configuration: str
    suppressed: bool
    hidden: bool
    exclude_from_bom: bool
    virtual: bool
    transform: list[float]  # 16 numbers as stored (metres)


@dataclass
class ModelDef:
    id: str
    name: str
    configuration: str
    file_path: str
    doc_type: str  # PART / ASSEMBLY
    bbox: list[float] | None
    refs: list[Reference] = field(default_factory=list)


@dataclass
class Tree:
    models: dict[str, ModelDef]
    root: str


@dataclass
class Feature:
    id: int
    name: str
    type: str
    kind: str  # Extrusion / Feature / Sketch / ...
    consumes: list[int] = field(default_factory=list)
    dimensions: dict[str, str] = field(default_factory=dict)


@dataclass
class SwDocument:
    path: str
    container: str
    doc_type: str
    name: str
    sw_version: str | None
    configurations: list[str]
    material: str | None
    properties: dict[str, str]
    features: list[Feature]
    tree: Tree | None
    warnings: list[str]


def _floats(s: str | None) -> list[float] | None:
    if not s:
        return None
    try:
        return [float(x) for x in s.split()]
    except ValueError:
        return None


def parse_tree(xml_text: str) -> Tree:
    root = ET.fromstring(xml_text.encode("utf-8"))
    files = {e.get("id"): e for e in root.iter() if _tag(e) == "swFile"}
    models: dict[str, ModelDef] = {}
    for m in root.iter():
        if _tag(m) != "swModel":
            continue
        f = files.get(m.get("swFileRef"))
        md = ModelDef(
            id=m.get("id", ""),
            name=m.get("swName", ""),
            configuration=m.get("swConfigurationName", ""),
            file_path=f.get("swPath", "") if f is not None else "",
            doc_type=f.get("swDocType", "") if f is not None else "",
            bbox=_floats(m.get("swBoundingBox")),
        )
        for r in m:
            if _tag(r) != "swReference":
                continue
            t = _floats(r.get("swTransform")) or []
            md.refs.append(Reference(
                id=r.get("id", ""),
                name=r.get("swName", ""),
                number=int(r.get("swReferenceNumber", "0") or 0),
                model_ref=r.get("swModelRef", ""),
                configuration=r.get("swConfigurationName", ""),
                suppressed=r.get("swSuppressed") == "YES",
                hidden=r.get("swHidden") == "YES",
                exclude_from_bom=r.get("swExcludeFromBOM") == "YES",
                virtual=r.get("swIsVirtualComponent") == "YES",
                transform=t if len(t) == 16 else [],
            ))
        models[md.id] = md
    # Root: the configuration's model, else the one nobody references.
    root_id = None
    for c in root.iter():
        if _tag(c) == "swConfiguration" and c.get("swModelRef") in models:
            root_id = c.get("swModelRef")
            if c.get("swMostRecentConfiguration") == "YES":
                break
    if root_id is None:
        used = {r.model_ref for m in models.values() for r in m.refs}
        roots = [k for k in models if k not in used]
        root_id = roots[0] if roots else next(iter(models), "")
    return Tree(models=models, root=root_id)


def parse_keywords(xml_text: str | None) -> tuple[list[Feature], list[str], str | None]:
    """Features (in creation order), configuration names and material."""
    if not xml_text:
        return [], [], None
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return [], [], None
    feats: list[Feature] = []
    configs: list[str] = []
    material = None
    for e in root:
        kind = _tag(e)
        if kind == "Configuration":
            configs.append(e.get("Name", ""))
            mat = e.get("Material")
            if mat and "not specified" not in mat and material is None:
                material = mat
            continue
        ftype = e.get("Type") or kind
        if ftype in _SYSTEM_TYPES or e.get("Name", "").endswith("___EndTag___"):
            continue
        if ftype.lower() == "plane" and e.get("Name", "").lower() in _STANDARD_PLANES:
            continue
        # In an assembly, each placed component is listed with a type of "<name>-".
        if ftype.endswith("-") and e.get("Name", "").startswith(ftype):
            continue
        try:
            fid = int(e.get("id", "0"))
        except ValueError:
            fid = 0
        consumes = []
        for c in (e.get("DissectableChildren") or "").split():
            if c.isdigit():
                consumes.append(int(c))
        dims = {d.get("Name", ""): (d.text or "") for d in e if _tag(d) == "Dimension"}
        feats.append(Feature(fid, e.get("Name", ""), ftype, kind, consumes, dims))
        if len(feats) >= MAX_FEATURES:
            break
    feats.sort(key=lambda f: f.id)
    return feats, configs, material


def load(path: str) -> SwDocument:
    sw = SwFile(path)
    warnings = list(sw.warnings)
    ext = os.path.splitext(path)[1].lower()
    doc_type = {".sldprt": "PART", ".sldasm": "ASSEMBLY"}.get(ext, "UNKNOWN")
    tree = None
    sw_version = None
    tree_xml = sw.xml("swXmlContents/COMPINSTANCETREE")
    if tree_xml:
        try:
            tree = parse_tree(tree_xml)
            sw_version = ET.fromstring(tree_xml.encode("utf-8")).get("swVersion")
        except ET.ParseError as e:
            warnings.append(f"component tree unreadable: {e}")
    elif doc_type == "ASSEMBLY":
        warnings.append("assembly has no component tree stream")
    features, configs, material = parse_keywords(sw.xml("swXmlContents/KeyWords"))
    if sw_version is None:
        fx = sw.xml("swXmlContents/Features")
        if fx:
            try:
                sw_version = ET.fromstring(fx.encode("utf-8")).get("swVersion")
            except ET.ParseError:
                pass
    custom = props.from_custom_xml(sw.xml("docProps/custom.xml"))
    if not custom:
        custom = props.from_property_set(sw.get("\x05DocumentSummaryInformation"))
    name = os.path.splitext(os.path.basename(path))[0]
    return SwDocument(path, sw.container, doc_type, name, sw_version, configs, material,
                      custom, features, tree, warnings)


def basename(sw_path: str) -> str:
    """File name from a stored Windows path."""
    return ntpath.basename(sw_path.replace("/", "\\"))
