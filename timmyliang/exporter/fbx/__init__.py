# -*- coding: utf-8 -*-
"""
FBX Exporter
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
from textwrap import dedent
from functools import partial
from collections import defaultdict

from PySide2 import QtWidgets, QtCore

import qrenderdoc
import renderdoc as rd

from .query_dialog import QueryDialog
from .progress_dialog import MProgressDialog

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
    }

    ; Object connections
    ;------------------------------------------------------------------

    Connections:  {
        
        ;Model::pCube1, Model::RootNode
        C: "OO",2035615390896,0
        
        ;Geometry::, Model::pCube1
        C: "OO",2035541511296,2035615390896

    }

    """


def export_fbx(save_path, mapper, data, attr_list, controller):

    if not data:
        # manager.ErrorDialog("Current Draw Call lack of Vertex. ", "Error")
        return

    save_name = os.path.basename(os.path.splitext(save_path)[0])

    # We'll decode the first three indices making up a triangle
    idx_dict = data["IDX"]
    value_dict = defaultdict(list)
    vertex_data = defaultdict(dict)

    for i, idx in enumerate(idx_dict):
        for attr in attr_list:
            value = data[attr][i]
            value_dict[attr].append(value)
            if idx not in vertex_data[attr]:
                vertex_data[attr][idx] = value

    ARGS = {
        "model_name": save_name,
        "LayerElementNormal": "",
        "LayerElementNormalInsert": "",
        "LayerElementBiNormal": "",
        "LayerElementBiNormalInsert": "",
        "LayerElementTangent": "",
        "LayerElementTangentInsert": "",
        "LayerElementColor": "",
        "LayerElementColorInsert": "",
        "LayerElementUV": "",
        "LayerElementUVInsert": "",
        "LayerElementUV2": "",
        "LayerElementUV2Insert": "",
    }

    POSITION = mapper.get("POSITION")
    NORMAL = mapper.get("NORMAL")
    BINORMAL = mapper.get("BINORMAL")
    TANGENT = mapper.get("TANGENT")
    COLOR = mapper.get("COLOR")
    UV = mapper.get("UV")
    UV2 = mapper.get("UV2")
    ENGINE = mapper.get("ENGINE")

    min_poly = min(idx_dict)
    idx_list = [idx - min_poly for idx in idx_dict]
    # idx_data = ",".join([str(idx) for idx in idx_list])
    idx_len = len(idx_list)

    def transform_rx_neg90(values):
        x, y, z = values[:3]
        return [x, z, -y]

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
        # The Unreal-space export transform includes a reflection, which already
        # flips handedness. Keep the original triangle corner order so faces
        # stay outward after the coordinate conversion.
        return list(values)

    class ProcessHandler(object):
        def run(self):
            curr = time.time()
            for name, func in inspect.getmembers(self, inspect.isroutine):
                if name.startswith("run_"):
                    func()
            print("elapsed time template: %s" % (time.time() - curr))

        def run_vertices(self):
            transformed_vertices = [
                transform_unreal_vector(values)
                for idx, values in sorted(vertex_data[POSITION].items())
            ]
            vertices = [str(v) for values in transformed_vertices for v in values]
            ARGS["vertices"] = ",".join(vertices)
            ARGS["vertices_num"] = len(vertices)

        def run_polygons(self):
            polygon_indices = reorder_triangle_corners(idx_list)
            polygons = [
                str(idx ^ -1 if i % 3 == 2 else idx)
                for i, idx in enumerate(polygon_indices)
            ]
            ARGS["polygons"] = ",".join(polygons)
            ARGS["polygons_num"] = len(polygons)

        def run_normals(self):
            if not vertex_data.get(NORMAL):
                return

            # NOTE FBX_ASCII only support 3 dimension
            normal_values = reorder_triangle_corners(value_dict[NORMAL])
            transformed_normals = [transform_unreal_vector(values) for values in normal_values]
            normals = [str(v) for values in transformed_normals for v in values]

            ARGS[
                "LayerElementNormal"
            ] = """
                LayerElementNormal: 0 {
                    Version: 101
                    Name: ""
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "Direct"
                    Normals: *%(normals_num)s {
                        a: %(normals)s
                    } 
                }
            """ % {
                "normals": ",".join(normals),
                "normals_num": len(normals),
            }
            ARGS[
                "LayerElementNormalInsert"
            ] = """
                LayerElement:  {
                        Type: "LayerElementNormal"
                    TypedIndex: 0
                }
            """

        def run_binormals(self):
            if not vertex_data.get(BINORMAL):
                return
            # NOTE FBX_ASCII only support 3 dimension
            transformed_binormals = [transform_unreal_vector(values) for values in value_dict[BINORMAL]]
            binormals = [str(-v) for values in transformed_binormals for v in values]

            ARGS[
                "LayerElementBiNormal"
            ] = """
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
                "binormals": ",".join(binormals),
                "binormals_num": len(binormals),
                "binormalsW": ",".join(["1" for i in range(idx_len)]),
                "binormalsW_num": idx_len,
            }
            ARGS[
                "LayerElementBiNormalInsert"
            ] = """
                LayerElement:  {
                        Type: "LayerElementBinormal"
                    TypedIndex: 0
                }
            """

        def run_tangents(self):
            if not vertex_data.get(TANGENT):
                return

            tangent_values = reorder_triangle_corners(value_dict[TANGENT])
            transformed_tangents = [transform_unreal_vector(values) for values in tangent_values]
            tangents = [str(v) for values in transformed_tangents for v in values]

            ARGS[
                "LayerElementTangent"
            ] = """
                LayerElementTangent: 0 {
                    Version: 101
                    Name: "map1"
                    MappingInformationType: "ByPolygonVertex"
                    ReferenceInformationType: "Direct"
                    Tangents: *%(tangents_num)s {
                        a: %(tangents)s
                    } 
                }
            """ % {
                "tangents": ",".join(tangents),
                "tangents_num": len(tangents),
            }

            ARGS[
                "LayerElementTangentInsert"
            ] = """
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
                # str(v) if i % 4 else "1"
                str(v)
                for values in color_values
                for i, v in enumerate(values, 1)
            ]

            ARGS[
                "LayerElementColor"
            ] = """
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
                "colors": ",".join(colors),
                "colors_num": len(colors),
                "colors_indices": ",".join([str(i) for i in range(len(color_values))]),
                "colors_indices_num": idx_len,
            }
            ARGS[
                "LayerElementColorInsert"
            ] = """
                LayerElement:  {
                    Type: "LayerElementColor"
                    TypedIndex: 0
                }
            """

        def run_uv(self):
            if not vertex_data.get(UV):
                return

            uv_index_values = reorder_triangle_corners(idx_list)
            uvs_indices = ",".join([str(idx) for idx in uv_index_values])
            uvs = [
                # NOTE flip y axis
                str(1 - v if i else v)
                for idx, values in sorted(vertex_data[UV].items())
                for i, v in enumerate(values)
            ]

            ARGS[
                "LayerElementUV"
            ] = """
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
                "uvs": ",".join(uvs),
                "uvs_num": len(uvs),
                "uvs_indices": uvs_indices,
                "uvs_indices_num": idx_len,
            }

            ARGS[
                "LayerElementUVInsert"
            ] = """
                LayerElement:  {
                    Type: "LayerElementUV"
                    TypedIndex: 0
                }
            """

        def run_uv2(self):
            if not vertex_data.get(UV2):
                return

            uv2_index_values = reorder_triangle_corners(idx_list)
            uvs_indices = ",".join([str(idx) for idx in uv2_index_values])
            uvs = [
                # NOTE flip y axis
                str(1 - v if i else v)
                for idx, values in sorted(vertex_data[UV2].items())
                for i, v in enumerate(values)
            ]

            ARGS[
                "LayerElementUV2"
            ] = """
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
                "uvs": ",".join(uvs),
                "uvs_num": len(uvs),
                "uvs_indices": uvs_indices,
                "uvs_indices_num": idx_len,
            }

            ARGS[
                "LayerElementUV2Insert"
            ] = """
                LayerElement:  {
                    Type: "LayerElementUV"
                    TypedIndex: 1
                }
            """

    handler = ProcessHandler()
    handler.run()

    fbx = FBX_ASCII_TEMPLETE % ARGS

    with open(save_path, "w") as f:
        f.write(dedent(fbx).strip())


def error_log(func):
    def wrapper(pyrenderdoc, data):
        manager = pyrenderdoc.Extensions()
        try:
            func(pyrenderdoc, data)
        except Exception:
            import traceback

            manager.MessageDialog("FBX Ouput Fail\n%s" % traceback.format_exc(), "Error!~")

    return wrapper


@error_log
def prepare_export(pyrenderdoc, data):
    manager = pyrenderdoc.Extensions()
    if not pyrenderdoc.HasMeshPreview():
        manager.ErrorDialog("No preview mesh!", "Error")
        return

    mqt = manager.GetMiniQtHelper()
    dialog = QueryDialog(mqt)
    # NOTE get input attribute
    if not mqt.ShowWidgetAsDialog(dialog.init_ui()):
        return

    mesh_mode            = dialog.mapper.get("MESH_MODE", "VS Input") or "VS Input"
    export_textures_flag = dialog.mapper.get("EXPORT_TEXTURES", False)

    save_path = manager.SaveFileName("Save FBX File", "", "*.fbx")
    if not save_path:
        return

    save_dir = os.path.dirname(save_path)
    fbx_name = os.path.basename(os.path.splitext(save_path)[0])
    dialog.mapper["FBX_NAME"] = fbx_name
    current  = time.time()

    # NOTE Get Data from QTableView directly
    main_window = pyrenderdoc.GetMainWindow().Widget()

    # pick table by mode
    if mesh_mode == "VS Input":
        candidates = ("vsinData", "inTable")
    else:
        candidates = ("out1Table", "vsoutData", "outTable")

    table = None
    for table_name in candidates:
        table = main_window.findChild(QtWidgets.QTableView, table_name)
        if table:
            break

    if not table:
        manager.ErrorDialog(
            "Mesh data table not found for mode: %s" % mesh_mode,
            "Error",
        )
        return

    model = table.model()
    row_count = model.rowCount()
    column_count = model.columnCount()
    rows = range(row_count)
    columns = range(column_count)

    data = defaultdict(list)
    attr_list = set()

    for _, c in MProgressDialog.loop(columns, status="Collect Mesh Data"):
        head = model.headerData(c, QtCore.Qt.Horizontal)
        values = [model.data(model.index(r, c)) for r in rows]
        if "." not in head:
            data[head] = values
        else:
            attr = head.split(".")[0]
            attr_list.add(attr)
            data[attr].append(values)

    for _, attr in MProgressDialog.loop(attr_list, status="Rearrange Mesh Data"):
        values_list = data[attr]
        data[attr] = [[float(values[r]) for values in values_list] for r in rows]

    print("elapsed time unpack: %s" % (time.time() - current))
    pyrenderdoc.Replay().BlockInvoke(partial(export_fbx, save_path, dialog.mapper, data, attr_list))

    # export textures if requested
    tex_results        = []
    tex_output_results = []
    shader_results     = []
    shader_errors      = []
    if export_textures_flag:
        pyrenderdoc.Replay().BlockInvoke(
            partial(_tex_invoke, save_dir, dialog.mapper, tex_results)
        )

    if dialog.mapper.get("EXPORT_OUTPUT_TEXTURES", False):
        pyrenderdoc.Replay().BlockInvoke(
            partial(_tex_output_invoke, save_dir, dialog.mapper, tex_output_results)
        )

    if dialog.mapper.get("EXPORT_SHADERS", False):
        pyrenderdoc.Replay().BlockInvoke(
            partial(_shader_invoke, save_dir, dialog.mapper, shader_results, shader_errors)
        )

    if os.path.exists(save_path):
        msg = "FBX Ouput Sucessfully"
        if tex_results:
            msg += "\n\nInput Textures saved (%d):\n" % len(tex_results)
            msg += "\n".join(os.path.basename(p) for p in tex_results[:20])
            if len(tex_results) > 20:
                msg += "\n... and %d more" % (len(tex_results) - 20)
        elif export_textures_flag:
            msg += "\n\nNo bound input textures found."
        if tex_output_results:
            msg += "\n\nOutput Textures saved (%d):\n" % len(tex_output_results)
            msg += "\n".join(os.path.basename(p) for p in tex_output_results)
        if shader_results:
            msg += "\n\nShaders saved (%d):\n" % len(shader_results)
            msg += "\n".join(os.path.basename(p) for p in shader_results)
            msg += "\n[fmt=%s]" % dialog.mapper.get("SHADER_FMT", "?")
        if shader_errors:
            msg += "\n\nShader export errors:\n" + "\n".join(shader_errors[:5])
        if dialog.mapper.get("EXPORT_SHADERS", False) and not shader_results and not shader_errors:
            stages = dialog.mapper.get("SHADER_STAGES", {})
            enabled = [k for k, v in stages.items() if v]
            msg += "\n\nShader export: no stages enabled (checked: %s)" % (enabled or "none")
        os.startfile(save_dir)
        manager.MessageDialog(msg, "Congradualtion!~")


def _tex_invoke(save_dir, mapper, out_list, controller):
    out_list.extend(_export_textures(save_dir, mapper, controller))


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
    bound_ids = {}  # resourceId -> label

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


def _tex_output_invoke(save_dir, mapper, out_list, controller):
    out_list.extend(_export_output_textures(save_dir, mapper, controller))


# ---------------------------------------------------------------------------
# shader export
# ---------------------------------------------------------------------------

# Map ShaderEncoding enum value to file extension
# RenderDoc ShaderEncoding: Unknown=0, DXBC=1, GLSL=2, SPIRV=3, SPIRVAsm=4,
#                           HLSL=5, OpenGLSPIRV=6, VulkanSPIRV=7, DXIL=8
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
    stages_enabled  = mapper.get("SHADER_STAGES", {})
    shader_fmt      = mapper.get("SHADER_FMT", "Binary")
    use_disasm      = (shader_fmt == "Disasm (txt)")
    fbx_name        = mapper.get("FBX_NAME", "") or ""
    shader_fbx_pfx  = mapper.get("SHADER_FBX_PREFIX", True)
    name_prefix     = (fbx_name + "_") if shader_fbx_pfx and fbx_name else ""
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
                continue  # stage not bound, skip silently

            entry_name = str(state.GetShaderEntryPoint(stage))
            res_id     = state.GetShader(stage)
            if res_id == rd.ResourceId.Null():
                continue  # stage not bound, skip silently

            enc_val  = int(refl.encoding)
            base_ext = _SHADER_EXT.get(enc_val, "bin")

            if use_disasm:
                pipe = state.GetComputePipelineObject() if stage == rd.ShaderStage.Compute else pipeline
                text = controller.DisassembleShader(pipe, refl, "")
                if not text:
                    errors.append("%s: disassembly returned empty" % stage_key)
                    continue
                # rdcstr may not be a plain Python str — force conversion
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
    infix       = mapper.get("TEX_INFIX",  "") or ""
    suffix      = mapper.get("TEX_SUFFIX", "") or ""
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
        stem = default_name if use_default else "%s%s%s%s" % (prefix, default_name, infix, suffix)
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


def register(version, pyrenderdoc):
    # version is the RenderDoc Major.Minor version as a string, such as "1.2"
    # pyrenderdoc is the CaptureContext handle, the same as the global available in the python shell
    print("Registering FBX Mesh Exporter extension for RenderDoc {}".format(version))
    pyrenderdoc.Extensions().RegisterPanelMenu(qrenderdoc.PanelMenu.MeshPreview, ["Export FBX Mesh"], prepare_export)


def unregister():
    print("Unregistrating FBX Mesh Exporter extension")


# # NOTE for reload plugin
# import subprocess
# import qrenderdoc
# location = r"E:\repo\renderdoc2fbx\install.bat"
# subprocess.call(["cmd","/c",location],shell=True)
# extension = pyrenderdoc.Extensions()
# extension.LoadExtension("exporter.fbx")
