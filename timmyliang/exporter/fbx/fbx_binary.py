# -*- coding: utf-8 -*-
"""
Minimal FBX 7.3 binary writer.

Node layout (version < 7500):
  EndOffset       uint32   absolute offset from file start to byte after this node
  NumProperties   uint32
  PropertyListLen uint32
  NameLen         uint8
  Name            bytes
  Properties      ...
  NestedNodes     ...
  NullRecord      13 x 0x00  (only present when there are nested nodes)
"""

import io
import zlib
import struct

_MAGIC   = b"Kaydara FBX Binary  \x00\x1a\x00"
_VERSION = 7300
_NULL13  = b"\x00" * 13


# ---------------------------------------------------------------------------
# Property encoder
# ---------------------------------------------------------------------------

def _enc_prop(v):
    if isinstance(v, bool):
        return b"C" + struct.pack("<B", int(v))
    if isinstance(v, int):
        if -(1 << 15) <= v < (1 << 15):
            return b"Y" + struct.pack("<h", v)
        if -(1 << 31) <= v < (1 << 31):
            return b"I" + struct.pack("<i", v)
        return b"L" + struct.pack("<q", v)
    if isinstance(v, float):
        return b"D" + struct.pack("<d", v)
    if isinstance(v, bytes):
        return b"R" + struct.pack("<I", len(v)) + v
    if isinstance(v, str):
        b = v.encode("utf-8")
        return b"S" + struct.pack("<I", len(b)) + b
    if isinstance(v, (list, tuple)):
        if not v:
            return b"d" + struct.pack("<III", 0, 0, 0)
        if isinstance(v[0], float):
            raw  = struct.pack("<%sd" % len(v), *[float(x) for x in v])
            comp = zlib.compress(raw)
            return b"d" + struct.pack("<III", len(v), 1, len(comp)) + comp
        if isinstance(v[0], int):
            raw  = struct.pack("<%si" % len(v), *[int(x) for x in v])
            comp = zlib.compress(raw)
            return b"i" + struct.pack("<III", len(v), 1, len(comp)) + comp
    raise TypeError("unsupported FBX property type %s" % type(v))


# ---------------------------------------------------------------------------
# FBXNode  — builds its bytes including correct EndOffset
# ---------------------------------------------------------------------------

class FBXNode(object):
    def __init__(self, name, *props):
        self.name     = name.encode("utf-8") if isinstance(name, str) else name
        self.props    = list(props)
        self.children = []

    def node(self, name, *props):
        n = FBXNode(name, *props)
        self.children.append(n)
        return n

    def encode(self, base_offset):
        """
        Encode this node starting at absolute file offset `base_offset`.
        Returns the encoded bytes.  EndOffset in the header is patched to
        base_offset + len(result).
        """
        prop_bytes   = b"".join(_enc_prop(p) for p in self.props)
        header_size  = 4 + 4 + 4 + 1 + len(self.name)   # EndOff+NumP+PropLen+NameLen+Name

        # encode children first (we need their size to compute our EndOffset)
        child_bytes = b""
        child_offset = base_offset + header_size + len(prop_bytes)
        if self.children:
            for child in self.children:
                cb = child.encode(child_offset)
                child_bytes  += cb
                child_offset += len(cb)
            child_bytes += _NULL13   # sentinel after last child

        end_offset = base_offset + header_size + len(prop_bytes) + len(child_bytes)

        header = struct.pack("<III", end_offset, len(self.props), len(prop_bytes))
        header += struct.pack("<B", len(self.name))
        header += self.name

        return header + prop_bytes + child_bytes


# ---------------------------------------------------------------------------
# FBX file builder
# ---------------------------------------------------------------------------

GEO_ID   = 2035541511296
MODEL_ID = 2035615390896


def _p70_node(parent, *args):
    parent.node("P", *args)


def _make_header():
    h = FBXNode("FBXHeaderExtension")
    h.node("FBXHeaderVersion", 1003)
    h.node("FBXVersion", _VERSION)
    ts = h.node("CreationTimeStamp")
    ts.node("Version", 1000)
    for k, v in [("Year",2021),("Month",1),("Day",1),
                 ("Hour",0),("Minute",0),("Second",0),("Millisecond",0)]:
        ts.node(k, v)
    h.node("Creator", "RenderDoc FBX Exporter")
    return h


def _make_global_settings():
    g = FBXNode("GlobalSettings")
    g.node("Version", 1000)
    p70 = g.node("Properties70")
    for row in [
        ("UpAxis",               "int",    "Integer", "", 1),
        ("UpAxisSign",           "int",    "Integer", "", 1),
        ("FrontAxis",            "int",    "Integer", "", 2),
        ("FrontAxisSign",        "int",    "Integer", "", 1),
        ("CoordAxis",            "int",    "Integer", "", 0),
        ("CoordAxisSign",        "int",    "Integer", "", 1),
        ("OriginalUpAxis",       "int",    "Integer", "", -1),
        ("OriginalUpAxisSign",   "int",    "Integer", "", 1),
        ("UnitScaleFactor",      "double", "Number",  "", 1.0),
        ("OriginalUnitScaleFactor","double","Number", "", 1.0),
    ]:
        p70.node("P", *row)
    return g


def _make_definitions():
    d = FBXNode("Definitions")
    d.node("Version", 100)
    d.node("Count", 2)

    gt = d.node("ObjectType", "Geometry")
    gt.node("Count", 1)
    gt.node("PropertyTemplate", "FbxMesh").node("Properties70").node(
        "P", "Primary Visibility", "bool", "", "", True)

    mt = d.node("ObjectType", "Model")
    mt.node("Count", 1)
    mt.node("PropertyTemplate", "FbxNode").node("Properties70").node(
        "P", "Visibility", "Visibility", "", "A", 1.0)
    return d


def _make_objects(model_name, vertices, polygons,
                  normals, binormals, tangents,
                  colors, uvs, uv_indices, uvs2, uv2_indices):
    objects = FBXNode("Objects")

    geo = objects.node("Geometry", GEO_ID, "Geometry::", "Mesh")
    geo.node("Vertices",           [float(v) for v in vertices])
    geo.node("PolygonVertexIndex", [int(i)   for i in polygons])
    geo.node("GeometryVersion", 124)

    layer0_elems = []

    if normals:
        le = geo.node("LayerElementNormal", 0)
        le.node("Version", 101)
        le.node("Name", "")
        le.node("MappingInformationType", "ByPolygonVertex")
        le.node("ReferenceInformationType", "Direct")
        le.node("Normals", [float(v) for v in normals])
        layer0_elems.append(("LayerElementNormal", 0))

    if binormals:
        le = geo.node("LayerElementBinormal", 0)
        le.node("Version", 101)
        le.node("Name", "map1")
        le.node("MappingInformationType", "ByPolygonVertex")
        le.node("ReferenceInformationType", "Direct")
        le.node("Binormals", [float(v) for v in binormals])
        le.node("BinormalsW", [1.0] * (len(binormals) // 3))
        layer0_elems.append(("LayerElementBinormal", 0))

    if tangents:
        le = geo.node("LayerElementTangent", 0)
        le.node("Version", 101)
        le.node("Name", "map1")
        le.node("MappingInformationType", "ByPolygonVertex")
        le.node("ReferenceInformationType", "Direct")
        le.node("Tangents", [float(v) for v in tangents])
        layer0_elems.append(("LayerElementTangent", 0))

    if colors:
        n_poly = len(colors) // 4
        le = geo.node("LayerElementColor", 0)
        le.node("Version", 101)
        le.node("Name", "colorSet1")
        le.node("MappingInformationType", "ByPolygonVertex")
        le.node("ReferenceInformationType", "IndexToDirect")
        le.node("Colors", [float(v) for v in colors])
        le.node("ColorIndex", list(range(n_poly)))
        layer0_elems.append(("LayerElementColor", 0))

    if uvs and uv_indices is not None:
        le = geo.node("LayerElementUV", 0)
        le.node("Version", 101)
        le.node("Name", "map1")
        le.node("MappingInformationType", "ByPolygonVertex")
        le.node("ReferenceInformationType", "IndexToDirect")
        le.node("UV", [float(v) for v in uvs])
        le.node("UVIndex", [int(i) for i in uv_indices])
        layer0_elems.append(("LayerElementUV", 0))

    layer0 = geo.node("Layer", 0)
    layer0.node("Version", 100)
    for elem_type, idx in layer0_elems:
        ref = layer0.node("LayerElement")
        ref.node("Type", elem_type)
        ref.node("TypedIndex", idx)

    if uvs2 and uv2_indices is not None:
        le = geo.node("LayerElementUV", 1)
        le.node("Version", 101)
        le.node("Name", "map2")
        le.node("MappingInformationType", "ByPolygonVertex")
        le.node("ReferenceInformationType", "IndexToDirect")
        le.node("UV", [float(v) for v in uvs2])
        le.node("UVIndex", [int(i) for i in uv2_indices])

        layer1 = geo.node("Layer", 1)
        layer1.node("Version", 100)
        ref = layer1.node("LayerElement")
        ref.node("Type", "LayerElementUV")
        ref.node("TypedIndex", 1)

    mdl = objects.node("Model", MODEL_ID, "Model::%s" % model_name, "Mesh")
    mdl.node("Version", 232)
    p70 = mdl.node("Properties70")
    p70.node("P", "DefaultAttributeIndex", "int", "Integer", "", 0)
    p70.node("P", "InheritType", "enum", "", "", 1)
    mdl.node("Shading", True)
    mdl.node("Culling", "CullingOff")

    return objects


def _make_connections(model_name):
    c = FBXNode("Connections")
    c.node("C", "OO", MODEL_ID, 0)
    c.node("C", "OO", GEO_ID, MODEL_ID)
    return c


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class FBXWriter(object):
    def __init__(self, model_name):
        self.model_name = model_name

    def write(self, path, vertices, polygons,
              normals=None, binormals=None, tangents=None,
              colors=None, uvs=None, uv_indices=None,
              uvs2=None, uv2_indices=None):

        top_nodes = [
            _make_header(),
            _make_global_settings(),
            _make_definitions(),
            _make_objects(self.model_name, vertices, polygons,
                          normals, binormals, tangents,
                          colors, uvs, uv_indices, uvs2, uv2_indices),
            _make_connections(self.model_name),
        ]

        # file layout:
        #   magic (23) + version (4) + nodes + null13 + padding + footer
        header_size = len(_MAGIC) + 4   # 27 bytes before first node

        # encode each top-level node with correct base offset
        encoded = []
        offset  = header_size
        for node in top_nodes:
            b = node.encode(offset)
            encoded.append(b)
            offset += len(b)

        # FBX footer: 16-byte magic + 15 zeros + version uint32 + zeros to 136 total
        footer = (
            b"\xfa\xbc\xab\x09\xd0\xc8\xd4\x66\xb1\x76\xfb\x83\x1c\xf7\x26\x7e" +
            b"\x00" * 15 +
            struct.pack("<I", _VERSION) +
            b"\x00" * 101
        )

        with open(path, "wb") as f:
            f.write(_MAGIC)
            f.write(struct.pack("<I", _VERSION))
            for b in encoded:
                f.write(b)
            f.write(_NULL13)
            f.write(footer)
