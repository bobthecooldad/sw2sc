"""Reader for Parasolid neutral-binary transmit data (the geometry inside SolidWorks files).

Written from the published "Parasolid XT Format Reference" (node layouts, field types,
binary encoding, embedded-schema edit sequences). No Parasolid code is used.

The data is a sequence of nodes. Every node type has a list of fields; files written by
newer Parasolid versions describe, the first time each node type appears, how its field
list differs from the base schema (SCH_13006). BASE below is that base schema as the
reference documents it; the per-file edits are applied on top.

Result: ``Partition.nodes`` - {index: Node(type, name, fields)}, pointer fields as int
indices (0 = null).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAX_NODES = 5_000_000
MAX_VAR = 50_000_000

# field = (name, type, n_elts)  type: d int, n short, u byte, c char, l logical, w unichar,
# p pointer, f double, v vector, h hvec(3 doubles), i interval, b box, t tag(int)
_ANY_CURVE = "node_id:d attributes_groups:p owner:p next:p previous:p geometric_owner:p sense:c"
_ANY_SURF = _ANY_CURVE

_BASE_SPEC = {
    # topology
    10: ("ASSEMBLY", "highest_node_id:d attributes_groups:p attribute_chains:p list:p surface:p curve:p point:p key:p res_size:f res_linear:f ref_instance:p next:p previous:p state:u owner:p type:u sub_instance:p"),
    11: ("INSTANCE", "node_id:d attributes_groups:p type:u part:p transform:p assembly:p next_in_part:p prev_in_part:p next_of_part:p prev_of_part:p"),
    12: ("BODY", "highest_node_id:d attributes_groups:p attribute_chains:p surface:p curve:p point:p key:p res_size:f res_linear:f ref_instance:p next:p previous:p state:u owner:p body_type:u nom_geom_state:u shell:p boundary_surface:p boundary_curve:p boundary_point:p region:p edge:p vertex:p"),
    13: ("SHELL", "node_id:d attributes_groups:p body:p next:p face:p edge:p vertex:p region:p front_face:p"),
    14: ("FACE", "node_id:d attributes_groups:p tolerance:f next:p previous:p loop:p shell:p surface:p sense:c next_on_surface:p previous_on_surface:p next_front:p previous_front:p front_shell:p"),
    15: ("LOOP", "node_id:d attributes_groups:p fin:p face:p next:p"),
    16: ("EDGE", "node_id:d attributes_groups:p tolerance:f fin:p previous:p next:p curve:p next_on_curve:p previous_on_curve:p owner:p"),
    17: ("FIN", "attributes_groups:p loop:p forward:p backward:p vertex:p other:p edge:p curve:p next_at_vx:p sense:c"),
    18: ("VERTEX", "node_id:d attributes_groups:p fin:p previous:p next:p point:p tolerance:f owner:p"),
    19: ("REGION", "node_id:d attributes_groups:p body:p next:p previous:p shell:p type:c"),
    # geometry
    29: ("POINT", "node_id:d attributes_groups:p owner:p next:p previous:p pvec:v"),
    30: ("LINE", _ANY_CURVE + " pvec:v direction:v"),
    31: ("CIRCLE", _ANY_CURVE + " centre:v normal:v x_axis:v radius:f"),
    32: ("ELLIPSE", _ANY_CURVE + " centre:v normal:v x_axis:v major_radius:f minor_radius:f"),
    38: ("INTERSECTION", _ANY_CURVE + " surface:p[2] chart:p start:p end:p"),
    40: ("CHART", "base_parameter:f base_scale:f chart_count:d chordal_error:f angular_error:f parameter_error:f[2] hvec:h[]"),
    41: ("LIMIT", "type:c hvec:h[]"),
    45: ("BSPLINE_VERTICES", "vertices:f[]"),
    50: ("PLANE", _ANY_SURF + " pvec:v normal:v x_axis:v"),
    51: ("CYLINDER", _ANY_SURF + " pvec:v axis:v radius:f x_axis:v"),
    52: ("CONE", _ANY_SURF + " pvec:v axis:v radius:f sin_half_angle:f cos_half_angle:f x_axis:v"),
    53: ("SPHERE", _ANY_SURF + " centre:v radius:f axis:v x_axis:v"),
    54: ("TORUS", _ANY_SURF + " centre:v axis:v major_radius:f minor_radius:f x_axis:v"),
    56: ("BLENDED_EDGE", _ANY_SURF + " blend_type:c surface:p[2] spine:p range:f[2] thumb_weight:f[2] boundary:p[2] start:p end:p"),
    59: ("BLEND_BOUND", _ANY_SURF + " boundary:n blend:p"),
    60: ("OFFSET_SURF", _ANY_SURF + " check:c true_offset:l surface:p offset:f scale:f"),
    67: ("SWEPT_SURF", _ANY_SURF + " section:p sweep:v scale:f"),
    68: ("SPUN_SURF", _ANY_SURF + " profile:p base:v axis:v start:v end:v start_param:f end_param:f x_axis:v scale:f"),
    # associated data
    70: ("LIST", "node_id:d owner:p next:p previous:p list_type:d list_length:d block_length:d size_of_entry:d list_block:p"),
    74: ("POINTER_LIS_BLOCK", "n_entries:d next_block:p entries:p[]"),
    79: ("ATT_DEF_ID", "string:c[]"),
    80: ("ATTRIB_DEF", "next:p identifier:p type_id:d actions:u[8] field_names:p legal_owners:l[14] fields:u[]"),
    81: ("ATTRIBUTE", "node_id:d definition:p owner:p next:p previous:p next_of_type:p previous_of_type:p fields:p[]"),
    82: ("INT_VALUES", "values:d[]"),
    83: ("REAL_VALUES", "values:f[]"),
    84: ("CHAR_VALUES", "values:c[]"),
    85: ("POINT_VALUES", "values:v[]"),
    86: ("VECTOR_VALUES", "values:v[]"),
    87: ("AXIS_VALUES", "values:v[]"),
    88: ("TAG_VALUES", "values:t[]"),
    89: ("DIRECTION_VALUES", "values:v[]"),
    90: ("GROUP", "node_id:d attributes_groups:p owner:p next:p previous:p type:u first_member:p"),
    91: ("MEMBER_OF_GROUP", "dummy_node_id:d owning_group:p owner:p next:p previous:p next_member:p previous_member:p"),
    98: ("UNICODE_VALUES", "values:w[]"),
    99: ("FIELD_NAMES", "names:p[]"),
    100: ("TRANSFORM", "node_id:d owner:p next:p previous:p rotation_matrix:f[9] translation_vector:v scale:f flag:d perspective_vector:v"),
    101: ("WORLD", "assembly:p attribute:p body:p transform:p surface:p curve:p point:p alive:l attrib_def:p highest_id:d current_id:d"),
    102: ("KEY", "string:c[]"),
    120: ("PE_SURF", _ANY_SURF + " type:c data:p tf:p internal_geom:p[]"),
    121: ("INT_PE_DATA", "geom_type:d real_array:p int_array:p"),
    122: ("EXT_PE_DATA", "key:p real_array:p int_array:p"),
    124: ("B_SURFACE", _ANY_SURF + " nurbs:p data:p"),
    125: ("SURFACE_DATA", "original_uint:i original_vint:i extended_uint:i extended_vint:i self_int:u original_u_start:c original_u_end:c original_v_start:c original_v_end:c extended_u_start:c extended_u_end:c extended_v_start:c extended_v_end:c analytic_form_type:c swept_form_type:c spun_form_type:c blend_form_type:c analytic_form:p swept_form:p spun_form:p blend_form:p"),
    126: ("NURBS_SURF", "u_periodic:l v_periodic:l u_degree:n v_degree:n n_u_vertices:d n_v_vertices:d u_knot_type:u v_knot_type:u n_u_knots:d n_v_knots:d rational:l u_closed:l v_closed:l surface_form:u vertex_dim:n bspline_vertices:p u_knot_mult:p v_knot_mult:p u_knots:p v_knots:p"),
    127: ("KNOT_MULT", "mult:n[]"),
    128: ("KNOT_SET", "knots:f[]"),
    130: ("PE_CURVE", _ANY_CURVE + " type:c data:p tf:p internal_geom:p[]"),
    133: ("TRIMMED_CURVE", _ANY_CURVE + " basis_curve:p point_1:v point_2:v parm_1:f parm_2:f"),
    134: ("B_CURVE", _ANY_CURVE + " nurbs:p data:p"),
    135: ("CURVE_DATA", "self_int:u analytic_form:p"),
    136: ("NURBS_CURVE", "degree:n n_vertices:d vertex_dim:n n_knots:d knot_type:u periodic:l closed:l rational:l curve_form:u bspline_vertices:p knot_mult:p knots:p"),
    137: ("SP_CURVE", _ANY_CURVE + " surface:p b_curve:p original:p tolerance_to_original:f"),
    141: ("GEOMETRIC_OWNER", "owner:p next:p previous:p shared_geometry:p"),
    # The reference lists 163 as the curve form and 184 as the surface form, but sample files
    # show node 163 with the surface layout (no `point`, has `gap`), referenced from SURFACE_DATA.
    163: ("HELIX_SU_FORM", "axis_pt:v axis_dir:v hand:c turns:i pitch:f gap:f tol:f"),
    184: ("HELIX_CU_FORM", "axis_pt:v axis_dir:v point:v hand:c turns:i pitch:f tol:f"),
}


@dataclass
class FieldDef:
    name: str
    type: str
    n: int  # 0 scalar, 1 variable, >1 array
    xmt: bool = True


def _parse_spec(s: str) -> list[FieldDef]:
    out = []
    for tok in s.split():
        name, t = tok.split(":")
        n = 0
        if t.endswith("[]"):
            t, n = t[:-2], 1
        elif "[" in t:
            t, k = t[:-1].split("[")
            n = int(k)
        out.append(FieldDef(name, t, n))
    return out


BASE: dict[int, tuple[str, list[FieldDef]]] = {k: (v[0], _parse_spec(v[1])) for k, v in _BASE_SPEC.items()}


class XtError(Exception):
    pass


@dataclass
class Node:
    type: int
    name: str
    index: int
    f: dict = field(default_factory=dict)


class _Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d, self.p = data, pos

    def take(self, n: int) -> bytes:
        if self.p + n > len(self.d):
            raise XtError(f"unexpected end of data at {self.p}")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u8(self):
        return self.take(1)[0]

    def i16(self):
        return struct.unpack(">h", self.take(2))[0]

    def i32(self):
        return struct.unpack(">i", self.take(4))[0]

    def f64(self):
        return struct.unpack(">d", self.take(8))[0]

    def ptr(self):
        r = self.i16()
        q = 0
        if r < 0:
            q = self.i16()
            r = -r
        return q * 32767 + r - 1

    def sstr(self):
        n = self.u8()
        return self.take(n).decode("latin-1")


_SCALAR = {
    "d": lambda r: r.i32(), "t": lambda r: r.i32(), "n": lambda r: r.i16(), "w": lambda r: r.i16(),
    "u": lambda r: r.u8(), "c": lambda r: chr(r.u8()), "l": lambda r: bool(r.u8()),
    "p": lambda r: r.ptr(), "f": lambda r: r.f64(),
    "v": lambda r: (r.f64(), r.f64(), r.f64()), "h": lambda r: (r.f64(), r.f64(), r.f64()),
    "i": lambda r: (r.f64(), r.f64()), "b": lambda r: tuple(r.f64() for _ in range(6)),
}


@dataclass
class Partition:
    modeller: str
    schema: str
    nodes: dict[int, Node]
    warnings: list[str]

    def of_type(self, name: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.name == name]

    def get(self, idx) -> Node | None:
        return self.nodes.get(idx) if idx else None


def _read_fielddef(r: _Reader) -> FieldDef:
    name = r.sstr()
    ptr_class = r.i16()
    n = r.ptr()
    t = "p" if ptr_class else r.sstr()
    xmt = True
    if n == 1:
        xmt = bool(r.u8())
    return FieldDef(name, t, n, xmt)


def read(data: bytes) -> Partition:
    """Parse a neutral-binary transmit stream ('PS\\0\\0' ...)."""
    recent: list[tuple[str, int, int]] = []
    try:
        return _read(data, recent)
    except (XtError, struct.error, UnicodeDecodeError, ValueError, IndexError) as e:
        trail = ", ".join(f"{n}#{i}@{p}" for n, i, p in recent[-4:])
        raise XtError(f"{str(e)[:120]} (after {trail})") from e


def _read(data: bytes, recent: list) -> Partition:
    if data[:4] != b"PS\x00\x00":
        raise XtError("not a neutral binary Parasolid stream")
    r = _Reader(data, 4)
    modeller = r.take(r.i16()).decode("latin-1")
    schema = r.take(r.i32()).decode("latin-1")
    embedded = schema.count("_") >= 3
    if embedded:
        r.i16()  # maximum number of node types
    usfld = r.i32()
    if usfld < 0 or usfld > 16:
        raise XtError(f"bad user field size {usfld}")
    schemas: dict[int, tuple[str, list[FieldDef]]] = {}
    nodes: dict[int, Node] = {}
    warnings: list[str] = []
    while True:
        start = r.p
        ntype = r.i16()
        if ntype == 1:  # terminator
            break
        if ntype not in schemas:
            base = BASE.get(ntype)
            if not embedded:
                if base is None:
                    raise XtError(f"unknown node type {ntype} at {start}")
                schemas[ntype] = base
            elif base is None:
                nf = r.u8()
                name = r.sstr()
                r.sstr()  # description
                schemas[ntype] = (name, [_read_fielddef(r) for _ in range(nf)])
            else:
                flag = r.u8()
                if flag == 0xFF:
                    schemas[ntype] = base
                else:
                    cur: list[FieldDef] = []
                    bi = 0
                    bfields = base[1]
                    while True:
                        op = chr(r.u8())
                        if op == "C":
                            if bi >= len(bfields):
                                raise XtError(f"{base[0]}: copy past end of base schema")
                            cur.append(bfields[bi])
                            bi += 1
                        elif op == "D":
                            bi += 1
                        elif op in "IA":
                            cur.append(_read_fielddef(r))
                        elif op == "Z":
                            break
                        else:
                            raise XtError(f"{base[0]}: bad schema edit {op!r} at {r.p - 1}")
                    if bi != len(bfields):
                        raise XtError(f"{base[0]}: base schema has {len(bfields)} fields, file used {bi}")
                    if len(cur) != flag:
                        warnings.append(f"{base[0]}: expected {flag} fields, built {len(cur)}")
                    schemas[ntype] = (base[0], cur)
        name, fdefs = schemas[ntype]
        variable = any(fd.n == 1 for fd in fdefs)
        vlen = r.i32() if variable else 0
        if vlen < 0 or vlen > MAX_VAR:
            raise XtError(f"{name}: bad variable length {vlen} at {start}")
        index = r.ptr()
        node = Node(ntype, name, index)
        for fd in fdefs:
            if not fd.xmt:
                continue
            read1 = _SCALAR.get(fd.type)
            if read1 is None:
                raise XtError(f"{name}.{fd.name}: unknown field type {fd.type!r}")
            if fd.n == 0:
                node.f[fd.name] = read1(r)
            else:
                count = vlen if fd.n == 1 else fd.n
                node.f[fd.name] = [read1(r) for _ in range(count)]
        if usfld and index:
            r.take(4 * usfld)
        nodes[index] = node
        recent.append((name, index, start))
        if len(recent) > 8:
            del recent[0]
        if len(nodes) > MAX_NODES:
            raise XtError("too many nodes")
    # terminator index
    r.ptr()
    return Partition(modeller, schema, nodes, warnings)
