# -*- coding: utf-8 -*-
"""
FBX / OBJ Mesh Exporter for RenderDoc
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

__author__ = "timmyliang"
__email__ = "820472580@qq.com"
__date__ = "2021-01-26 20:44:17"


import os
import time
import struct
import inspect
import tempfile
from textwrap import dedent
from functools import partial
from collections import defaultdict

from PySide2 import QtWidgets, QtCore

import qrenderdoc
import renderdoc as rd

from .query_dialog import QueryDialog
from .progress_dialog import MProgressDialog

# ---------------------------------------------------------------------------
# FBX ASCII template
# ---------------------------------------------------------------------------

FBX_ASCII_TEMPLETE = """
    ; FBX 7.3.0 project file
    ; ----------------------------------------------------

    ; Object definitions
    ;------------------------------------------------------------------

    Definitions:  {

        ObjectType: "Geometry" {
            Count: 1
            PropertyTemplate: "FbxMesh" {
                Properties70:  {
                    P: "Primary Visibility", "bool", "", "",1
                }
            }
        }

        ObjectType: "Model" {
            Count: 1
            PropertyTemplate: "FbxNode" {
                Properties70:  {
                    P: "Visibility", "Visibility", "", "A",1
                }
            }
        }
    }

    ; Object properties
    ;------------------------------------------------------------------

    Objects:  {
        Geometry: 2035541511296, "Geometry::", "Mesh" {
            Vertices: *%(vertices_num)s {
                a: %(vertices)s
            }
            PolygonVertexIndex: *%(polygons_num)s {
                a: %(polygons)s
            }
            GeometryVersion: 124
            %(LayerElementNormal)s
            %(LayerElementBiNormal)s
            %(LayerElementTangent)s
            %(LayerElementColor)s
            %(LayerElementUV)s
            %(LayerElementUV2)s
            Layer: 0 {
                Version: 100
                %(LayerElementNormalInsert)s
                %(LayerElementBiNormalInsert)s
                %(LayerElementTangentInsert)s
                %(LayerElementColorInsert)s
                %(LayerElementUVInsert)s

            }
            Layer: 1 {
                Version: 100
                %(LayerElementUV2Insert)s
            }
        }
        Model: 2035615390896, "Model::%(model_name)s", "Mesh" {
            Properties70:  {
                P: "DefaultAttributeIndex", "int", "Integer", "",0
            }
        }
%(FbxMaterialObjects)s
%(FbxSkinObjects)s
    }

    ; Object connections
    ;------------------------------------------------------------------

    Connections:  {

        ;Model::pCube1, Model::RootNode
        C: "OO",2035615390896,0

        ;Geometry::, Model::pCube1
        C: "OO",2035541511296,2035615390896

%(FbxMaterialConnections)s
%(FbxSkinConnections)s
    }

    """


def _build_fbx_material(save_dir, fbx_name):
    """Scan *save_dir* for images previously exported alongside the FBX and
    build FBX ASCII Material + Texture node strings (Objects section) and
    the corresponding Connection entries.

    Returns (material_objects_str, material_connections_str).  Both are empty
    strings when no suitable textures are found.
    """
    import re as _re

    # Collect image files in the same directory
    _img_exts = {".png", ".jpg", ".jpeg", ".tga", ".dds", ".bmp", ".hdr", ".exr"}
    try:
        _all_files = [
            f for f in os.listdir(save_dir)
            if os.path.splitext(f)[1].lower() in _img_exts
        ]
    except OSError:
        return "", ""

    if not _all_files:
        return "", ""

    # Classify textures by common suffix patterns
    _NORMAL_SUFFIXES  = _re.compile(r"_n(rm|ormal|ormal_map)?$", _re.IGNORECASE)
    _ROUGH_SUFFIXES   = _re.compile(r"_(rough|roughness|orm|pbr)$", _re.IGNORECASE)
    _METAL_SUFFIXES   = _re.compile(r"_(metal|metallic|m)$",        _re.IGNORECASE)
    _EMIT_SUFFIXES    = _re.compile(r"_(emit|emissive|e)$",          _re.IGNORECASE)

    _diffuse   = None   # first non-special image (probably diffuse / albedo)
    _normal_m  = None
    _rough_m   = None
    _emissive  = None

    for _f in sorted(_all_files):
        _stem = os.path.splitext(_f)[0]
        if _NORMAL_SUFFIXES.search(_stem):
            _normal_m = _normal_m or _f
        elif _ROUGH_SUFFIXES.search(_stem) or _METAL_SUFFIXES.search(_stem):
            _rough_m = _rough_m or _f
        elif _EMIT_SUFFIXES.search(_stem):
            _emissive = _emissive or _f
        else:
            _diffuse = _diffuse or _f

    # Build texture list: (channel_name, filename, prop_name)
    _TEX_SLOTS = []
    if _diffuse:   _TEX_SLOTS.append(("DiffuseColor", _diffuse,  "DiffuseColor"))
    if _normal_m:  _TEX_SLOTS.append(("NormalMap",    _normal_m, "NormalMap"))
    if _rough_m:   _TEX_SLOTS.append(("Roughness",    _rough_m,  "SpecularColor"))
    if _emissive:  _TEX_SLOTS.append(("Emissive",     _emissive, "EmissiveColor"))

    if not _TEX_SLOTS:
        return "", ""

    # Assign deterministic IDs (well beyond the Geometry/Model IDs above)
    _MAT_ID  = 3000000000001
    _OBJ_BLK = ""
    _CON_BLK = ""

    # Material node
    _OBJ_BLK += """
        Material: %d, "Material::%s_mat", "" {
            Version: 102
            ShadingModel: "phong"
            MultiLayer: 0
            Properties70:  {
                P: "AmbientColor",  "Color", "", "A",0.1,0.1,0.1
                P: "DiffuseColor",  "Color", "", "A",0.8,0.8,0.8
            }
        }""" % (_MAT_ID, fbx_name)

    _CON_BLK += "\n        ;Material, Model\n"
    _CON_BLK += "        C: \"OO\",%d,2035615390896\n" % _MAT_ID

    for _ci, (_chan, _fname, _prop) in enumerate(_TEX_SLOTS):
        _tex_id = _MAT_ID + _ci + 1
        _rel    = "./%s" % _fname
        _OBJ_BLK += """
        Texture: %d, "Texture::%s", "" {
            Type: "TextureVideoClip"
            Version: 202
            TextureName: "Texture::%s"
            Properties70:  {
                P: "CurrentTextureBlendMode", "enum", "", "",0
                P: "UVSet",                  "KString","","", "map1"
            }
            Media: "Video::%s"
            FileName: "%s"
            RelativeFilename: "%s"
            ModelUVTranslation: 0,0
            ModelUVScaling: 1,1
            Texture_Alpha_Source: "None"
            Cropping: 0,0,0,0
        }""" % (_tex_id, _chan, _chan, _chan, _fname, _rel)

        _CON_BLK += "        ;Texture::%s, Material::%s_mat\n" % (_chan, fbx_name)
        _CON_BLK += "        C: \"OP\",%d,%d, \"%s\"\n" % (_tex_id, _MAT_ID, _prop)

    return _OBJ_BLK, _CON_BLK


# ---------------------------------------------------------------------------
# Mesh data helpers
# ---------------------------------------------------------------------------

def _scan_available_attrs(main_window):
    """Scan the Mesh Viewer table for available vertex attribute names.

    Returns a sorted list of attribute root names (e.g. ["NORMAL", "POSITION",
    "TEXCOORD0"]).  Returns an empty list when no mesh table is found.
    """
    for table_name in ("vsinData", "inTable"):
        table = main_window.findChild(QtWidgets.QTableView, table_name)
        if table:
            model = table.model()
            attrs = set()
            for c in range(model.columnCount()):
                head = model.headerData(c, QtCore.Qt.Horizontal)
                if head and "." in head:
                    attrs.add(head.split(".")[0])
            return sorted(attrs)
    return []


def _collect_mesh_data(main_window):
    """Read all vertex attribute columns from the Mesh Viewer table.

    Returns ``(data, attr_list)`` where *data* is a ``defaultdict(list)``
    keyed by attribute name (e.g. ``"POSITION"`` → ``[[x,y,z], ...]`` per
    row) and *attr_list* is the set of multi-component attribute names.
    Returns ``(None, None)`` when the table widget cannot be found.
    """
    table = None
    for table_name in ("vsinData", "inTable"):
        table = main_window.findChild(QtWidgets.QTableView, table_name)
        if table:
            break

    if not table:
        return None, None

    model        = table.model()
    row_count    = model.rowCount()
    column_count = model.columnCount()
    rows         = range(row_count)
    columns      = range(column_count)

    data      = defaultdict(list)
    attr_list = set()

    for _, c in MProgressDialog.loop(columns, status="Collect Mesh Data"):
        head   = model.headerData(c, QtCore.Qt.Horizontal)
        values = [model.data(model.index(r, c)) for r in rows]
        if "." not in head:
            data[head] = values
        else:
            attr = head.split(".")[0]
            attr_list.add(attr)
            data[attr].append(values)

    for _, attr in MProgressDialog.loop(attr_list, status="Rearrange Mesh Data"):
        values_list = data[attr]
        data[attr]  = [[float(values[r]) for values in values_list] for r in rows]

    return data, attr_list


# ---------------------------------------------------------------------------
# FBX export
# ---------------------------------------------------------------------------

def export_fbx(save_path, mapper, data, attr_list, controller):
    """Write *data* to *save_path* in FBX ASCII format."""

    if not data:
        return

    save_name = os.path.basename(os.path.splitext(save_path)[0])

    idx_dict   = data["IDX"]
    value_dict = defaultdict(list)
    vertex_data = defaultdict(dict)

    for i, idx in enumerate(idx_dict):
        for attr in attr_list:
            value = data[attr][i]
            value_dict[attr].append(value)
            if idx not in vertex_data[attr]:
                vertex_data[attr][idx] = value

    ARGS = {
        "model_name":                save_name,
        "LayerElementNormal":        "",
        "LayerElementNormalInsert":  "",
        "LayerElementBiNormal":      "",
        "LayerElementBiNormalInsert":"",
        "LayerElementTangent":       "",
        "LayerElementTangentInsert": "",
        "LayerElementColor":         "",
        "LayerElementColorInsert":   "",
        "LayerElementUV":            "",
        "LayerElementUVInsert":      "",
        "LayerElementUV2":           "",
        "LayerElementUV2Insert":     "",
        "FbxMaterialObjects":        "",
        "FbxMaterialConnections":    "",
        "FbxSkinObjects":            "",
        "FbxSkinConnections":        "",
    }

    POSITION = mapper.get("POSITION")
    NORMAL   = mapper.get("NORMAL")
    BINORMAL = mapper.get("BINORMAL")
    TANGENT  = mapper.get("TANGENT")
    COLOR    = mapper.get("COLOR")
    UV       = mapper.get("UV")
    UV2      = mapper.get("UV2")
    ENGINE   = mapper.get("ENGINE")
    flip_u   = mapper.get("FLIP_U", False)
    flip_v   = mapper.get("FLIP_V", True)

    min_poly = min(idx_dict)
    idx_list = [idx - min_poly for idx in idx_dict]
    idx_len  = len(idx_list)

    def transform_rx_neg90_mirror_x(values):
        x, y, z = values[:3]
        return [-x, z, -y]

    def transform_unreal_vector(values):
        if ENGINE != "unreal":
            return list(values[:3])
        return transform_rx_neg90_mirror_x(values)

    def reorder_triangle_corners(values):
        if ENGINE != "unreal":
            return list(values)
        return list(values)

    class ProcessHandler(object):
        def run(self):
            curr = time.time()
            for name, func in inspect.getmembers(self, inspect.isroutine):
                if name.startswith("run_"):
                    func()
            print("elapsed time template: %s" % (time.time() - curr))

        def run_vertices(self):
            transformed = [
                transform_unreal_vector(values)
                for idx, values in sorted(vertex_data[POSITION].items())
            ]
            vertices = [str(v) for values in transformed for v in values]
            ARGS["vertices"]     = ",".join(vertices)
            ARGS["vertices_num"] = len(vertices)

        def run_polygons(self):
            polygon_indices = reorder_triangle_corners(idx_list)
            polygons = [
                str(idx ^ -1 if i % 3 == 2 else idx)
                for i, idx in enumerate(polygon_indices)
            ]
            ARGS["polygons"]     = ",".join(polygons)
            ARGS["polygons_num"] = len(polygons)

        def run_normals(self):
            if not vertex_data.get(NORMAL):
                return
            # ── Diagnostic: show first-vertex values for NORMAL & TANGENT ──
            # If normals look like tangents, ATTRIBUTE1/ATTRIBUTE2 may be swapped.
            # Check: normal vectors should be ~unit-length; dot(normal, tangent)≈0.
            _nv0 = next(iter(vertex_data[NORMAL].values()), None)
            TANGENT_key = mapper.get("TANGENT", "")
            _tv0 = (next(iter(vertex_data[TANGENT_key].values()), None)
                    if TANGENT_key and vertex_data.get(TANGENT_key) else None)
            _ndiag = [round(v, 3) for v in _nv0[:3]] if _nv0 else []
            _tdiag = [round(v, 3) for v in _tv0[:3]] if _tv0 else []
            print("[normals diag] nrm_v0=%s  tan_v0=%s" % (_ndiag, _tdiag))

            normal_values      = reorder_triangle_corners(value_dict[NORMAL])
            transformed_normals = [transform_unreal_vector(v) for v in normal_values]
            normals = [str(v) for values in transformed_normals for v in values]
            ARGS["LayerElementNormal"] = """
                LayerElementNormal: 0 {
                    Version: 101
                    Name: ""
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "Direct"
                    Normals: *%(normals_num)s {
                        a: %(normals)s
                    }
                }
            """ % {"normals": ",".join(normals), "normals_num": len(normals)}
            ARGS["LayerElementNormalInsert"] = """
                LayerElement:  {
                        Type: "LayerElementNormal"
                    TypedIndex: 0
                }
            """

        def run_binormals(self):
            if not vertex_data.get(BINORMAL):
                return
            transformed = [transform_unreal_vector(v) for v in value_dict[BINORMAL]]
            binormals = [str(-v) for values in transformed for v in values]
            ARGS["LayerElementBiNormal"] = """
                LayerElementBinormal: 0 {
                    Version: 101
                    Name: "map1"
                    MappingInformationType: "ByVertice"
                    ReferenceInformationType: "Direct"
                    Binormals: *%(binormals_num)s {
                        a: %(binormals)s
                    }
                    BinormalsW: *%(binormalsW_num)s {
                        a: %(binormalsW)s
                    }
                }
            """ % {
                "binormals":     ",".join(binormals),
                "binormals_num": len(binormals),
                "binormalsW":    ",".join(["1" for _ in range(idx_len)]),
                "binormalsW_num": idx_len,
            }
            ARGS["LayerElementBiNormalInsert"] = """
                LayerElement:  {
                        Type: "LayerElementBinormal"
                    TypedIndex: 0
                }
            """

        def run_tangents(self):
            if not vertex_data.get(TANGENT):
                return
            tangent_values = reorder_triangle_corners(value_dict[TANGENT])
            transformed    = [transform_unreal_vector(v) for v in tangent_values]
            tangents = [str(v) for values in transformed for v in values]
            ARGS["LayerElementTangent"] = """
                LayerElementTangent: 0 {
                    Version: 101
                    Name: "map1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "Direct"
                    Tangents: *%(tangents_num)s {
                        a: %(tangents)s
                    }
                }
            """ % {"tangents": ",".join(tangents), "tangents_num": len(tangents)}
            ARGS["LayerElementTangentInsert"] = """
                    LayerElement:  {
                        Type: "LayerElementTangent"
                        TypedIndex: 0
                    }
            """

        def run_color(self):
            if not vertex_data.get(COLOR):
                return
            color_values = reorder_triangle_corners(value_dict[COLOR])
            colors = [
                str(v)
                for values in color_values
                for i, v in enumerate(values, 1)
            ]
            ARGS["LayerElementColor"] = """
                LayerElementColor: 0 {
                    Version: 101
                    Name: "colorSet1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "IndexToDirect"
                    Colors: *%(colors_num)s {
                        a: %(colors)s
                    }
                    ColorIndex: *%(colors_indices_num)s {
                        a: %(colors_indices)s
                    }
                }
            """ % {
                "colors":             ",".join(colors),
                "colors_num":         len(colors),
                "colors_indices":     ",".join([str(i) for i in range(len(color_values))]),
                "colors_indices_num": idx_len,
            }
            ARGS["LayerElementColorInsert"] = """
                LayerElement:  {
                    Type: "LayerElementColor"
                    TypedIndex: 0
                }
            """

        def run_uv(self):
            if not vertex_data.get(UV):
                return
            uv_index_values = reorder_triangle_corners(idx_list)
            uvs_indices     = ",".join([str(idx) for idx in uv_index_values])
            uvs = [
                str((1 - v if flip_u else v) if i == 0 else (1 - v if flip_v else v))
                for idx, values in sorted(vertex_data[UV].items())
                for i, v in enumerate(values)
            ]
            ARGS["LayerElementUV"] = """
                LayerElementUV: 0 {
                    Version: 101
                    Name: "map1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "IndexToDirect"
                    UV: *%(uvs_num)s {
                        a: %(uvs)s
                    }
                    UVIndex: *%(uvs_indices_num)s {
                        a: %(uvs_indices)s
                    }
                }
            """ % {
                "uvs":             ",".join(uvs),
                "uvs_num":         len(uvs),
                "uvs_indices":     uvs_indices,
                "uvs_indices_num": idx_len,
            }
            ARGS["LayerElementUVInsert"] = """
                LayerElement:  {
                    Type: "LayerElementUV"
                    TypedIndex: 0
                }
            """

        def run_uv2(self):
            if not vertex_data.get(UV2):
                return
            uv2_index_values = reorder_triangle_corners(idx_list)
            uvs_indices      = ",".join([str(idx) for idx in uv2_index_values])
            uvs = [
                str((1 - v if flip_u else v) if i == 0 else (1 - v if flip_v else v))
                for idx, values in sorted(vertex_data[UV2].items())
                for i, v in enumerate(values)
            ]
            ARGS["LayerElementUV2"] = """
                LayerElementUV: 1 {
                    Version: 101
                    Name: "map2"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "IndexToDirect"
                    UV: *%(uvs_num)s {
                        a: %(uvs)s
                    }
                    UVIndex: *%(uvs_indices_num)s {
                        a: %(uvs_indices)s
                    }
                }
            """ % {
                "uvs":             ",".join(uvs),
                "uvs_num":         len(uvs),
                "uvs_indices":     uvs_indices,
                "uvs_indices_num": idx_len,
            }
            ARGS["LayerElementUV2Insert"] = """
                LayerElement:  {
                    Type: "LayerElementUV"
                    TypedIndex: 1
                }
            """

    handler = ProcessHandler()
    handler.run()

    save_dir = os.path.dirname(save_path)
    _mat_objs, _mat_cons = _build_fbx_material(save_dir, save_name)
    ARGS["FbxMaterialObjects"]     = _mat_objs
    ARGS["FbxMaterialConnections"] = _mat_cons

    fbx = FBX_ASCII_TEMPLETE % ARGS

    with open(save_path, "w") as f:
        f.write(dedent(fbx).strip())


# ---------------------------------------------------------------------------
# OBJ export  (NEW)
# ---------------------------------------------------------------------------

def export_obj(save_path, mapper, data, attr_list, controller):
    """Write *data* to *save_path* in Wavefront OBJ format.

    OBJ is widely supported by Blender, Maya, 3ds Max, Houdini and many other
    DCC tools without requiring the FBX SDK.  Vertex positions, UVs, normals
    and (as comments) vertex colors are written.
    """
    if not data:
        return

    save_name  = os.path.basename(os.path.splitext(save_path)[0])
    idx_dict   = data["IDX"]
    value_dict = defaultdict(list)
    vertex_data = defaultdict(dict)

    for i, idx in enumerate(idx_dict):
        for attr in attr_list:
            value = data[attr][i]
            value_dict[attr].append(value)
            if idx not in vertex_data[attr]:
                vertex_data[attr][idx] = value

    POSITION = mapper.get("POSITION")
    NORMAL   = mapper.get("NORMAL")
    UV       = mapper.get("UV")
    COLOR    = mapper.get("COLOR")
    ENGINE   = mapper.get("ENGINE")
    flip_u   = mapper.get("FLIP_U", False)
    flip_v   = mapper.get("FLIP_V", True)

    min_poly = min(idx_dict)
    idx_list = [idx - min_poly for idx in idx_dict]

    def xform(values):
        """Apply engine-specific coordinate conversion."""
        if ENGINE != "unreal":
            return list(values[:3])
        x, y, z = values[:3]
        return [-x, z, -y]

    lines = [
        "# OBJ exported from RenderDoc by renderdoc2fbx",
        "# Mesh: %s" % save_name,
        "# Vertices: %d  Triangles: %d" % (
            len(set(idx_dict)) , len(idx_list) // 3),
        "",
    ]

    # ── Vertex positions (unique per vertex index) ───────────────────────────
    has_pos = POSITION and vertex_data.get(POSITION)
    if has_pos:
        for _, v in sorted(vertex_data[POSITION].items()):
            p = xform(v)
            lines.append("v %.6f %.6f %.6f" % (p[0], p[1], p[2]))
        lines.append("")

    # ── Texture coordinates (unique per vertex index, IndexToDirect) ─────────
    has_uv = UV and vertex_data.get(UV)
    if has_uv:
        for _, v in sorted(vertex_data[UV].items()):
            u  = (1.0 - v[0]) if flip_u else v[0]
            vv = (1.0 - v[1]) if flip_v else v[1]
            lines.append("vt %.6f %.6f" % (u, vv))
        lines.append("")

    # ── Normals (per polygon vertex — one entry per face corner) ─────────────
    has_normal = NORMAL and vertex_data.get(NORMAL)
    if has_normal:
        for nvals in value_dict[NORMAL]:
            n = xform(nvals)
            lines.append("vn %.6f %.6f %.6f" % (n[0], n[1], n[2]))
        lines.append("")

    # ── Vertex color as OBJ extension comments ────────────────────────────────
    has_color = COLOR and vertex_data.get(COLOR)
    if has_color:
        lines.append("# Vertex colors (r g b a per unique vertex):")
        for idx, cv in sorted(vertex_data[COLOR].items()):
            comps = " ".join("%.4f" % c for c in cv[:4])
            lines.append("# vc %d %s" % (idx - min_poly, comps))
        lines.append("")

    # ── Faces ─────────────────────────────────────────────────────────────────
    lines.append("g %s" % save_name)
    num_tris = len(idx_list) // 3
    for tri in range(num_tris):
        parts = []
        for corner in range(3):
            li = tri * 3 + corner          # linear poly-vert index (0-based)
            vi = idx_list[li] + 1          # OBJ position index (1-based)
            ni = li + 1                    # OBJ normal index  (1-based, per-poly-vert)
            if has_uv and has_normal:
                parts.append("%d/%d/%d" % (vi, vi, ni))
            elif has_uv:
                parts.append("%d/%d" % (vi, vi))
            elif has_normal:
                parts.append("%d//%d" % (vi, ni))
            else:
                parts.append(str(vi))
        lines.append("f " + " ".join(parts))

    with open(save_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# VS Output export (clip-space reconstruction)
# ---------------------------------------------------------------------------

def _read_vsin_attrs_from_gpu(mapper, info_list, controller):
    """Read VS Input vertex attributes directly from the GPU vertex buffer.

    This bypasses the Qt Mesh-Viewer table entirely, which is unreliable in
    VS Output view mode because RenderDoc repopulates the same table widget
    with VS Output attribute data (named ``_input0``…``_inputN`` for Vulkan /
    DX12 DXIL shaders) instead of VS Input data.

    Attribute-name mapping
    ----------------------
    The pipeline vertex-input layout may use:
    - D3D11/D3D12 semantic style: ``TEXCOORD0``, ``NORMAL``, ``ATTRIBUTE5`` …
    - Vulkan location style:      ``_input0``, ``_input1``, ``_input4`` …

    For each layout slot we generate ALL plausible aliases so that a mapper
    configured with ``UV = "ATTRIBUTE5"`` still matches the slot that lives at
    Vulkan location 5 (or slot index 5) regardless of what RenderDoc calls it.

    Returns
    -------
    attr_data : dict
        ``{attr_name: [[comp0, comp1, …], …]}`` — one list entry per **unique
        vertex** in the VS Input vertex buffer.
    vsin_nidxs : list[int]
        Normalized 0-based vertex index for every face corner (draw index),
        built from the VS Input index buffer.  Directly usable as UV-index
        array for FBX ``IndexToDirect``.
    """
    attr_data  = {}
    vsin_nidxs = []

    try:
        # ── VS Input vertex buffer ────────────────────────────────────────────
        fmt_in = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSIn)
        if fmt_in.numIndices == 0:
            info_list.append("vsin_gpu: 0 indices – no VS Input data")
            return attr_data, vsin_nidxs

        raw     = bytes(controller.GetBufferData(fmt_in.vertexResourceId, 0, 0))
        vbo_off = fmt_in.vertexByteOffset
        vb_data = raw[vbo_off:] if vbo_off < len(raw) else raw
        stride  = fmt_in.vertexByteStride
        nv      = len(vb_data) // stride    # unique vertex count

        info_list.append("vsin_gpu: %d unique verts  stride=%d bytes" % (nv, stride))

        # ── VS Input index buffer → face-corner vertex index list ─────────────
        idx_raw  = _read_index_buffer(fmt_in, controller)
        if idx_raw is None:
            idx_raw = list(range(nv))
        min_idx   = min(idx_raw) if idx_raw else 0
        vsin_nidxs = [v - min_idx for v in idx_raw]

        # ── Collect ALL vertex buffers: VS Input primary + VS Output buffer ────
        # GetVertexBuffers() is unavailable in some RenderDoc versions.
        # However, the VS Output vertex buffer IS always accessible and the
        # vertex shader typically passes UV through as an output attribute
        # (TEXCOORD0 etc.).  We add the VS Output buffer as a secondary scan
        # source so we can find UV even when the VS Input VB has all-zero UV.
        all_vb = []   # list of (raw_bytes, stride)
        all_vb.append((vb_data, stride))   # primary VS Input buffer

        # Try GetVertexBuffers() (newer RenderDoc)
        try:
            state0  = controller.GetPipelineState()
            vb_list = state0.GetVertexBuffers()
            for bi, vb_b in enumerate(vb_list):
                rid  = getattr(vb_b, 'resourceId', None)
                boff = int(getattr(vb_b, 'byteOffset', 0) or 0)
                bstr = int(getattr(vb_b, 'byteStride', 0) or 0)
                if not rid or rid == rd.ResourceId.Null() or bstr <= 0:
                    continue
                if rid == fmt_in.vertexResourceId:
                    continue
                try:
                    raw_bi  = bytes(controller.GetBufferData(rid, 0, 0))
                    data_bi = raw_bi[boff:] if boff < len(raw_bi) else raw_bi
                    nv_bi   = len(data_bi) // bstr
                    if nv_bi >= nv // 2:   # plausible vertex count
                        all_vb.append((data_bi, bstr))
                        info_list.append("vsin_gpu: extra VB binding %d stride=%d verts=%d" % (
                            bi, bstr, nv_bi))
                except Exception:
                    pass
        except Exception as e:
            info_list.append("vsin_gpu: GetVertexBuffers() skipped: %s" % str(e))

        # Try to add VS Output vertex buffer as an additional scan source.
        # The vertex shader typically passes UV through to its outputs, so
        # the UV should be present in the VS Output buffer even when it's
        # missing or mis-offset in the VS Input buffer.
        try:
            fmt_out_scan = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
            if (fmt_out_scan.numIndices > 0 and
                    fmt_out_scan.vertexResourceId != rd.ResourceId.Null()):
                raw_vs = bytes(controller.GetBufferData(
                    fmt_out_scan.vertexResourceId, 0, 0))
                vs_off = fmt_out_scan.vertexByteOffset
                vs_str = fmt_out_scan.vertexByteStride
                vb_vs  = raw_vs[vs_off:] if vs_off < len(raw_vs) else raw_vs
                nv_vs  = len(vb_vs) // vs_str if vs_str > 0 else 0
                if nv_vs >= nv // 2:
                    all_vb.append((vb_vs, vs_str))
                    info_list.append("vsin_gpu: added VS Output VB stride=%d verts=%d" % (
                        vs_str, nv_vs))
        except Exception as e:
            info_list.append("vsin_gpu: VS Output VB: %s" % str(e))

        # Hex dump of first vertex for diagnostics (bytes 0-63 of VB0)
        if vb_data and stride > 0:
            _hdump = " ".join("%02X" % vb_data[i] for i in range(min(stride, 64)))
            info_list.append("vsin_gpu v0_hex: " + _hdump)
            _fdump = " ".join("@%d:%.3f" % (i*4, struct.unpack_from("<f", vb_data, i*4)[0])
                              for i in range(min(stride//4, 16)))
            info_list.append("vsin_gpu v0_f32: " + _fdump)

        # ── Vertex input layout → byte-offset map ─────────────────────────────
        state   = controller.GetPipelineState()
        va_list = state.GetVertexInputs()

        # Sort by declared location so we can accumulate offsets in HW order
        def _va_loc(iv):
            return getattr(iv[1], 'location', iv[0])
        va_sorted = sorted(enumerate(va_list), key=_va_loc)

        # Collect raw info per slot
        slot_info = []   # (slot_i, loc, comp, width, reported_off)
        for slot_i, va in va_sorted:
            fmt_va  = getattr(va, 'format', None)
            comp    = getattr(fmt_va, 'compCount',     4) if fmt_va else 4
            width   = getattr(fmt_va, 'compByteWidth', 4) if fmt_va else 4
            rep_off = int(getattr(va, 'byteOffset', 0) or 0)
            loc     = getattr(va, 'location', slot_i)
            slot_info.append((slot_i, loc, comp, width, rep_off))

        # If ALL reported byteOffsets are 0, the API isn't providing them.
        # Compute accumulated offsets instead.  Try two strategies and pick the
        # one whose total matches the vertex stride.
        any_nonzero = any(si[4] > 0 for si in slot_info)

        if any_nonzero:
            # Use API-reported offsets (most accurate)
            computed_offsets = [si[4] for si in slot_info]
            info_list.append("vsin_gpu offsets: api-reported")
        else:
            # Strategy A: natural (no padding)
            nat_offs, nat_cum = [], 0
            for _, _, comp, width, _ in slot_info:
                nat_offs.append(nat_cum)
                nat_cum += comp * width

            # Strategy B: float4-aligned (each attribute rounded up to 4-comp boundary)
            aln_offs, aln_cum = [], 0
            for _, _, comp, width, _ in slot_info:
                aln_offs.append(aln_cum)
                raw = comp * width
                aligned = ((raw + 4 * width - 1) // (4 * width)) * (4 * width)
                aln_cum += aligned

            if abs(aln_cum - stride) <= 4:
                computed_offsets = aln_offs
                info_list.append("vsin_gpu offsets: float4-aligned  total=%d stride=%d" % (aln_cum, stride))
            elif abs(nat_cum - stride) <= 4:
                computed_offsets = nat_offs
                info_list.append("vsin_gpu offsets: natural  total=%d stride=%d" % (nat_cum, stride))
            else:
                # Neither standard strategy fits the stride.
                # The most common explanation is trailing per-vertex padding:
                # attributes are packed tightly (natural layout), and the
                # remainder of the stride is unused space.  As long as
                # nat_cum <= stride, natural offsets are safe to use.
                computed_offsets = nat_offs
                if nat_cum <= stride:
                    info_list.append("vsin_gpu offsets: natural+pad  nat=%d stride=%d" % (nat_cum, stride))
                else:
                    info_list.append("vsin_gpu offsets: FALLBACK nat=%d aln=%d stride=%d" % (nat_cum, aln_cum, stride))

        # Identify comp=2 slots as UV candidates (hint for user)
        uv_hints = [
            "_input%d/ATTRIBUTE%d(off%d)" % (loc, loc, computed_offsets[i])
            for i, (_, loc, comp, _, _) in enumerate(slot_info) if comp == 2
        ]
        if uv_hints:
            info_list.append("vsin_gpu UV_candidates(comp=2): %s" % " ".join(uv_hints))

        layout = {}   # name_variant -> (byteOffset, compCount, compByteWidth, fmtChar)
        for idx, (slot_i, loc, comp, width, _) in enumerate(slot_info):
            off  = computed_offsets[idx]
            # Format char: 4-byte→float, 2-byte→half-float, 1-byte→signed byte
            if   width == 4: fc = "f"
            elif width == 2: fc = "e"   # half-float (Python ≥ 3.6)
            elif width == 1: fc = "b"   # int8 (packed SNORM tangent/normal)
            else:            fc = "f"
            info = (off, comp, width, fc)

            # Collect name aliases
            va    = va_sorted[idx][1]
            sname = (getattr(va, 'semanticName', '') or '').strip()
            sidx  = getattr(va, 'semanticIndex', 0)
            candidates = set()
            if sname:
                candidates.add(sname + str(sidx))
                if sidx == 0:
                    candidates.add(sname)
                candidates.add(sname.upper() + str(sidx))
            candidates.add("_input%d" % loc)
            candidates.add("_input%d" % slot_i)
            candidates.add("ATTRIBUTE%d" % loc)
            candidates.add("ATTRIBUTE%d" % slot_i)

            for name in candidates:
                if name and name not in layout:
                    layout[name] = info

        # Show slot details so user can identify UV / Color names
        slot_detail = []
        for idx, (slot_i, loc, comp, width, _) in enumerate(slot_info):
            slot_detail.append("loc%d:off%d:comp%d" % (loc, computed_offsets[idx], comp))
        info_list.append("vsin_gpu slots=[%s]" % " ".join(slot_detail))
        info_list.append("vsin_gpu layout keys=[%s]" %
                         ",".join(sorted(layout.keys())[:14]))

        # ── Read each requested attribute ──────────────────────────────────────
        for key in ("POSITION", "NORMAL", "TANGENT", "BINORMAL", "COLOR", "UV", "UV2"):
            attr_name = mapper.get(key, "")
            if not attr_name:
                continue
            if attr_name not in layout:
                info_list.append("  %s=%r -> MISSING (not in layout)" % (key, attr_name))
                continue
            off, comp, width, fc = layout[attr_name]
            verts = []
            for vi in range(nv):
                base = vi * stride + off
                if base + comp * width > len(vb_data):
                    break
                raw = list(struct.unpack_from("<%d%s" % (comp, fc), vb_data, base))
                # Normalise packed integer types to float range
                if fc == "b":          # int8 SNORM → [-1, 1]
                    raw = [v / 127.0 for v in raw]
                elif fc == "B":        # uint8 UNORM → [0, 1]
                    raw = [v / 255.0 for v in raw]
                # half-float "e" is already a Python float — no conversion needed
                verts.append(raw)

            # ── For UV/UV2: verify values look like UV, scan if not ────────────
            # "Collapsed to a point" happens when:
            # (a) offset is wrong (reads from padding → all zeros), or
            # (b) format is half-float but API reports width=4 (float32) → tiny
            #
            # Detection: if max absolute value across first 20 verts < 0.01,
            # scan the ENTIRE vertex stride for float16 / float32 pairs whose
            # values are in the plausible UV range [0.001, 10] with variation.
            if key in ("UV", "UV2") and comp == 2:
                _sample = [abs(v) for e in verts[:20] for v in e
                           if v == v and not (v != v)]  # filter NaN
                _max_v  = max(_sample) if _sample else 0.0

                if _max_v < 0.01:
                    # Current read gives no real UV data.
                    # Scan EVERY bound vertex buffer at EVERY 2-byte-aligned offset,
                    # trying both float16 and float32.
                    # Rejection heuristics (to avoid bone-weights / normals):
                    #   • Normals (SNORM): u+v ≈ const per vertex → low std-dev of sums
                    #   • Bone-weights: u+v ≈ 1.0 → mean(abs(u+v-1)) < 0.05
                    #   • UV: values cover 2-D area, sums NOT pinned to 1
                    info_list.append("  %s: near-zero (max=%.2e), scanning all VBs…" % (key, _max_v))
                    _best_score, _best_verts, _best_desc = -1, None, ""

                    for _vbi, (_vbd, _vbstr) in enumerate(all_vb):
                        _nvb = len(_vbd) // _vbstr if _vbstr > 0 else 0
                        # For primary VB (vbi=0): skip known attribute region
                        # (offsets 0..nat_cum-1 are position/tangent/normal, NOT UV).
                        # For VS Output buffer: skip SV_Position (first 16 bytes).
                        if _vbi == 0:
                            _start_off = nat_cum      # scan only the "extra" region
                        elif _vbi == len(all_vb) - 1:
                            _start_off = 16           # skip SV_Position in VS Out
                        else:
                            _start_off = 0
                        for _scan_off in range(_start_off, _vbstr - 1, 2):
                            for _sfmt, _sbpc in (("e", 2), ("f", 4)):
                                _need = comp * _sbpc
                                if _scan_off + _need > _vbstr:
                                    continue
                                _sv = []
                                for _vi in range(min(50, _nvb)):
                                    _b = _vi * _vbstr + _scan_off
                                    if _b + _need > len(_vbd):
                                        break
                                    _sv.append(list(struct.unpack_from(
                                        "<%d%s" % (comp, _sfmt), _vbd, _b)))
                                if len(_sv) < 5:
                                    continue
                                _vals = [v for _e in _sv for v in _e]
                                _in_range = sum(1 for v in _vals if 0.001 <= abs(v) <= 10.0)
                                _nonzero  = sum(1 for v in _vals if abs(v) > 0.001)
                                _vmax     = max(abs(v) for v in _vals)
                                _unique   = len(set(round(v, 3) for v in _vals))
                                # Bone-weight detection: u+v must be BOTH pinned near
                                # 1.0 (>95%) AND very low variance — normal UV can
                                # have u+v≈1 coincidentally, but bone weights ALWAYS
                                # sum to exactly 1 with near-zero variance.
                                _sums = [_sv[i][0] + _sv[i][1] for i in range(len(_sv))]
                                _mean_s = sum(_sums) / max(len(_sums), 1)
                                _var_s  = sum((s - _mean_s)**2 for s in _sums) / max(len(_sums), 1)
                                _n1 = sum(1 for s in _sums if abs(s - 1.0) < 0.03)
                                if _n1 > len(_sums) * 0.95 and _var_s < 0.005:
                                    continue   # almost certainly bone weights
                                # Require genuine 2D spread in both axes
                                _us = [_sv[i][0] for i in range(len(_sv))]
                                _vs_v = [_sv[i][1] for i in range(len(_sv))]
                                _urange = max(_us) - min(_us) if _us else 0
                                _vrange = max(_vs_v) - min(_vs_v) if _vs_v else 0
                                if _urange < 0.02 or _vrange < 0.02:
                                    continue   # degenerate (collapsed axis)
                                # Bonus for all-positive values (UV coords are ≥0)
                                _all_pos = sum(1 for v in _vals if v >= 0)
                                _score = (_in_range + _nonzero * 2 + min(_unique, 20)
                                          + (_all_pos // 2))
                                if (0.001 <= _vmax <= 10.0 and
                                        _nonzero >= len(_vals) * 0.3 and
                                        _in_range >= len(_vals) * 0.7 and
                                        _score > _best_score):
                                    _best_score = _score
                                    _best_desc  = "vb%d off=%d fmt=%s str=%d" % (
                                        _vbi, _scan_off, _sfmt, _vbstr)
                                    _best_verts = (_vbd, _vbstr, _nvb, _scan_off, _sfmt, _sbpc)

                    if _best_verts is not None:
                        _vbd, _vbstr, _nvb, _scan_off, _sfmt, _sbpc = _best_verts
                        _new_verts = []
                        for _vi in range(_nvb):
                            _b = _vi * _vbstr + _scan_off
                            if _b + comp * _sbpc > len(_vbd):
                                break
                            _new_verts.append(list(struct.unpack_from(
                                "<%d%s" % (comp, _sfmt), _vbd, _b)))
                        if _new_verts:
                            verts = _new_verts
                            info_list.append("  %s: scan→ %s (score=%d  uR=%.2f vR=%.2f)" % (
                                key, _best_desc, _best_score,
                                max(v[0] for v in _new_verts[:20]) - min(v[0] for v in _new_verts[:20]),
                                max(v[1] for v in _new_verts[:20]) - min(v[1] for v in _new_verts[:20])))
                    else:
                        info_list.append("  %s: scan found nothing in any VB" % key)

            attr_data[attr_name] = verts
            info_list.append("  %s=%r -> OK  %d verts  comp=%d  byteOff=%d  fmt=%s" % (
                key, attr_name, len(verts), comp, off, fc))

        # ── Auto-detect missing UV2 / Color when Vulkan remaps attribute IDs ──
        # Vulkan relocates ATTRIBUTE6 (UV2) and ATTRIBUTE13 (Color) to lower
        # locations that don't match Unreal's D3D semantic numbers.  When the
        # mapper name isn't found in the layout, scan the vertex buffer for a
        # candidate that matches the expected component pattern and value range.
        _uv_attr  = mapper.get("UV",    "")
        _uv2_attr = mapper.get("UV2",   "")
        _col_attr = mapper.get("COLOR", "")

        # Compute UV0 centre-of-mass so UV2 candidates can be discriminated.
        _uv0_cx = _uv0_cy = 0.0
        _uv0_n  = 0
        if _uv_attr and attr_data.get(_uv_attr):
            _uv0s = attr_data[_uv_attr][:50]
            if _uv0s:
                _uv0_cx = sum(e[0] for e in _uv0s) / len(_uv0s)
                _uv0_cy = sum(e[1] for e in _uv0s) / len(_uv0s)
                _uv0_n  = len(_uv0s)

        for _mkey, _mattr, _mcomp in [("UV2", _uv2_attr, 2),
                                       ("COLOR", _col_attr, 4)]:
            if not _mattr or attr_data.get(_mattr):
                continue       # already found or not requested
            info_list.append("  auto-scan %s (attr=%r)…" % (_mkey, _mattr))
            _best_sc, _best_info = -1, None

            for _avbd, _avbstr in all_vb:
                _anvb = len(_avbd) // _avbstr if _avbstr > 0 else 0
                for _aso in range(0, _avbstr, 2):
                    for _asfmt, _asbpc in [("f", 4), ("e", 2), ("B", 1), ("b", 1)]:
                        _anb = _mcomp * _asbpc
                        if _aso + _anb > _avbstr:
                            continue
                        _asv = []
                        for _avi in range(min(50, _anvb)):
                            _ab = _avi * _avbstr + _aso
                            if _ab + _anb > len(_avbd): break
                            _araw = list(struct.unpack_from(
                                "<%d%s" % (_mcomp, _asfmt), _avbd, _ab))
                            if _asfmt == "b": _araw = [v/127.0 for v in _araw]
                            elif _asfmt == "B": _araw = [v/255.0 for v in _araw]
                            _asv.append(_araw)
                        if len(_asv) < 5: continue
                        _avals = [v for e in _asv for v in e]

                        if _mkey == "UV2":
                            _aus = [e[0] for e in _asv]
                            _avs = [e[1] for e in _asv]
                            _ura = max(_aus) - min(_aus) if _aus else 0
                            _vra = max(_avs) - min(_avs) if _avs else 0
                            _amx = max(abs(v) for v in _avals)
                            if not (0.001 <= _amx <= 10 and _ura >= 0.02 and _vra >= 0.02):
                                continue
                            # Reject if centre matches UV0 (same channel)
                            if _uv0_n:
                                _acx = sum(_aus) / len(_aus)
                                _acy = sum(_avs) / len(_avs)
                                if abs(_acx - _uv0_cx) + abs(_acy - _uv0_cy) < 0.05:
                                    continue
                            _asc = (sum(1 for v in _avals if 0.001 <= abs(v) <= 10) +
                                    len(set(round(v, 2) for v in _avals)))
                        else:  # COLOR
                            # UNORM: all values in [0,1], none negative
                            if any(v < -0.01 for v in _avals): continue
                            if max(_avals) > 1.05: continue
                            _asc = (sum(1 for v in _avals if v > 0.001) +
                                    len(set(round(v, 2) for v in _avals)))

                        if _asc > _best_sc:
                            _best_sc   = _asc
                            _best_info = (_avbd, _avbstr, _anvb, _aso, _asfmt, _asbpc)

            if _best_info:
                _avbd, _avbstr, _anvb, _aso, _asfmt, _asbpc = _best_info
                _afinal = []
                for _avi in range(_anvb):
                    _ab = _avi * _avbstr + _aso
                    if _ab + _mcomp * _asbpc > len(_avbd): break
                    _araw = list(struct.unpack_from(
                        "<%d%s" % (_mcomp, _asfmt), _avbd, _ab))
                    if _asfmt == "b": _araw = [v/127.0 for v in _araw]
                    elif _asfmt == "B": _araw = [v/255.0 for v in _araw]
                    _afinal.append(_araw)
                if _afinal:
                    attr_data[_mattr] = _afinal
                    info_list.append("  %s=%r auto-found: off=%d fmt=%s score=%d %dverts" % (
                        _mkey, _mattr, _aso, _asfmt, _best_sc, len(_afinal)))

    except Exception:
        import traceback
        info_list.append("vsin_gpu ERROR: " + traceback.format_exc().split('\n')[-2])

    return attr_data, vsin_nidxs

def _read_index_buffer(fmt, controller):
    """Read the index buffer referenced by *fmt* and return a list of ints.

    Returns ``None`` when:
    - no index buffer is attached (non-indexed draw), or
    - an error occurs while reading.

    Returned indices are normalized to 0-based (minimum index is subtracted).
    Supports uint16 (stride=2) and uint32 (stride=4) index formats.
    """
    if fmt.indexResourceId == rd.ResourceId.Null():
        return None
    try:
        raw        = bytes(controller.GetBufferData(fmt.indexResourceId, 0, 0))
        byte_off   = fmt.indexByteOffset
        idx_stride = fmt.indexByteStride
        count      = fmt.numIndices

        if idx_stride == 2:
            pack_char = "H"   # uint16
        elif idx_stride == 4:
            pack_char = "I"   # uint32
        else:
            return None

        indices = []
        for i in range(count):
            base = byte_off + i * idx_stride
            if base + idx_stride > len(raw):
                break
            indices.append(struct.unpack_from("<" + pack_char, raw, base)[0])

        if not indices:
            return None

        # Normalize: subtract base-vertex so indices start at 0
        min_idx = min(indices)
        if min_idx != 0:
            indices = [v - min_idx for v in indices]
        return indices
    except Exception:
        return None


def _scan_bone_data(vb_data, stride, nv, nat_cum, info_list=None):
    """Scan the 'extra' region of a vertex buffer for bone weight/index data.

    Looks for two adjacent regions:
      • BoneWeights: N×float or N×uint8  all in [0,1], sum ≈ 1.0
      • BoneIndices: N×uint8 or N×uint16 all small integers (0-255)

    Returns (weights_list, indices_list) where each list has *nv* entries of
    length N (N = 4 or 8), or (None, None) if nothing convincing is found.
    """
    if nat_cum >= stride or nv < 5:
        return None, None

    IDENTITY_4x4 = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]

    # Try n_bones=4 first, then 8 (common in UE4/UE5)
    for n_bones in (4, 8):
        # Strategy A: float weights (4B each) + byte indices (1B each)
        for wfmt, wbpc in [("f", 4), ("B", 1)]:  # try float32 then uint8 weights
            for ifmt, ibpc in [("B", 1), ("H", 2)]:  # byte then uint16 indices
                _w_sz = n_bones * wbpc
                _i_sz = n_bones * ibpc
                # Try every 4-byte-aligned offset in the extra region
                for _woff in range(nat_cum, stride - _w_sz - _i_sz + 1, 4):
                    _ioff = _woff + _w_sz
                    if _ioff + _i_sz > stride:
                        continue
                    # Sample first min(20, nv) vertices
                    _wsamples = []
                    _isamples = []
                    ok = True
                    for _vi in range(min(20, nv)):
                        _wb = _vi * stride + _woff
                        _ib = _vi * stride + _ioff
                        if _wb + _w_sz > len(vb_data) or _ib + _i_sz > len(vb_data):
                            ok = False; break
                        _w = list(struct.unpack_from("<%d%s" % (n_bones, wfmt), vb_data, _wb))
                        _i = list(struct.unpack_from("<%d%s" % (n_bones, ifmt), vb_data, _ib))
                        if wfmt == "B": _w = [v/255.0 for v in _w]
                        # Validate: weights in [0,1], sum ≈ 1, indices are small ints
                        if any(w < -0.01 or w > 1.05 for w in _w): ok = False; break
                        if abs(sum(_w) - 1.0) > 0.15: ok = False; break
                        if any(idx > 512 for idx in _i): ok = False; break
                        _wsamples.append(_w)
                        _isamples.append(_i)
                    if not ok or len(_wsamples) < 5:
                        continue
                    # Passed all checks — read all vertices
                    all_w, all_i = [], []
                    for _vi in range(nv):
                        _wb = _vi * stride + _woff
                        _ib = _vi * stride + _ioff
                        if _wb + _w_sz > len(vb_data) or _ib + _i_sz > len(vb_data):
                            break
                        _w = list(struct.unpack_from("<%d%s" % (n_bones, wfmt), vb_data, _wb))
                        _i = list(struct.unpack_from("<%d%s" % (n_bones, ifmt), vb_data, _ib))
                        if wfmt == "B": _w = [v/255.0 for v in _w]
                        all_w.append(_w)
                        all_i.append(_i)
                    if len(all_w) >= nv * 0.9:
                        if info_list is not None:
                            info_list.append(
                                "bone_scan: %d bones woff=%d wfmt=%s ioff=%d ifmt=%s "
                                "(%d verts)" % (n_bones, _woff, wfmt, _ioff, ifmt, len(all_w)))
                        return all_w, all_i
    return None, None


def _build_fbx_skin(weights_list, indices_list, n_verts, geom_id=2035541511296):
    """Build FBX ASCII SkinDeformer + Cluster nodes from bone data.

    *weights_list*  – list of per-vertex weight arrays  (len == n_verts)
    *indices_list*  – list of per-vertex bone-index arrays
    *n_verts*       – total vertex count (needed for identity transforms)
    *geom_id*       – the Geometry node ID to attach the deformer to

    Returns (objects_str, connections_str) to embed in the FBX file.
    """
    if not weights_list or not indices_list:
        return "", ""

    n_bones_per_vert = len(weights_list[0])

    # Discover unique bone indices
    all_bone_ids = set()
    for idxs in indices_list:
        all_bone_ids.update(idxs)
    all_bone_ids = sorted(all_bone_ids)

    # Build per-bone influence lists
    bone_verts   = {b: [] for b in all_bone_ids}
    bone_weights = {b: [] for b in all_bone_ids}
    for vi, (ws, idxs) in enumerate(zip(weights_list, indices_list)):
        for w, bi in zip(ws, idxs):
            if w > 0.001:
                bone_verts[bi].append(vi)
                bone_weights[bi].append(w)

    SKIN_ID = 4000000000001
    _objs = ""
    _cons = ""

    # Skin deformer node
    _objs += """
        Deformer: %d, "Deformer::", "Skin" {
            Version: 101
            Link_DeformAcuracy: 50
        }""" % SKIN_ID
    _cons += "\n        C: \"OO\",%d,%d\n" % (SKIN_ID, geom_id)

    # Identity transform (4×4 row-major, but FBX wants column-major 16 floats)
    _identity = ",".join(["1" if i % 5 == 0 else "0" for i in range(16)])

    for bone_idx in all_bone_ids:
        _cluster_id = SKIN_ID + bone_idx + 1
        _bverts  = bone_verts[bone_idx]
        _bwgts   = bone_weights[bone_idx]
        if not _bverts:
            continue
        _vi_str = ",".join(str(v) for v in _bverts)
        _wg_str = ",".join("%.6f" % w for w in _bwgts)

        # Joint node (placeholder — RenderDoc has no bone hierarchy)
        _joint_id = _cluster_id + 100000
        _objs += """
        Model: %d, "Model::Joint_%d", "LimbNode" {
            Version: 232
            Properties70: {
                P: "RotationActive",  "bool", "", "",1
                P: "InheritType",     "enum", "", "",1
            }
        }""" % (_joint_id, bone_idx)

        _objs += """
        Deformer: %d, "SubDeformer::", "Cluster" {
            Version: 100
            UserData: "", ""
            Indexes: *%d { a: %s }
            Weights: *%d { a: %s }
            Transform: *16 { a: %s }
            TransformLink: *16 { a: %s }
        }""" % (_cluster_id, len(_bverts), _vi_str,
                len(_bwgts), _wg_str, _identity, _identity)

        # Connect joint to model root, cluster to skin deformer, cluster to joint
        _cons += "        C: \"OO\",%d,0\n" % _joint_id
        _cons += "        C: \"OO\",%d,%d\n" % (_cluster_id, SKIN_ID)
        _cons += "        C: \"OO\",%d,%d\n" % (_joint_id, _cluster_id)

    return _objs, _cons


def _try_get_view_matrix(controller):
    """Try to extract the View (or ViewProjection) matrix from VS constant buffer 0.

    Scans the first 512 bytes of the VS stage's first constant buffer for a
    4×4 float matrix whose upper-left 3×3 is approximately orthonormal
    (rotation-only) and whose determinant is approximately ±1.  Returns the
    4×4 matrix as a flat 16-element list (row-major) or None on failure.
    """
    try:
        state = controller.GetPipelineState()
        vs_cbs = state.GetConstantBuffers(rd.ShaderStage.Vertex)
        if not vs_cbs:
            return None
        cb0 = vs_cbs[0]
        cb_id = getattr(cb0, 'resourceId', None)
        if not cb_id or cb_id == rd.ResourceId.Null():
            return None

        raw = bytes(controller.GetBufferData(cb_id, 0, 512))

        # Slide a 4×4 float window over the buffer and test each candidate
        for _off in range(0, len(raw) - 64, 4):
            _m = list(struct.unpack_from("<16f", raw, _off))
            # Test upper-left 3×3 for approximate orthonormality
            def _col(c): return [_m[r*4+c] for r in range(3)]
            c0, c1, c2 = _col(0), _col(1), _col(2)
            def _dot(a, b): return sum(x*y for x, y in zip(a, b))
            def _norm(v): return _dot(v, v) ** 0.5
            n0, n1, n2 = _norm(c0), _norm(c1), _norm(c2)
            if not (0.9 < n0 < 1.1 and 0.9 < n1 < 1.1 and 0.9 < n2 < 1.1):
                continue
            # Check cross-orthogonality: |dot(c0,c1)|, |dot(c0,c2)|, |dot(c1,c2)| < 0.05
            if (abs(_dot(c0, c1)) > 0.05 or abs(_dot(c0, c2)) > 0.05 or
                    abs(_dot(c1, c2)) > 0.05):
                continue
            # Determinant of 3×3 (cross product c0 × c1 · c2) ≈ ±1
            _cross = [c0[1]*c1[2]-c0[2]*c1[1],
                      c0[2]*c1[0]-c0[0]*c1[2],
                      c0[0]*c1[1]-c0[1]*c1[0]]
            if abs(abs(_dot(_cross, c2)) - 1.0) > 0.1:
                continue
            return _m   # found a valid rotation matrix

    except Exception:
        pass
    return None


def _mat4_inv_rigid(m):
    """Invert a rigid-body 4×4 matrix (rotation+translation only, row-major).
    For a View matrix V, returns V^{-1} (camera-to-world / WorldFromView).
    Layout: row r, col c → m[r*4+c].
    """
    # Transpose the 3×3 rotation part
    r = [[m[r2*4+c2] for c2 in range(3)] for r2 in range(3)]
    rt = [[r[c2][r2] for c2 in range(3)] for r2 in range(3)]
    # Translation = -R^T * t
    t = [m[0*4+3], m[1*4+3], m[2*4+3]]
    nt = [-sum(rt[i][j]*t[j] for j in range(3)) for i in range(3)]
    return [
        rt[0][0], rt[0][1], rt[0][2], nt[0],
        rt[1][0], rt[1][1], rt[1][2], nt[1],
        rt[2][0], rt[2][1], rt[2][2], nt[2],
        0,        0,        0,        1,
    ]


def _apply_mat4_point(m, x, y, z):
    """Transform point (x,y,z) by 4×4 row-major matrix m (w=1)."""
    return (m[0]*x + m[1]*y + m[2]*z + m[3],
            m[4]*x + m[5]*y + m[6]*z + m[7],
            m[8]*x + m[9]*y + m[10]*z + m[11])


def _export_vsout_fbx(save_path, mapper, info_list, err_list,
                      vs_in_data, vs_in_attr_list, controller):
    """Export VS Output mesh with reconstructed view-space positions.

    Vertex positions come from SV_Position (clip-space) + projection-matrix
    reconstruction.  UV and Normal channels are optionally sourced from the
    VS Input vertex buffer (same draw call, same index buffer) and written as
    proper FBX LayerElement blocks so DCC tools receive correct texture
    mapping without a second import step.

    Args:
        vs_in_data:      dict returned by _collect_mesh_data (VS Input table),
                         or None if the caller chose not to include VS In attrs.
        vs_in_attr_list: set of attribute names present in vs_in_data, or None.
    """
    import traceback
    try:
        fmt_out    = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSOut)
        status_str = str(fmt_out.status) if fmt_out.status else ""
        if status_str:
            err_list.append("GetPostVSData(VSOut) failed: %s" % status_str)
            return

        if fmt_out.numIndices == 0:
            err_list.append("VS Output has 0 vertices")
            return

        out_buf   = bytes(controller.GetBufferData(fmt_out.vertexResourceId, 0, 0))
        out_vbo   = fmt_out.vertexByteOffset
        out_bytes = out_buf[out_vbo:] if out_vbo < len(out_buf) else out_buf
        stride    = fmt_out.vertexByteStride
        cc        = fmt_out.format.compCount
        cw        = fmt_out.format.compByteWidth
        char      = "f" if cw == 4 else "d"
        actual    = len(out_bytes) // stride
        near      = fmt_out.nearPlane
        far       = fmt_out.farPlane

        clip_pos = []
        for i in range(actual):
            base = i * stride
            if base + 4 * cw > len(out_bytes):
                break
            comps = struct.unpack_from("<%d%s" % (min(cc, 4), char), out_bytes, base)
            clip_pos.append(comps)

        if not clip_pos:
            err_list.append("No clip positions read")
            return

        m00 = m11 = None
        try:
            fmt_in    = controller.GetPostVSData(0, 0, rd.MeshDataStage.VSIn)
            si        = str(fmt_in.status) if fmt_in.status else ""
            if not si and fmt_in.numIndices > 0:
                in_buf    = bytes(controller.GetBufferData(fmt_in.vertexResourceId, 0, 0))
                in_vbo    = fmt_in.vertexByteOffset
                in_bytes  = in_buf[in_vbo:] if in_vbo < len(in_buf) else in_buf
                in_stride = fmt_in.vertexByteStride
                in_cc     = fmt_in.format.compCount
                in_cw     = fmt_in.format.compByteWidth
                in_char   = "f" if in_cw == 4 else "d"
                in_actual = min(len(in_bytes) // in_stride, actual)
                m00_list, m11_list = [], []
                for i in range(min(in_actual, 100)):
                    base = i * in_stride
                    if base + in_cc * in_cw > len(in_bytes):
                        break
                    vp     = struct.unpack_from("<%d%s" % (in_cc, in_char), in_bytes, base)
                    if len(clip_pos) <= i:
                        break
                    cp     = clip_pos[i]
                    cw_val = cp[3] if len(cp) >= 4 else 1.0
                    if abs(cw_val) < 0.001:
                        continue
                    if len(vp) >= 1 and abs(vp[0]) > 0.01:
                        m00_list.append(cp[0] / vp[0])
                    if len(vp) >= 2 and abs(vp[1]) > 0.01:
                        m11_list.append(cp[1] / vp[1])
                if m00_list:
                    m00_list.sort()
                    m00 = m00_list[len(m00_list) // 2]
                if m11_list:
                    m11_list.sort()
                    m11 = m11_list[len(m11_list) // 2]
        except Exception:
            pass

        aspect = 1.0
        try:
            state = controller.GetPipelineState()
            vp    = state.GetViewport(0)
            if vp.height > 0:
                aspect = float(vp.width) / float(vp.height)
        except Exception:
            pass

        if not (m00 and m11 and abs(m00 - 1.0) > 0.01):
            m11 = 1.732
            m00 = m11 / aspect if aspect > 0 else m11

        info_list.append("aspect=%.4f m00=%.4f m11=%.4f actual=%d" % (
            aspect, m00, m11, actual))

        # Build vertex positions.
        # IMPORTANT: write a placeholder (0,0,0) instead of skipping degenerate
        # vertices (w≈0) so that every clip_pos[i] maps to vertex index i.
        # Skipping with `continue` would shift subsequent indices and corrupt faces.
        vertices = []
        for cp in clip_pos:
            cx, cy, cz = cp[0], cp[1], cp[2]
            cw_val = cp[3] if len(cp) >= 4 else 1.0
            if abs(cw_val) < 1e-6:
                # Degenerate clip vertex — emit a placeholder to keep index alignment
                vertices.extend([0.0, 0.0, 0.0])
                continue
            ndc_z = cz / cw_val
            if far > 1e30:
                denom  = 1.0 - ndc_z
                view_z = near / denom if abs(denom) > 1e-9 else cw_val
            else:
                denom  = far - ndc_z * (far - near)
                view_z = (near * far / denom) if abs(denom) > 1e-9 else cw_val
            vx = cx / m00
            vy = cy / m11
            vertices.extend([vx, vy, view_z])

        # ── Optional: bake view-space → world-space via inv(ViewMatrix) ───────
        bake_world = mapper.get("BAKE_WORLD_SPACE", False)
        _view_inv  = None
        if bake_world:
            _vm = _try_get_view_matrix(controller)
            if _vm:
                _view_inv = _mat4_inv_rigid(_vm)
                info_list.append("world-space: ViewMatrix found, baking positions")
            else:
                info_list.append("world-space: ViewMatrix NOT found, staying view-space")
        if _view_inv and len(vertices) % 3 == 0:
            _ws = []
            for _vi3 in range(len(vertices) // 3):
                _vx, _vy, _vz = vertices[_vi3*3], vertices[_vi3*3+1], vertices[_vi3*3+2]
                _wx, _wy, _wz = _apply_mat4_point(_view_inv, _vx, _vy, _vz)
                _ws.extend([_wx, _wy, _wz])
            vertices = _ws

        if len(vertices) >= 9:
            info_list.append("v0=%s v1=%s v2=%s" % (
                [round(x, 3) for x in vertices[0:3]],
                [round(x, 3) for x in vertices[3:6]],
                [round(x, 3) for x in vertices[6:9]]))

        # Read the real index buffer that connects vertices into triangles.
        # Sequential fallback is used only for non-indexed (vertex-array) draws.
        idx_list = _read_index_buffer(fmt_out, controller)
        has_ib   = idx_list is not None
        if not has_ib:
            idx_list = list(range(len(clip_pos)))
        n_fc = len(idx_list)   # face corners — must be defined before GPU attr read
        info_list.append("index_buf=%s  faces=%d" % (
            "yes" if has_ib else "no (sequential)", n_fc // 3))

        polygons = [~idx if i % 3 == 2 else idx for i, idx in enumerate(idx_list)]

        save_name = os.path.basename(os.path.splitext(save_path)[0])

        # ── VS Input attribute pass-through ───────────────────────────────────
        # VS Output MeshFormat only exposes SV_Position.  All other channels
        # (UV, UV2, Normal, Tangent, BiNormal, Color) are borrowed from the VS
        # Input vertex buffer, which uses the same index buffer and therefore
        # the same vertex ordering as the VS Output buffer.
        #
        # Mapping strategy
        # ─────────────────
        # UV / UV2  →  per-unique-vertex (IndexToDirect).
        #   The table has one row per draw-index; we deduplicate by vertex-index
        #   to build a compact UV array, then use idx_list as the UV-index array.
        #   This matches how export_fbx writes UV.
        #
        # Normal / Tangent / BiNormal / Color  →  per-polygon-vertex (Direct /
        #   IndexToDirect-with-sequential-indices).
        #   We write vs_in_data[attr][i] for face-corner i because the VS Input
        #   table rows are in draw-index order, identical to idx_list order.
        #   This preserves hard-edge (seam) normals correctly.

        ENGINE  = mapper.get("ENGINE",   "unity")
        flip_u  = mapper.get("FLIP_U",  False)
        flip_v  = mapper.get("FLIP_V",  True)

        UV      = mapper.get("UV",       "")
        UV2     = mapper.get("UV2",      "")
        NORMAL  = mapper.get("NORMAL",   "")
        TANGENT = mapper.get("TANGENT",  "")
        BINORM  = mapper.get("BINORMAL", "")
        COLOR   = mapper.get("COLOR",    "")

        vsout_uv      = mapper.get("VSOUT_INCLUDE_VSIN_UV",      True)
        vsout_uv2     = mapper.get("VSOUT_INCLUDE_VSIN_UV2",     True)
        vsout_normal  = mapper.get("VSOUT_INCLUDE_VSIN_NORMAL",  True)
        vsout_tangent = mapper.get("VSOUT_INCLUDE_VSIN_TANGENT", True)
        vsout_binorm  = mapper.get("VSOUT_INCLUDE_VSIN_BINORMAL",True)
        vsout_color   = mapper.get("VSOUT_INCLUDE_VSIN_COLOR",   True)

        # Warn when all pass-through options are disabled
        flags = [vsout_uv, vsout_uv2, vsout_normal, vsout_tangent, vsout_binorm, vsout_color]
        if not any(flags):
            info_list.append("WARNING: ALL VS-In pass-through checkboxes are OFF "
                             "→ open Export Mesh dialog and check them in 'VS Output Extras'")

        layer_uv      = "";  layer_uv_ins  = ""
        layer_uv2     = "";  layer_uv2_ins = ""
        layer_nrm     = "";  layer_nrm_ins = ""
        layer_tan     = "";  layer_tan_ins = ""
        layer_bn      = "";  layer_bn_ins  = ""
        layer_col     = "";  layer_col_ins = ""

        # ── Diagnostic: always report what VS Input data we have ──────────────
        _d = []
        if vs_in_data is None:
            _d.append("qt_table=None")
        else:
            _tmp_idx  = vs_in_data.get("IDX", [])
            _tmp_att  = vs_in_attr_list or set()
            _d.append("qt_rows=%d attrs=[%s]" % (
                len(_tmp_idx), ",".join(sorted(_tmp_att)[:6])))
        info_list.append("vsin_qt: " + "  ".join(_d))

        # ── Read VS Input attributes directly from GPU vertex buffer ──────────
        # This is reliable regardless of which tab (VS In / VS Out) the user
        # has selected in the Mesh Viewer, because the Qt table repopulates with
        # VS Output data in VS Output view mode (Vulkan: _inputN names).
        vsin_raw, vsin_nidxs_gpu = _read_vsin_attrs_from_gpu(
            mapper, info_list, controller)

        # vsin_nidxs: normalized 0-based VS Input vertex index per face corner
        # Used as UV IndexToDirect index array — must come from the VS Input IB,
        # NOT from idx_list (the VS Output expanded sequential indices).
        vsin_nidxs = vsin_nidxs_gpu[:n_fc] if vsin_nidxs_gpu else []
        if len(vsin_nidxs) < n_fc:
            vsin_nidxs.extend([0] * (n_fc - len(vsin_nidxs)))

        # ── Override UV with Qt-table data (RenderDoc decoded the format) ────
        # The Qt mesh-viewer table has per-draw-corner float UV already decoded
        # from whatever GPU format (float16, float32 …).  This is more reliable
        # than our own GPU byte-offset + format guessing in _read_vsin_attrs_from_gpu.
        # The "IDX" column gives raw VS-Input vertex indices matching the draw IB.
        _qt_uv_key = None
        # Search order: mapper UV key first, then common Vulkan locations.
        # For each candidate, verify the data actually looks like UV (float2,
        # values in [0, 10] range, non-zero variation) so we skip normals /
        # tangents / other comp=2 attributes that aren't UV.
        def _uv_candidate_score(key):
            """Return a score ≥1 if key looks like UV, else 0."""
            if not (vs_in_data and vs_in_data.get(key)):
                return 0
            _s = vs_in_data[key]
            if not (_s and hasattr(_s[0], '__len__') and len(_s[0]) >= 2):
                return 0
            _vals = [abs(v) for e in _s[:30] for v in e[:2] if v == v]
            _mx = max(_vals) if _vals else 0
            _nz = sum(1 for v in _vals if v > 0.001)
            if not (0.001 <= _mx <= 10.0 and _nz >= len(_vals) * 0.3):
                return 0
            return _nz + len(set(round(v, 2) for v in _vals))  # higher = more varied

        _qt_uv_key = None
        _best_uv_score = 0
        for _qk in ([UV] if UV else []) + ["_input4", "_input3", "_input2"]:
            _sc = _uv_candidate_score(_qk)
            if _sc > _best_uv_score:
                _best_uv_score = _sc
                _qt_uv_key = _qk
            # Stop early if the mapper's own key scored well — trust it
            if _qt_uv_key == UV and _sc >= 10:
                break

        if vsout_uv and _qt_uv_key:
            try:
                _qt_uv_corn = vs_in_data[_qt_uv_key]   # [u,v] per draw corner
                _qt_idx_raw = vs_in_data.get("IDX", [])
                if _qt_idx_raw and len(_qt_uv_corn) >= n_fc:
                    _qi = [int(float(x)) for x in _qt_idx_raw[:n_fc]]
                    _min_qi = min(_qi) if _qi else 0
                    _uv_map = {}
                    for _fc in range(n_fc):
                        _ni = _qi[_fc] - _min_qi
                        if _ni not in _uv_map:
                            _uv_map[_ni] = list(_qt_uv_corn[_fc][:2])
                    if _uv_map:
                        _max_ni = max(_uv_map.keys())
                        vsin_raw[UV] = [_uv_map.get(_i, [0.0, 0.0])
                                        for _i in range(_max_ni + 1)]
                        # Rebuild corner→vertex index from Qt IDX (consistency)
                        vsin_nidxs = [_qi[fc] - _min_qi for fc in range(n_fc)]
                        info_list.append("UV: Qt-table override (%s score=%d) %d unique/%d corners" % (
                            _qt_uv_key, _best_uv_score, len(_uv_map), n_fc))
            except Exception as _e_qt:
                info_list.append("UV: Qt-table override failed: %s" % str(_e_qt))

        # ── UV2 Qt-table override (second comp=2 key, different from UV0) ─────
        if vsout_uv2 and UV2 and not vsin_raw.get(UV2) and vs_in_data:
            try:
                _uv2_score, _qt_uv2_key = -1, None
                for _qk2 in ([UV2] if UV2 else []) + ["_input3", "_input4", "_input2"]:
                    if _qk2 == _qt_uv_key:
                        continue    # don't re-use the UV0 key
                    _s2 = vs_in_data.get(_qk2)
                    if not _s2: continue
                    if not (hasattr(_s2[0], '__len__') and len(_s2[0]) >= 2): continue
                    _v2 = [abs(v) for e in _s2[:30] for v in e[:2] if v == v]
                    if not _v2 or max(_v2) < 0.001: continue
                    _sc2 = sum(1 for v in _v2 if 0.001 <= v <= 10) + len(set(round(v, 2) for v in _v2))
                    if _sc2 > _uv2_score:
                        _uv2_score  = _sc2
                        _qt_uv2_key = _qk2

                if _qt_uv2_key:
                    _qt_uv2_corn = vs_in_data[_qt_uv2_key]
                    _qt_idx2     = vs_in_data.get("IDX", [])
                    if _qt_idx2 and len(_qt_uv2_corn) >= n_fc:
                        _qi2 = [int(float(x)) for x in _qt_idx2[:n_fc]]
                        _min2 = min(_qi2)
                        _uv2_map = {}
                        for _fc2 in range(n_fc):
                            _ni2 = _qi2[_fc2] - _min2
                            if _ni2 not in _uv2_map:
                                _uv2_map[_ni2] = list(_qt_uv2_corn[_fc2][:2])
                        if _uv2_map:
                            vsin_raw[UV2] = [_uv2_map.get(_i2, [0.0, 0.0])
                                             for _i2 in range(max(_uv2_map) + 1)]
                            info_list.append("UV2: Qt-table (%s score=%d) %d unique" % (
                                _qt_uv2_key, _uv2_score, len(_uv2_map)))
            except Exception as _e_uv2:
                info_list.append("UV2: Qt-table failed: %s" % str(_e_uv2))

        def _xform3(vals):
            if ENGINE != "unreal":
                return list(vals[:3])
            x, y, z = vals[:3]
            return [-x, z, -y]

        def _safe_vert(attr_verts, vi, default):
            """Return vertex data at normalized index vi, or default."""
            return attr_verts[vi] if vi < len(attr_verts) else default

        # ── UV0 (IndexToDirect, per-unique-vertex) ───────────────────────────
        if vsout_uv and UV and vsin_raw.get(UV):
            uv_verts = vsin_raw[UV]
            uvs = [
                str((1.0 - v if flip_u else v) if dim == 0
                    else (1.0 - v if flip_v else v))
                for vals in uv_verts
                for dim, v in enumerate(vals[:2])
            ]
            uvi = ",".join(str(i) for i in vsin_nidxs)
            layer_uv = """
                LayerElementUV: 0 {
                    Version: 101
                    Name: "map1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "IndexToDirect"
                    UV: *%(uvs_num)s {
                        a: %(uvs)s
                    }
                    UVIndex: *%(uvi_num)s {
                        a: %(uvi)s
                    }
                }
            """ % {"uvs": ",".join(uvs), "uvs_num": len(uvs),
                   "uvi": uvi,            "uvi_num": n_fc}
            layer_uv_ins = """
                LayerElement: {
                    Type: "LayerElementUV"
                    TypedIndex: 0
                }
            """
            info_list.append("uv=%s (%d unique)" % (UV, len(uv_verts)))

        # ── UV1 (IndexToDirect, per-unique-vertex) ───────────────────────────
        if vsout_uv2 and UV2 and vsin_raw.get(UV2):
            uv2_verts = vsin_raw[UV2]
            uvs2 = [
                str((1.0 - v if flip_u else v) if dim == 0
                    else (1.0 - v if flip_v else v))
                for vals in uv2_verts
                for dim, v in enumerate(vals[:2])
            ]
            uvi2 = ",".join(str(i) for i in vsin_nidxs)
            layer_uv2 = """
                LayerElementUV: 1 {
                    Version: 101
                    Name: "map2"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "IndexToDirect"
                    UV: *%(uvs_num)s {
                        a: %(uvs)s
                    }
                    UVIndex: *%(uvi_num)s {
                        a: %(uvi)s
                    }
                }
            """ % {"uvs": ",".join(uvs2), "uvs_num": len(uvs2),
                   "uvi": uvi2,            "uvi_num": n_fc}
            layer_uv2_ins = """
                LayerElement: {
                    Type: "LayerElementUV"
                    TypedIndex: 1
                }
            """
            info_list.append("uv2=%s (%d unique)" % (UV2, len(uv2_verts)))

        # ── Normal (ByPolygonVertex Direct, via vertex-index lookup) ─────────
        info_list.append("nrm_check: vsout_normal=%s NORMAL=%r has=%s" % (
            vsout_normal, NORMAL, bool(vsin_raw.get(NORMAL, None))))
        if vsout_normal and NORMAL and vsin_raw.get(NORMAL):
            nrm_verts = vsin_raw[NORMAL]
            nrms = []
            for fc_i in range(n_fc):
                vi = vsin_nidxs[fc_i]
                n  = _xform3(_safe_vert(nrm_verts, vi, [0.0, 0.0, 1.0]))
                nrms.extend(str(x) for x in n)
            layer_nrm = """
                LayerElementNormal: 0 {
                    Version: 101
                    Name: ""
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "Direct"
                    Normals: *%(n)s {
                        a: %(v)s
                    }
                }
            """ % {"n": len(nrms), "v": ",".join(nrms)}
            layer_nrm_ins = """
                LayerElement: {
                    Type: "LayerElementNormal"
                    TypedIndex: 0
                }
            """
            info_list.append("normal=%s (%d corners)" % (NORMAL, n_fc))

        # ── Tangent (ByPolygonVertex Direct) ─────────────────────────────────
        if vsout_tangent and TANGENT and vsin_raw.get(TANGENT):
            tan_verts = vsin_raw[TANGENT]
            tans = []
            for fc_i in range(n_fc):
                vi = vsin_nidxs[fc_i]
                t  = _xform3(_safe_vert(tan_verts, vi, [1.0, 0.0, 0.0]))
                tans.extend(str(x) for x in t)
            layer_tan = """
                LayerElementTangent: 0 {
                    Version: 101
                    Name: "map1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "Direct"
                    Tangents: *%(n)s {
                        a: %(v)s
                    }
                }
            """ % {"n": len(tans), "v": ",".join(tans)}
            layer_tan_ins = """
                LayerElement: {
                    Type: "LayerElementTangent"
                    TypedIndex: 0
                }
            """
            info_list.append("tangent=%s" % TANGENT)

        # ── BiNormal (ByPolygonVertex Direct) ────────────────────────────────
        if vsout_binorm and BINORM and vsin_raw.get(BINORM):
            bn_verts = vsin_raw[BINORM]
            bns = []
            for fc_i in range(n_fc):
                vi = vsin_nidxs[fc_i]
                b  = _xform3(_safe_vert(bn_verts, vi, [0.0, 1.0, 0.0]))
                bns.extend(str(-float(x)) for x in b)
            layer_bn = """
                LayerElementBinormal: 0 {
                    Version: 101
                    Name: "map1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "Direct"
                    Binormals: *%(n)s {
                        a: %(v)s
                    }
                    BinormalsW: *%(wn)s {
                        a: %(w)s
                    }
                }
            """ % {"n":  len(bns), "v": ",".join(bns),
                   "wn": n_fc,     "w": ",".join(["1"] * n_fc)}
            layer_bn_ins = """
                LayerElement: {
                    Type: "LayerElementBinormal"
                    TypedIndex: 0
                }
            """
            info_list.append("binormal=%s" % BINORM)

        # ── Color (ByPolygonVertex IndexToDirect, sequential) ─────────────────
        if vsout_color and COLOR and vsin_raw.get(COLOR):
            col_verts = vsin_raw[COLOR]
            cols = []
            for fc_i in range(n_fc):
                vi = vsin_nidxs[fc_i]
                c  = _safe_vert(col_verts, vi, [1.0, 1.0, 1.0, 1.0])
                cols.extend(str(x) for x in c[:4])
            col_idx = ",".join(str(i) for i in range(n_fc))
            layer_col = """
                LayerElementColor: 0 {
                    Version: 101
                    Name: "colorSet1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "IndexToDirect"
                    Colors: *%(n)s {
                        a: %(v)s
                    }
                    ColorIndex: *%(in_num)s {
                        a: %(idx)s
                    }
                }
            """ % {"n": len(cols), "v": ",".join(cols),
                   "in_num": n_fc,  "idx": col_idx}
            layer_col_ins = """
                LayerElement: {
                    Type: "LayerElementColor"
                    TypedIndex: 0
                }
            """
            info_list.append("color=%s" % COLOR)

        # ── Diagnostic: which FBX layers were actually written ────────────────
        info_list.append("layers: UV=%s UV2=%s Nrm=%s Tan=%s BN=%s Col=%s" % (
            "Y" if layer_uv  else "N",
            "Y" if layer_uv2 else "N",
            "Y" if layer_nrm else "N",
            "Y" if layer_tan else "N",
            "Y" if layer_bn  else "N",
            "Y" if layer_col else "N",
        ))

        # ── Bone weight / SkinDeformer (optional) ────────────────────────────
        _skin_objs = ""
        _skin_cons = ""
        if mapper.get("EXPORT_SKIN", False):
            try:
                _pipe  = controller.GetPipelineState()
                _vb0_d = None
                _vb0_s = 0
                try:
                    _vbs   = _pipe.GetVertexBuffers()
                    if _vbs:
                        _vb0   = _vbs[0]
                        _vb0_d = bytes(controller.GetBufferData(
                            _vb0.resourceId, _vb0.byteOffset, 0))
                        _vb0_s = _vb0.byteStride
                except Exception:
                    pass
                if _vb0_d and _vb0_s:
                    _nv_total = len(vertices) // 3
                    # nat_cum from mapper or estimate from attribute layout
                    _nat = 28   # default fallback
                    _bw, _bi = _scan_bone_data(_vb0_d, _vb0_s, _nv_total, _nat, info_list)
                    if _bw:
                        _skin_objs, _skin_cons = _build_fbx_skin(_bw, _bi, _nv_total)
                        info_list.append("skin: %d bones, %d verts" % (
                            max(max(idxs) for idxs in _bi) + 1, _nv_total))
                    else:
                        info_list.append("skin: no bone data found in VB0")
            except Exception as _se:
                info_list.append("skin error: %s" % str(_se)[:80])

        _mat_objs, _mat_cons = _build_fbx_material(
            os.path.dirname(save_path), save_name)
        ARGS = {
            "model_name":                save_name,
            "vertices":                  ",".join(str(v) for v in vertices),
            "vertices_num":              len(vertices),
            "polygons":                  ",".join(str(p) for p in polygons),
            "polygons_num":              len(polygons),
            "LayerElementNormal":        layer_nrm,
            "LayerElementNormalInsert":  layer_nrm_ins,
            "LayerElementBiNormal":      layer_bn,
            "LayerElementBiNormalInsert":layer_bn_ins,
            "LayerElementTangent":       layer_tan,
            "LayerElementTangentInsert": layer_tan_ins,
            "LayerElementColor":         layer_col,
            "LayerElementColorInsert":   layer_col_ins,
            "LayerElementUV":            layer_uv,
            "LayerElementUVInsert":      layer_uv_ins,
            "LayerElementUV2":           layer_uv2,
            "LayerElementUV2Insert":     layer_uv2_ins,
            "FbxMaterialObjects":        _mat_objs,
            "FbxMaterialConnections":    _mat_cons,
            "FbxSkinObjects":            _skin_objs,
            "FbxSkinConnections":        _skin_cons,
        }
        fbx = FBX_ASCII_TEMPLETE % ARGS
        with open(save_path, "w") as f:
            f.write(dedent(fbx).strip())

    except Exception:
        import traceback
        err_list.append(traceback.format_exc())


# ---------------------------------------------------------------------------
# Texture export helpers
# ---------------------------------------------------------------------------

_FMT_MAP = {
    "PNG": (rd.FileType.PNG, "png"),
    "DDS": (rd.FileType.DDS, "dds"),
    "TGA": (rd.FileType.TGA, "tga"),
    "BMP": (rd.FileType.BMP, "bmp"),
    "HDR": (rd.FileType.HDR, "hdr"),
    "EXR": (rd.FileType.EXR, "exr"),
}


def _export_textures(save_dir, mapper, controller):
    fmt_name    = mapper.get("TEX_FORMAT", "PNG") or "PNG"
    use_default = mapper.get("TEX_DEFAULT_NAME", True)
    fbx_name    = mapper.get("FBX_NAME", "") or ""
    tex_fbx_pfx = mapper.get("TEX_FBX_PREFIX", False)
    if tex_fbx_pfx and fbx_name:
        prefix = fbx_name + "_"
    else:
        prefix = mapper.get("TEX_PREFIX", "") or ""
    infix     = mapper.get("TEX_INFIX",  "") or ""
    suffix    = mapper.get("TEX_SUFFIX", "") or ""
    file_type, ext = _FMT_MAP.get(fmt_name.upper(), (rd.FileType.PNG, "png"))

    textures = controller.GetTextures()
    tex_set  = {t.resourceId for t in textures}

    accesses     = controller.GetDescriptorAccess()
    store_ranges = defaultdict(list)
    for acc in accesses:
        store_ranges[acc.descriptorStore].append(acc)

    bound_ids = set()
    for store_id, acc_list in store_ranges.items():
        if store_id == rd.ResourceId.Null():
            continue
        try:
            ranges = [rd.DescriptorRange(acc) for acc in acc_list]
            for desc in controller.GetDescriptors(store_id, ranges):
                rid = desc.resource
                if rid != rd.ResourceId.Null() and rid in tex_set:
                    bound_ids.add(rid)
        except Exception:
            pass

    if not bound_ids:
        state = controller.GetPipelineState()
        for stage in [rd.ShaderStage.Vertex, rd.ShaderStage.Pixel,
                      rd.ShaderStage.Geometry, rd.ShaderStage.Hull,
                      rd.ShaderStage.Domain, rd.ShaderStage.Compute]:
            try:
                for binding in state.GetReadOnlyResources(stage):
                    for res in binding.resources:
                        rid = res.resourceId
                        if rid != rd.ResourceId.Null() and rid in tex_set:
                            bound_ids.add(rid)
            except Exception:
                pass

    res_names = {}
    try:
        for rdesc in controller.GetResources():
            res_names[rdesc.resourceId] = rdesc.name
    except Exception:
        pass

    saved = []
    for res_id in bound_ids:
        default_name = res_names.get(res_id, "texture_%s" % int(res_id))
        default_name = default_name.replace("/", "_").replace("\\", "_").replace(":", "_")
        stem     = default_name if use_default else "%s%s%s%s" % (prefix, default_name, infix, suffix)
        out_path = os.path.join(save_dir, "%s.%s" % (stem, ext))
        try:
            save_data            = rd.TextureSave()
            save_data.resourceId = res_id
            save_data.destType   = file_type
            save_data.mip        = 0
            save_data.slice.sliceIndex = 0
            controller.SaveTexture(save_data, out_path)
            saved.append(out_path)
        except Exception as e:
            print("Skipped texture %s: %s" % (stem, e))

    return saved


def _export_output_textures(save_dir, mapper, controller):
    """Export render targets (color outputs + depth) bound at the current draw call."""
    fmt_name    = mapper.get("TEX_FORMAT", "PNG") or "PNG"
    fbx_name    = mapper.get("FBX_NAME", "") or ""
    tex_fbx_pfx = mapper.get("TEX_FBX_PREFIX", False)
    prefix      = (fbx_name + "_out_") if tex_fbx_pfx and fbx_name else "out_"
    file_type, ext = _FMT_MAP.get(fmt_name.upper(), (rd.FileType.PNG, "png"))

    textures = controller.GetTextures()
    tex_set  = {t.resourceId for t in textures}

    state     = controller.GetPipelineState()
    bound_ids = {}

    try:
        for i, desc in enumerate(state.GetOutputTargets()):
            rid = desc.resource
            if rid != rd.ResourceId.Null() and rid in tex_set:
                bound_ids[rid] = "color%d" % i
    except Exception:
        pass

    try:
        depth = state.GetDepthTarget()
        if depth and depth.resource != rd.ResourceId.Null() and depth.resource in tex_set:
            bound_ids[depth.resource] = "depth"
    except Exception:
        pass

    saved = []
    for res_id, label in bound_ids.items():
        name     = "%s%s.%s" % (prefix, label, ext)
        out_path = os.path.join(save_dir, name)
        try:
            save_data            = rd.TextureSave()
            save_data.resourceId = res_id
            save_data.destType   = file_type
            save_data.mip        = 0
            save_data.slice.sliceIndex = 0
            controller.SaveTexture(save_data, out_path)
            saved.append(out_path)
        except Exception as e:
            print("Skipped output texture %s: %s" % (label, e))

    return saved


def _tex_invoke(save_dir, mapper, out_list, controller):
    out_list.extend(_export_textures(save_dir, mapper, controller))


def _tex_output_invoke(save_dir, mapper, out_list, controller):
    out_list.extend(_export_output_textures(save_dir, mapper, controller))


# ---------------------------------------------------------------------------
# Shader export helpers
# ---------------------------------------------------------------------------

_SHADER_EXT = {
    0: "bin",    # Unknown
    1: "dxbc",   # DXBC
    2: "glsl",   # GLSL
    3: "spv",    # SPIRV
    4: "spvasm", # SPIRVAsm
    5: "hlsl",   # HLSL
    6: "spv",    # OpenGLSPIRV
    7: "spv",    # VulkanSPIRV
    8: "dxil",   # DXIL
}

_STAGE_MAP = {
    "VS": rd.ShaderStage.Vertex,
    "PS": rd.ShaderStage.Pixel,
    "GS": rd.ShaderStage.Geometry,
    "HS": rd.ShaderStage.Hull,
    "DS": rd.ShaderStage.Domain,
    "CS": rd.ShaderStage.Compute,
}


def _export_shaders(save_dir, mapper, controller):
    import traceback
    stages_enabled = mapper.get("SHADER_STAGES", {})
    shader_fmt     = mapper.get("SHADER_FMT", "Binary")
    use_disasm     = (shader_fmt == "Disasm (txt)")
    fbx_name       = mapper.get("FBX_NAME", "") or ""
    shader_fbx_pfx = mapper.get("SHADER_FBX_PREFIX", True)
    name_prefix    = (fbx_name + "_") if shader_fbx_pfx and fbx_name else ""
    state          = controller.GetPipelineState()
    pipeline       = state.GetGraphicsPipelineObject()

    saved  = []
    errors = []

    for stage_key, stage in _STAGE_MAP.items():
        if not stages_enabled.get(stage_key, False):
            continue
        try:
            refl = state.GetShaderReflection(stage)
            if refl is None:
                continue

            entry_name = str(state.GetShaderEntryPoint(stage))
            res_id     = state.GetShader(stage)
            if res_id == rd.ResourceId.Null():
                continue

            enc_val  = int(refl.encoding)
            base_ext = _SHADER_EXT.get(enc_val, "bin")

            if use_disasm:
                pipe     = state.GetComputePipelineObject() if stage == rd.ShaderStage.Compute else pipeline
                text     = controller.DisassembleShader(pipe, refl, "")
                if not text:
                    errors.append("%s: disassembly returned empty" % stage_key)
                    continue
                text_str = text if isinstance(text, str) else text.decode("utf-8", errors="replace")
                name     = "%s%s_%s.%s.txt" % (name_prefix, stage_key, entry_name, base_ext)
                out_path = os.path.join(save_dir, name)
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(text_str)
            else:
                raw = bytes(refl.rawBytes)
                if not raw:
                    errors.append("%s: rawBytes is empty" % stage_key)
                    continue
                name     = "%s%s_%s.%s" % (name_prefix, stage_key, entry_name, base_ext)
                out_path = os.path.join(save_dir, name)
                with open(out_path, "wb") as f:
                    f.write(raw)

            saved.append(out_path)
        except Exception:
            errors.append("%s: %s" % (stage_key, traceback.format_exc()))

    return saved, errors


def _shader_invoke(save_dir, mapper, out_list, err_list, controller):
    saved, errors = _export_shaders(save_dir, mapper, controller)
    out_list.extend(saved)
    err_list.extend(errors)


# ---------------------------------------------------------------------------
# Export orchestration helpers
# ---------------------------------------------------------------------------

def _build_settings_mapper(settings):
    """Reconstruct a mapper dict from a QSettings object (for Quick Export)."""
    mapper = {}
    for key, _ in QueryDialog.edit_config:
        mapper[key] = settings.value(key, "")

    mapper["ENGINE"]                 = settings.value("Engine",               "unity")
    mapper["MESH_MODE"]              = settings.value("MeshMode",             "VS Input")
    mapper["EXPORT_FORMAT"]          = settings.value("ExportFormat",         "FBX")
    mapper["FLIP_U"]                 = settings.value("FlipU",  "false") == "true"
    mapper["FLIP_V"]                 = settings.value("FlipV",  "true")  == "true"
    mapper["EXPORT_TEXTURES"]        = settings.value("ExportTextures",       "true") == "true"
    mapper["EXPORT_OUTPUT_TEXTURES"] = settings.value("ExportOutputTextures", "true") == "true"
    mapper["TEX_FORMAT"]             = settings.value("TexFormat",            "PNG")
    mapper["TEX_DEFAULT_NAME"]       = settings.value("TexDefaultName",       "true") == "true"
    mapper["TEX_PREFIX"]             = settings.value("TexPrefix",            "")
    mapper["TEX_INFIX"]              = settings.value("TexInfix",             "")
    mapper["TEX_SUFFIX"]             = settings.value("TexSuffix",            "")
    mapper["TEX_FBX_PREFIX"]         = settings.value("TexFbxPrefix",         "true") == "true"
    mapper["EXPORT_SHADERS"]         = settings.value("ExportShaders",        "true") == "true"
    mapper["SHADER_FMT"]             = settings.value("ShaderFmt",            "Binary")
    mapper["SHADER_FBX_PREFIX"]      = settings.value("ShaderFbxPrefix",      "true") == "true"
    mapper["SHADER_STAGES"]          = {
        k: settings.value("ShaderStage_%s" % k,
                          "true" if QueryDialog.STAGE_DEFAULTS.get(k, False) else "false") == "true"
        for k in QueryDialog.STAGE_KEYS
    }
    mapper["VSOUT_INCLUDE_VSIN_UV"]      = settings.value("VSOutIncludeVSInUV",      "true") == "true"
    mapper["VSOUT_INCLUDE_VSIN_UV2"]     = settings.value("VSOutIncludeVSInUV2",     "true") == "true"
    mapper["VSOUT_INCLUDE_VSIN_NORMAL"]  = settings.value("VSOutIncludeVSInNormal",  "true") == "true"
    mapper["VSOUT_INCLUDE_VSIN_TANGENT"] = settings.value("VSOutIncludeVSInTangent", "true") == "true"
    mapper["VSOUT_INCLUDE_VSIN_BINORMAL"]= settings.value("VSOutIncludeVSInBinormal","true") == "true"
    mapper["VSOUT_INCLUDE_VSIN_COLOR"]   = settings.value("VSOutIncludeVSInColor",   "true") == "true"
    mapper["BAKE_WORLD_SPACE"]           = settings.value("BakeWorldSpace",           "false") == "true"
    mapper["EXPORT_SKIN"]                = settings.value("ExportSkin",                "false") == "true"
    return mapper


def _run_mesh_export(save_path, mapper, data, attr_list, pyrenderdoc, fbx_info, fbx_errors):
    """Dispatch to FBX or OBJ exporter based on EXPORT_FORMAT in *mapper*."""
    export_format = mapper.get("EXPORT_FORMAT", "FBX")
    mesh_mode     = mapper.get("MESH_MODE", "VS Input")

    if mesh_mode == "VS Input":
        if export_format == "OBJ":
            pyrenderdoc.Replay().BlockInvoke(
                partial(export_obj, save_path, mapper, data, attr_list)
            )
        else:
            pyrenderdoc.Replay().BlockInvoke(
                partial(export_fbx, save_path, mapper, data, attr_list)
            )
    else:
        # data / attr_list here are the VS Input attributes (UV, Normal, ...)
        # collected by the caller for pass-through into VS Output export.
        pyrenderdoc.Replay().BlockInvoke(
            partial(_export_vsout_fbx, save_path, mapper, fbx_info, fbx_errors,
                    data, attr_list)
        )


def _run_secondary_exports(save_dir, mapper, pyrenderdoc):
    """Export textures and shaders if requested. Returns (tex_in, tex_out, shaders, shader_errs)."""
    tex_results        = []
    tex_output_results = []
    shader_results     = []
    shader_errors      = []

    if mapper.get("EXPORT_TEXTURES", False):
        pyrenderdoc.Replay().BlockInvoke(
            partial(_tex_invoke, save_dir, mapper, tex_results)
        )

    if mapper.get("EXPORT_OUTPUT_TEXTURES", False):
        pyrenderdoc.Replay().BlockInvoke(
            partial(_tex_output_invoke, save_dir, mapper, tex_output_results)
        )

    if mapper.get("EXPORT_SHADERS", False):
        pyrenderdoc.Replay().BlockInvoke(
            partial(_shader_invoke, save_dir, mapper, shader_results, shader_errors)
        )

    return tex_results, tex_output_results, shader_results, shader_errors


def _build_success_msg(save_path, mapper, fbx_info,
                       tex_results, tex_output_results,
                       shader_results, shader_errors):
    """Build the text shown in the success dialog."""
    export_format = mapper.get("EXPORT_FORMAT", "FBX")
    msg = "%s Output Successful!" % export_format

    if fbx_info:
        msg += "\n\nVS Out info:\n" + "\n".join(fbx_info)

    if tex_results:
        msg += "\n\nInput Textures saved (%d):\n" % len(tex_results)
        msg += "\n".join(os.path.basename(p) for p in tex_results[:20])
        if len(tex_results) > 20:
            msg += "\n... and %d more" % (len(tex_results) - 20)
    elif mapper.get("EXPORT_TEXTURES", False):
        msg += "\n\nNo bound input textures found."

    if tex_output_results:
        msg += "\n\nOutput Textures saved (%d):\n" % len(tex_output_results)
        msg += "\n".join(os.path.basename(p) for p in tex_output_results)

    if shader_results:
        msg += "\n\nShaders saved (%d):\n" % len(shader_results)
        msg += "\n".join(os.path.basename(p) for p in shader_results)
        msg += "\n[fmt=%s]" % mapper.get("SHADER_FMT", "?")

    if shader_errors:
        msg += "\n\nShader export errors:\n" + "\n".join(shader_errors[:5])

    if mapper.get("EXPORT_SHADERS", False) and not shader_results and not shader_errors:
        stages  = mapper.get("SHADER_STAGES", {})
        enabled = [k for k, v in stages.items() if v]
        msg += "\n\nShader export: no stages enabled (checked: %s)" % (enabled or "none")

    return msg


# ---------------------------------------------------------------------------
# Error decorator
# ---------------------------------------------------------------------------

def error_log(func):
    def wrapper(pyrenderdoc, data):
        manager = pyrenderdoc.Extensions()
        try:
            func(pyrenderdoc, data)
        except Exception:
            import traceback
            manager.MessageDialog("Export Failed\n%s" % traceback.format_exc(), "Error!")

    return wrapper



# ---------------------------------------------------------------------------
# Batch (multi-draw-call) merge helpers
# ---------------------------------------------------------------------------

def _do_batch_merge(save_path, mapper, event_ids, pyrenderdoc,
                    info_list, err_list, main_window):
    """Export *event_ids* (VS Output) and write a combined FBX.

    For each event the replay is advanced to that EID, VS Output data is
    collected, and vertices/polygons are accumulated with index offsets so
    all draw calls end up in a single Geometry node.
    """
    from functools import partial as _partial

    save_name = os.path.basename(os.path.splitext(save_path)[0])

    # Accumulate across all events
    all_vertices   = []
    all_polygons   = []
    vert_offset    = 0
    layer_uv       = "";  layer_uv_ins   = ""
    layer_uv2      = "";  layer_uv2_ins  = ""
    layer_nrm      = "";  layer_nrm_ins  = ""
    layer_tan      = "";  layer_tan_ins  = ""
    layer_bn       = "";  layer_bn_ins   = ""
    layer_col      = "";  layer_col_ins  = ""

    # Per-layer accumulation lists (strings from each event)
    _uvs_acc   = [];  _uvi_acc   = []
    _uv2s_acc  = [];  _uv2i_acc  = []
    _nrms_acc  = []
    _tans_acc  = []
    _bns_acc   = []
    _cols_acc  = [];  _coli_acc  = []

    for _eid in event_ids:
        _per_info   = []
        _per_errors = []

        # Switch replay to this event
        try:
            pyrenderdoc.Replay().BlockInvoke(
                lambda ctrl, eid=_eid: ctrl.SetFrameEvent(eid, True)
            )
        except Exception as _e:
            info_list.append("batch: EID %d skip (SetFrameEvent: %s)" % (_eid, _e))
            continue

        # Collect VS Input pass-through data (UV/Normal etc.)
        _vsin_data, _vsin_attrs = _collect_mesh_data(main_window)

        # Temporary file to capture per-event FBX (we parse it back)
        import tempfile as _tf
        _tmp = _tf.mktemp(suffix=".fbx")

        pyrenderdoc.Replay().BlockInvoke(
            _partial(_export_vsout_fbx, _tmp, mapper, _per_info, _per_errors,
                     _vsin_data, _vsin_attrs)
        )

        if _per_errors:
            info_list.append("batch: EID %d errors: %s" % (_eid, _per_errors[0][:80]))
            continue
        if not os.path.exists(_tmp):
            info_list.append("batch: EID %d produced no file" % _eid)
            continue

        # Parse the temporary FBX to extract vertices and polygons
        try:
            with open(_tmp, "r") as _fh:
                _txt = _fh.read()
            import re as _re

            def _extract(pattern, text):
                m = _re.search(pattern, text, _re.DOTALL)
                return m.group(1).strip() if m else ""

            _verts_str = _extract(r"Vertices:\s*\*\d+\s*\{[^}]*a:\s*([^}]+)\}", _txt)
            _polys_str = _extract(r"PolygonVertexIndex:\s*\*\d+\s*\{[^}]*a:\s*([^}]+)\}", _txt)

            if not _verts_str or not _polys_str:
                info_list.append("batch: EID %d empty geometry" % _eid)
                continue

            _verts = [float(v) for v in _verts_str.split(",") if v.strip()]
            _polys = [int(v)   for v in _polys_str.split(",") if v.strip()]
            _nv    = len(_verts) // 3

            # Offset polygon indices
            def _offset_idx(idx):
                return (~(~idx + vert_offset)) if idx < 0 else idx + vert_offset

            all_vertices.extend(_verts)
            all_polygons.extend(_offset_idx(p) for p in _polys)
            vert_offset += _nv

            info_list.append("batch: EID %d → %d verts %d faces" % (
                _eid, _nv, len(_polys) // 3))

            # Accumulate UV, Normal etc. layer data (concatenate)
            # UV
            _uv_s = _extract(r'LayerElementUV:\s*0\s*\{.*?UV:\s*\*\d+\s*\{[^}]*a:\s*([^}]+)\}', _txt)
            _ui_s = _extract(r'LayerElementUV:\s*0\s*\{.*?UVIndex:\s*\*\d+\s*\{[^}]*a:\s*([^}]+)\}', _txt)
            if _uv_s and _ui_s:
                _uvs_acc.append(_uv_s.strip())
                _ui_vals = [str(int(v) + (len(_uvi_acc[0].split(",")) // 2
                                          if _uvi_acc else 0))
                            for v in _ui_s.split(",") if v.strip()]
                # Simpler: just offset UV indices by current UV vertex count
                _cur_uv_verts = sum(s.count(",") + 1 for s in _uvs_acc[:-1]) // 2
                _ui_off = [str(int(v) + _cur_uv_verts) for v in _ui_s.split(",") if v.strip()]
                _uvi_acc.append(",".join(_ui_off))

            # Normal
            _nrm_s = _extract(r'LayerElementNormal:\s*0\s*\{.*?Normals:\s*\*\d+\s*\{[^}]*a:\s*([^}]+)\}', _txt)
            if _nrm_s: _nrms_acc.append(_nrm_s.strip())

        except Exception as _pe:
            info_list.append("batch: EID %d parse error: %s" % (_eid, str(_pe)[:60]))
        finally:
            try: os.remove(_tmp)
            except OSError: pass

    if not all_vertices:
        err_list.append("Batch merge: no geometry collected from any event")
        return

    # Build combined UV layer if available
    if _uvs_acc:
        _all_uvs = ",".join(_uvs_acc)
        _all_uvi = ",".join(_uvi_acc)
        layer_uv = """
            LayerElementUV: 0 {
                Version: 101
                Name: "map1"
                MappingInformationType: "ByPolygonVertex"
                ReferenceInformationType: "IndexToDirect"
                UV: *%(n)s { a: %(v)s }
                UVIndex: *%(in)s { a: %(i)s }
            }""" % {"n":  _all_uvs.count(",") + 1, "v": _all_uvs,
                    "in": _all_uvi.count(",") + 1, "i": _all_uvi}
        layer_uv_ins = """
            LayerElement: { Type: "LayerElementUV" TypedIndex: 0 }"""

    # Build combined Normal layer if available
    if _nrms_acc:
        _all_nrms = ",".join(_nrms_acc)
        layer_nrm = """
            LayerElementNormal: 0 {
                Version: 101
                Name: ""
                MappingInformationType: "ByPolygonVertex"
                ReferenceInformationType: "Direct"
                Normals: *%(n)s { a: %(v)s }
            }""" % {"n": _all_nrms.count(",") + 1, "v": _all_nrms}
        layer_nrm_ins = """
            LayerElement: { Type: "LayerElementNormal" TypedIndex: 0 }"""

    _mat_objs, _mat_cons = _build_fbx_material(os.path.dirname(save_path), save_name)

    ARGS = {
        "model_name":                save_name,
        "vertices":                  ",".join(str(v) for v in all_vertices),
        "vertices_num":              len(all_vertices),
        "polygons":                  ",".join(str(p) for p in all_polygons),
        "polygons_num":              len(all_polygons),
        "LayerElementNormal":        layer_nrm,
        "LayerElementNormalInsert":  layer_nrm_ins,
        "LayerElementBiNormal":      layer_bn,
        "LayerElementBiNormalInsert":layer_bn_ins,
        "LayerElementTangent":       layer_tan,
        "LayerElementTangentInsert": layer_tan_ins,
        "LayerElementColor":         layer_col,
        "LayerElementColorInsert":   layer_col_ins,
        "LayerElementUV":            layer_uv,
        "LayerElementUVInsert":      layer_uv_ins,
        "LayerElementUV2":           layer_uv2,
        "LayerElementUV2Insert":     layer_uv2_ins,
        "FbxMaterialObjects":        _mat_objs,
        "FbxMaterialConnections":    _mat_cons,
        "FbxSkinObjects":            "",
        "FbxSkinConnections":        "",
    }
    fbx = FBX_ASCII_TEMPLETE % ARGS
    with open(save_path, "w") as _fh:
        _fh.write(dedent(fbx).strip())
    info_list.append("batch: merged %d events → %d total verts" % (
        len(event_ids), len(all_vertices) // 3))


# ---------------------------------------------------------------------------
# Main export entry points
# ---------------------------------------------------------------------------

@error_log
def prepare_export(pyrenderdoc, data):
    """Open the Export Options dialog then perform the full export."""
    manager = pyrenderdoc.Extensions()
    if not pyrenderdoc.HasMeshPreview():
        manager.ErrorDialog("No preview mesh!", "Error")
        return

    # Pre-scan available vertex attributes so the dialog can display / auto-fill them
    main_window     = pyrenderdoc.GetMainWindow().Widget()
    available_attrs = _scan_available_attrs(main_window)

    mqt    = manager.GetMiniQtHelper()
    dialog = QueryDialog(mqt, available_attrs=available_attrs)
    if not mqt.ShowWidgetAsDialog(dialog.init_ui()):
        return

    mesh_mode     = dialog.mapper.get("MESH_MODE", "VS Input") or "VS Input"
    export_format = dialog.mapper.get("EXPORT_FORMAT", "FBX")

    # Choose file extension based on selected format
    if export_format == "OBJ":
        save_path = manager.SaveFileName("Save OBJ File", "", "*.obj")
    else:
        save_path = manager.SaveFileName("Save FBX File", "", "*.fbx")
    if not save_path:
        return

    save_dir = os.path.dirname(save_path)
    fbx_name = os.path.basename(os.path.splitext(save_path)[0])
    dialog.mapper["FBX_NAME"] = fbx_name
    current = time.time()

    fbx_info   = []
    fbx_errors = []

    # ── Detect multi-draw-call batch mode ────────────────────────────────────
    # If the user selected >1 event in the Event Browser, offer to merge them.
    _selected_eids = []
    try:
        _sel_evts = pyrenderdoc.GetSelectedEvents()
        if _sel_evts and len(_sel_evts) > 1:
            _selected_eids = [int(e) for e in _sel_evts]
    except Exception:
        pass

    if len(_selected_eids) > 1 and mesh_mode == "VS Output":
        # Ask user before running batch
        _batch_msg = ("检测到 %d 个选中的 draw call。\n合并导出为单个 FBX？\n\n"
                      "EID: %s …" % (
                          len(_selected_eids),
                          ", ".join(str(e) for e in _selected_eids[:8])))
        if manager.QuestionDialog(_batch_msg, "Batch Export"):
            _do_batch_merge(save_path, dialog.mapper, _selected_eids,
                            pyrenderdoc, fbx_info, fbx_errors, main_window)
            if fbx_errors:
                manager.ErrorDialog(
                    "Batch export failed:\n" + "\n".join(fbx_errors), "Error")
                return
            tex_in, tex_out, shaders, shader_errs = _run_secondary_exports(
                save_dir, dialog.mapper, pyrenderdoc)
            if os.path.exists(save_path):
                msg = _build_success_msg(save_path, dialog.mapper, fbx_info,
                                         tex_in, tex_out, shaders, shader_errs)
                os.startfile(save_dir)
                manager.MessageDialog(msg, "Done!")
            return

    def _add_input_aliases(data, attr_list):
        """Add _inputN ↔ ATTRIBUTE{N} aliases so both naming conventions work.

        Vulkan-based RenderDoc captures use location-based names (_input0,
        _input1, …) in the Qt Mesh Viewer table.  Unreal Engine presets
        reference them as ATTRIBUTE0, ATTRIBUTE1, etc.  This helper creates
        bidirectional aliases so VS-Input export finds data regardless of
        which convention the mapper uses.

        Also adds common semantic-name fallbacks so Unity (POSITION, NORMAL,
        TEXCOORD0 …) and Godot (VERTEX, UV …) presets work with Vulkan
        captures even though the table only shows _inputN columns.
        """
        if data is None:
            return data, attr_list
        added = {}
        for k in list(data.keys()):
            if k.startswith("_input"):
                try:
                    n     = int(k[len("_input"):])
                    alias = "ATTRIBUTE%d" % n
                    if alias not in data:
                        added[alias] = data[k]
                except ValueError:
                    pass
            elif k.startswith("ATTRIBUTE"):
                try:
                    n     = int(k[len("ATTRIBUTE"):])
                    alias = "_input%d" % n
                    if alias not in data:
                        added[alias] = data[k]
                except ValueError:
                    pass

        # ── Semantic-name fallbacks for Unity / Godot / D3D presets ──────
        # Vulkan captures only expose _inputN / ATTRIBUTE{N} names.  When the
        # mapper uses semantic names (POSITION, NORMAL, TEXCOORD0 …), look
        # for them in the location-ordered data.  Location 0 is always
        # Position, 1 = Tangent, 2 = Normal in Unreal's Vulkan layout.
        _SEM_FALLBACKS = [
            ("POSITION",  ["_input0", "ATTRIBUTE0"]),
            ("VERTEX",    ["_input0", "ATTRIBUTE0"]),   # Godot
            ("SV_Position",["_input0","ATTRIBUTE0"]),
            ("NORMAL",    ["_input2", "ATTRIBUTE2"]),
            ("TANGENT",   ["_input1", "ATTRIBUTE1"]),
            ("BINORMAL",  ["_input3", "ATTRIBUTE3"]),
            ("TEXCOORD0", ["_input3", "ATTRIBUTE3", "_input4", "ATTRIBUTE4"]),
            ("TEXCOORD1", ["_input4", "ATTRIBUTE4", "_input5", "ATTRIBUTE5"]),
            ("UV",        ["_input3", "ATTRIBUTE3", "_input4", "ATTRIBUTE4"]),
            ("UV2",       ["_input4", "ATTRIBUTE4", "_input5", "ATTRIBUTE5"]),
            ("COLOR",     ["_input5", "ATTRIBUTE5", "_input6", "ATTRIBUTE6"]),
            ("COLOR0",    ["_input5", "ATTRIBUTE5", "_input6", "ATTRIBUTE6"]),
        ]
        _all_data = dict(data)
        _all_data.update(added)
        for _sem, _cands in _SEM_FALLBACKS:
            if _sem in _all_data:
                continue   # already exists
            for _c in _cands:
                if _c in _all_data:
                    added[_sem] = _all_data[_c]
                    _all_data[_sem] = _all_data[_c]
                    break
        if added:
            data.update(added)
            if attr_list is not None:
                attr_list = set(attr_list) | set(added.keys())
        return data, attr_list

    if mesh_mode == "VS Input":
        data, attr_list = _collect_mesh_data(main_window)
        if data is None:
            manager.ErrorDialog(
                "Mesh data table not found for VS Input mode.",
                "Error",
            )
            return
        data, attr_list = _add_input_aliases(data, attr_list)
        print("elapsed time unpack: %s" % (time.time() - current))
        _run_mesh_export(save_path, dialog.mapper, data, attr_list,
                         pyrenderdoc, fbx_info, fbx_errors)
    else:
        # VS Output: also read VS Input table for attribute pass-through
        need_vsin = any(dialog.mapper.get(k, True) for k in (
            "VSOUT_INCLUDE_VSIN_UV", "VSOUT_INCLUDE_VSIN_UV2",
            "VSOUT_INCLUDE_VSIN_NORMAL", "VSOUT_INCLUDE_VSIN_TANGENT",
            "VSOUT_INCLUDE_VSIN_BINORMAL", "VSOUT_INCLUDE_VSIN_COLOR",
        ))
        if need_vsin:
            vs_in_data, vs_in_attr_list = _collect_mesh_data(main_window)
        else:
            vs_in_data, vs_in_attr_list = None, None
        _run_mesh_export(save_path, dialog.mapper, vs_in_data, vs_in_attr_list,
                         pyrenderdoc, fbx_info, fbx_errors)
        if fbx_errors:
            manager.ErrorDialog(
                "VS Output export failed:\n" + "\n".join(fbx_errors), "Error"
            )
            return

    tex_in, tex_out, shaders, shader_errs = _run_secondary_exports(
        save_dir, dialog.mapper, pyrenderdoc
    )

    if os.path.exists(save_path):
        msg = _build_success_msg(save_path, dialog.mapper, fbx_info,
                                 tex_in, tex_out, shaders, shader_errs)
        os.startfile(save_dir)
        manager.MessageDialog(msg, "Done!")


@error_log
def prepare_quick_export(pyrenderdoc, data):
    """Export using last saved settings — no dialog is shown.

    The save-file dialog is still presented so the user can choose where to
    write the output, but all export options are read from the stored
    QSettings (same INI that the full dialog uses), making repeat exports
    effortless.
    """
    manager = pyrenderdoc.Extensions()
    if not pyrenderdoc.HasMeshPreview():
        manager.ErrorDialog("No preview mesh!", "Error")
        return

    # Load last-used settings
    settings_path = os.path.join(tempfile.gettempdir(), "RenderDoc_QueryDialog.ini")
    settings      = QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat)
    mapper        = _build_settings_mapper(settings)

    export_format = mapper.get("EXPORT_FORMAT", "FBX")
    if export_format == "OBJ":
        save_path = manager.SaveFileName("Quick Export — Save OBJ File", "", "*.obj")
    else:
        save_path = manager.SaveFileName("Quick Export — Save FBX File", "", "*.fbx")
    if not save_path:
        return

    save_dir = os.path.dirname(save_path)
    fbx_name = os.path.basename(os.path.splitext(save_path)[0])
    mapper["FBX_NAME"] = fbx_name

    main_window = pyrenderdoc.GetMainWindow().Widget()
    mesh_mode   = mapper.get("MESH_MODE", "VS Input")
    fbx_info    = []
    fbx_errors  = []

    if mesh_mode == "VS Input":
        data, attr_list = _collect_mesh_data(main_window)
        if data is None:
            manager.ErrorDialog("Mesh data table not found.", "Error")
            return
        _run_mesh_export(save_path, mapper, data, attr_list,
                         pyrenderdoc, fbx_info, fbx_errors)
    else:
        need_vsin = any(mapper.get(k, True) for k in (
            "VSOUT_INCLUDE_VSIN_UV", "VSOUT_INCLUDE_VSIN_UV2",
            "VSOUT_INCLUDE_VSIN_NORMAL", "VSOUT_INCLUDE_VSIN_TANGENT",
            "VSOUT_INCLUDE_VSIN_BINORMAL", "VSOUT_INCLUDE_VSIN_COLOR",
        ))
        if need_vsin:
            vs_in_data, vs_in_attr_list = _collect_mesh_data(main_window)
            vs_in_data, vs_in_attr_list = _add_input_aliases(vs_in_data, vs_in_attr_list)
        else:
            vs_in_data, vs_in_attr_list = None, None
        _run_mesh_export(save_path, mapper, vs_in_data, vs_in_attr_list,
                         pyrenderdoc, fbx_info, fbx_errors)
        if fbx_errors:
            manager.ErrorDialog(
                "VS Output export failed:\n" + "\n".join(fbx_errors), "Error"
            )
            return

    tex_in, tex_out, shaders, shader_errs = _run_secondary_exports(
        save_dir, mapper, pyrenderdoc
    )

    if os.path.exists(save_path):
        msg = _build_success_msg(save_path, mapper, fbx_info,
                                 tex_in, tex_out, shaders, shader_errs)
        os.startfile(save_dir)
        manager.MessageDialog(msg, "Quick Export Done!")


# ---------------------------------------------------------------------------
# Extension registration
# ---------------------------------------------------------------------------

def register(version, pyrenderdoc):
    print("Registering FBX/OBJ Mesh Exporter extension for RenderDoc {}".format(version))
    ext = pyrenderdoc.Extensions()
    ext.RegisterPanelMenu(
        qrenderdoc.PanelMenu.MeshPreview,
        ["Export Mesh"],
        prepare_export,
    )
    ext.RegisterPanelMenu(
        qrenderdoc.PanelMenu.MeshPreview,
        ["Quick Export (last settings)"],
        prepare_quick_export,
    )


def unregister():
    print("Unregistering FBX/OBJ Mesh Exporter extension")


# # NOTE for reload plugin
# import subprocess
# import qrenderdoc
# location = r"E:\repo\renderdoc2fbx\install.bat"
# subprocess.call(["cmd","/c",location],shell=True)
# extension = pyrenderdoc.Extensions()
# extension.LoadExtension("exporter.fbx")
