# -*- coding: utf-8 -*-
"""
Export Options dialog for the RenderDoc FBX/OBJ Mesh Exporter.

Improvements over the original:
  * Available vertex attributes are displayed and auto-detect fills the fields.
  * Format selector: FBX (ASCII) or Wavefront OBJ.
  * Per-axis UV flip controls (U and V independently).
  * Godot engine template preset added.
"""

from __future__ import division
from __future__ import print_function
from __future__ import absolute_import

__author__ = "timmyliang"
__email__ = "820472580@qq.com"
__date__ = "2021-04-09 20:39:53"

import os
import tempfile
from functools import partial
from PySide2 import QtCore


# ---------------------------------------------------------------------------
# Auto-detect heuristics
# ---------------------------------------------------------------------------

# Map from our internal key to candidate attribute names, ordered by priority.
# The first candidate found in the available attributes list wins.
_AUTO_DETECT_MAP = {
    "POSITION": ["POSITION", "SV_Position", "ATTRIBUTE0", "ATTR0", "in_POSITION0"],
    "NORMAL":   ["NORMAL",   "ATTRIBUTE2",  "ATTR2",      "in_NORMAL0"],
    "TANGENT":  ["TANGENT",  "ATTRIBUTE1",  "ATTR1",      "in_TANGENT0"],
    "BINORMAL": ["BINORMAL", "ATTRIBUTE3",  "ATTR3",      "in_BINORMAL0"],
    "COLOR":    ["COLOR",    "COLOR0",      "ATTRIBUTE13", "ATTR13", "in_COLOR0"],
    "UV":       ["TEXCOORD0","TEXCOORD",    "UV0",         "UV",
                 "ATTRIBUTE5", "ATTR5",     "in_TEXCOORD0"],
    "UV2":      ["TEXCOORD1","UV1",         "UV2",
                 "ATTRIBUTE6", "ATTR6",     "in_TEXCOORD1"],
}


def _detect_attrs(available_attrs):
    """Return {key: detected_name} for every key that matches something in *available_attrs*."""
    attr_set = set(available_attrs)
    result   = {}
    for key, candidates in _AUTO_DETECT_MAP.items():
        for cand in candidates:
            if cand in attr_set:
                result[key] = cand
                break
    return result


# ---------------------------------------------------------------------------
# Engine templates
# ---------------------------------------------------------------------------

_ENGINE_TEMPLATES = {
    "unity": {
        "POSITION": "POSITION",  "TANGENT": "TANGENT",
        "BINORMAL": "",          "NORMAL":  "NORMAL",
        "COLOR":    "COLOR",     "UV":      "TEXCOORD0",
        "UV2":      "TEXCOORD1",
    },
    "unreal": {
        "POSITION": "ATTRIBUTE0", "TANGENT": "ATTRIBUTE1",
        "BINORMAL": "",           "NORMAL":  "ATTRIBUTE2",
        "COLOR":    "ATTRIBUTE13","UV":      "ATTRIBUTE5",
        "UV2":      "ATTRIBUTE6",
    },
    "godot": {
        "POSITION": "VERTEX",   "TANGENT": "TANGENT",
        "BINORMAL": "BINORMAL", "NORMAL":  "NORMAL",
        "COLOR":    "COLOR",    "UV":      "UV",
        "UV2":      "UV2",
    },
}


class QueryDialog(object):

    title = "Export Options"

    edit_config = [
        ("POSITION", "Position"),
        ("NORMAL",   "Normal  "),
        ("TANGENT",  "Tangent "),
        ("BINORMAL", "BiNormal"),
        ("COLOR",    "Color   "),
        ("UV",       "UV      "),
        ("UV2",      "UV2     "),
    ]

    ENGINE_OPTIONS = ["unity", "unreal", "godot"]
    MODE_OPTIONS   = ["VS Input", "VS Output"]
    FORMAT_OPTIONS = ["FBX", "OBJ"]
    FMT_OPTIONS    = ["PNG", "DDS", "TGA", "BMP", "HDR", "EXR"]
    STAGE_KEYS     = ["VS", "PS", "GS", "HS", "DS", "CS"]
    STAGE_DEFAULTS = {"VS": True, "PS": True, "GS": False,
                      "HS": False, "DS": False, "CS": False}

    def __init__(self, mqt, available_attrs=None):
        self.mqt             = mqt
        self.button_dict     = {}
        self.stage_checks    = {}
        self.mapper          = {}
        self.available_attrs = available_attrs or []
        name = "RenderDoc_%s.ini" % self.__class__.__name__
        path = os.path.join(tempfile.gettempdir(), name)
        self.settings = QtCore.QSettings(path, QtCore.QSettings.IniFormat)

    # ------------------------------------------------------------------
    # Low-level widget helpers
    # ------------------------------------------------------------------

    def _label(self, text):
        w = self.mqt.CreateLabel()
        self.mqt.SetWidgetText(w, text)
        return w

    def _combo(self, options, saved, callback):
        m = self.mqt
        c = m.CreateComboBox(False, callback)
        m.SetComboOptions(c, options)
        m.SelectComboOption(c, saved if saved in options else options[0])
        return c

    def _add_row(self, grid, row, label_text, widget):
        self.mqt.AddGridWidget(grid, row, 0, self._label(label_text), 1, 1)
        self.mqt.AddGridWidget(grid, row, 1, widget, 1, 1)

    def _add_two_per_row(self, grid, row, items_2col):
        """Place two labeled-checkbox items side-by-side in one row (2 per row)."""
        self._add_n_per_row(grid, row, items_2col, n=2)

    def _add_n_per_row(self, grid, row, items, n=2):
        """Place up to *n* labeled-checkbox items side-by-side in one row.

        Each item is a tuple (attr_name, setting_key, label, cb_name, default).
        Layout: col 0=label0, col 1=check0, col 2=label1, col 3=check1, …
        """
        m = self.mqt
        for ci, (attr_name, setting_key, label, cb_name, default) in enumerate(items[:n]):
            chk = m.CreateCheckbox(getattr(self, cb_name))
            m.SetWidgetChecked(chk, self.settings.value(setting_key, default) == "true")
            setattr(self, attr_name, chk)
            m.AddGridWidget(grid, row, ci * 2,     self._label(label), 1, 1)
            m.AddGridWidget(grid, row, ci * 2 + 1, chk,                1, 1)

    def _section(self, grid, row, title):
        self.mqt.AddGridWidget(grid, row, 0, self._label("-- %s --" % title), 1, 2)

    # ------------------------------------------------------------------
    # Engine template preset
    # ------------------------------------------------------------------

    def _apply_template(self, text):
        config = _ENGINE_TEMPLATES.get(text, {})
        self.settings.setValue("Engine", text)
        for key, edit in self.button_dict.items():
            value = config.get(key, "")
            self.settings.setValue(key, value)
            self.mqt.SetWidgetText(edit, value)

    # ------------------------------------------------------------------
    # Auto-detect from available attributes
    # ------------------------------------------------------------------

    def _apply_auto_detect(self, *_):
        """Fill attribute fields from heuristic matching of *available_attrs*."""
        detected = _detect_attrs(self.available_attrs)
        for key, edit in self.button_dict.items():
            value = detected.get(key, "")
            if value:
                self.settings.setValue(key, value)
                self.mqt.SetWidgetText(edit, value)

    # ------------------------------------------------------------------
    # Main UI builder
    # ------------------------------------------------------------------

    def init_ui(self):
        m           = self.mqt
        self.widget = m.CreateToplevelWidget(self.title, None)
        grid        = m.CreateGridContainer()
        m.AddWidget(self.widget, grid)

        r = 0   # row counter

        # ── Available Attributes (info only) ──────────────────────────────
        if self.available_attrs:
            attrs_str = ", ".join(self.available_attrs)
            # Truncate if too long for a single label
            if len(attrs_str) > 80:
                attrs_str = attrs_str[:77] + "..."
            self._section(grid, r, "Mesh Export"); r += 1
            self.mqt.AddGridWidget(
                grid, r, 0, self._label("Found attrs:"), 1, 1)
            self.mqt.AddGridWidget(
                grid, r, 1, self._label(attrs_str), 1, 1)
            r += 1
        else:
            self._section(grid, r, "Mesh Export"); r += 1

        # ── Engine preset ──────────────────────────────────────────────
        saved_engine     = self.settings.value("Engine", "unity")
        self.engine_combo = self._combo(self.ENGINE_OPTIONS, saved_engine,
                                        self._on_engine_changed)
        self._add_row(grid, r, "Engine", self.engine_combo); r += 1

        # ── Mesh mode ──────────────────────────────────────────────────
        saved_mode      = self.settings.value("MeshMode", "VS Input")
        self.mode_combo = self._combo(self.MODE_OPTIONS, saved_mode,
                                      self._on_mode_changed)
        self._add_row(grid, r, "Mesh Mode", self.mode_combo); r += 1

        # ── Export format ──────────────────────────────────────────────
        saved_fmt        = self.settings.value("ExportFormat", "FBX")
        self.fmt_combo   = self._combo(self.FORMAT_OPTIONS, saved_fmt,
                                       self._on_export_format_changed)
        self._add_row(grid, r, "Format", self.fmt_combo); r += 1

        # ── VS Output options ──────────────────────────────────────────
        # 6个主选项 3个/排 → 2行; Bake World Space + Skin Weights 2个/排 → 1行
        self._section(grid, r, "VS Output Extras (from VS Input)"); r += 1

        _vsout_checks = [
            ("vsout_uv_check",      "VSOutIncludeVSInUV",      "UV",       "_on_vsout_uv",      "true"),
            ("vsout_uv2_check",     "VSOutIncludeVSInUV2",     "UV2",      "_on_vsout_uv2",     "true"),
            ("vsout_normal_check",  "VSOutIncludeVSInNormal",  "Normal",   "_on_vsout_normal",  "true"),
            ("vsout_tangent_check", "VSOutIncludeVSInTangent", "Tangent",  "_on_vsout_tangent", "true"),
            ("vsout_binorm_check",  "VSOutIncludeVSInBinormal","BiNormal", "_on_vsout_binorm",  "true"),
            ("vsout_color_check",   "VSOutIncludeVSInColor",   "Color",    "_on_vsout_color",   "true"),
        ]
        for i in range(0, len(_vsout_checks), 3):
            self._add_n_per_row(grid, r, _vsout_checks[i:i+3], n=3); r += 1

        # Bake World Space + Export Skin Weights — 2个/排，集中在同一 section
        _vsout_extra2 = [
            ("bake_world_check",   "BakeWorldSpace", "Bake World",    "_on_bake_world",   "false"),
            ("export_skin_check",  "ExportSkin",     "Skin Weights",  "_on_export_skin",  "false"),
        ]
        self._add_n_per_row(grid, r, _vsout_extra2, n=2); r += 1

        # ── Batch EID input (单行高度) ─────────────────────────────────────
        self.batch_eids_edit = m.CreateTextBox(True, self._on_batch_eids)
        _saved_eids = self.settings.value("BatchEIDs", "")
        if _saved_eids:
            m.SetWidgetText(self.batch_eids_edit, _saved_eids)
        self._add_row(grid, r, "批量EID(如:100,200-210)", self.batch_eids_edit); r += 1

        # ── Attribute mapping fields ───────────────────────────────────
        self.button_dict = {}
        for key, label_text in self.edit_config:
            edit = m.CreateTextBox(True, partial(self._on_attr_changed, key))
            m.SetWidgetText(edit, "")
            saved = self.settings.value(key, "")
            if saved:
                m.SetWidgetText(edit, saved)
            self.button_dict[key] = edit
            self._add_row(grid, r, label_text, edit); r += 1

        # ── Auto-detect button (visible only when attrs were found) ────
        if self.available_attrs:
            detect_btn = m.CreateButton(self._apply_auto_detect)
            m.SetWidgetText(detect_btn, "Auto-detect Attributes")
            m.AddGridWidget(grid, r, 0, detect_btn, 1, 2); r += 1

        # ── UV Flip ────────────────────────────────────────────────────
        self._section(grid, r, "UV Options"); r += 1

        self.flip_u_check = m.CreateCheckbox(self._on_flip_u)
        m.SetWidgetChecked(self.flip_u_check,
            self.settings.value("FlipU", "false") == "true")
        self.flip_v_check = m.CreateCheckbox(self._on_flip_v)
        m.SetWidgetChecked(self.flip_v_check,
            self.settings.value("FlipV", "true") == "true")
        m.AddGridWidget(grid, r, 0, self._label("Flip U"), 1, 1)
        m.AddGridWidget(grid, r, 1, self.flip_u_check, 1, 1)
        m.AddGridWidget(grid, r, 2, self._label("Flip V"), 1, 1)
        m.AddGridWidget(grid, r, 3, self.flip_v_check, 1, 1)
        r += 1

        # ── Texture ────────────────────────────────────────────────────
        self._section(grid, r, "Texture Export"); r += 1

        self.tex_check = m.CreateCheckbox(self._on_tex_check)
        m.SetWidgetChecked(self.tex_check,
            self.settings.value("ExportTextures", "true") == "true")
        self.tex_output_check = m.CreateCheckbox(self._on_tex_output_check)
        m.SetWidgetChecked(self.tex_output_check,
            self.settings.value("ExportOutputTextures", "true") == "true")
        m.AddGridWidget(grid, r, 0, self._label("Export Inputs"),  1, 1)
        m.AddGridWidget(grid, r, 1, self.tex_check,                1, 1)
        m.AddGridWidget(grid, r, 2, self._label("Export Outputs"), 1, 1)
        m.AddGridWidget(grid, r, 3, self.tex_output_check,         1, 1)
        r += 1

        saved_tex_fmt      = self.settings.value("TexFormat", "PNG")
        self.tex_fmt_combo = self._combo(self.FMT_OPTIONS, saved_tex_fmt,
                                         self._on_tex_fmt_changed)
        self._add_row(grid, r, "Tex Format", self.tex_fmt_combo); r += 1

        self.default_name_check = m.CreateCheckbox(self._on_default_name)
        use_default = self.settings.value("TexDefaultName", "true") == "true"
        m.SetWidgetChecked(self.default_name_check, use_default)
        self._add_row(grid, r, "Default Name", self.default_name_check); r += 1

        self.tex_fbx_prefix_check = m.CreateCheckbox(self._on_tex_fbx_prefix)
        tex_fbx_prefix = self.settings.value("TexFbxPrefix", "true") == "true"
        m.SetWidgetChecked(self.tex_fbx_prefix_check, tex_fbx_prefix)
        self._add_row(grid, r, "FBX Name Prefix", self.tex_fbx_prefix_check); r += 1

        self.tex_prefix_edit = m.CreateTextBox(True, partial(self._on_attr_changed, "TexPrefix"))
        self.tex_infix_edit  = m.CreateTextBox(True, partial(self._on_attr_changed, "TexInfix"))
        self.tex_suffix_edit = m.CreateTextBox(True, partial(self._on_attr_changed, "TexSuffix"))
        m.SetWidgetText(self.tex_prefix_edit, self.settings.value("TexPrefix", ""))
        m.SetWidgetText(self.tex_infix_edit,  self.settings.value("TexInfix",  ""))
        m.SetWidgetText(self.tex_suffix_edit, self.settings.value("TexSuffix", ""))
        self._add_row(grid, r, "Prefix", self.tex_prefix_edit); r += 1
        self._add_row(grid, r, "Infix",  self.tex_infix_edit);  r += 1
        self._add_row(grid, r, "Suffix", self.tex_suffix_edit); r += 1

        self._set_naming_enabled(not use_default)
        if tex_fbx_prefix:
            m.SetWidgetEnabled(self.tex_prefix_edit, False)

        # ── Shader ────────────────────────────────────────────────────
        self._section(grid, r, "Shader Export"); r += 1

        self.shader_check = m.CreateCheckbox(self._on_shader_check)
        m.SetWidgetChecked(self.shader_check,
            self.settings.value("ExportShaders", "true") == "true")
        self._add_row(grid, r, "Export", self.shader_check); r += 1

        self.shader_fmt_combo = self._combo(
            ["Binary", "Disasm (txt)"],
            self.settings.value("ShaderFmt", "Disasm (txt)"),
            self._on_shader_fmt_changed)
        self._add_row(grid, r, "Format", self.shader_fmt_combo); r += 1

        self.shader_fbx_prefix_check = m.CreateCheckbox(self._on_shader_fbx_prefix)
        shader_fbx_prefix = self.settings.value("ShaderFbxPrefix", "true") == "true"
        m.SetWidgetChecked(self.shader_fbx_prefix_check, shader_fbx_prefix)
        self._add_row(grid, r, "FBX Name Prefix", self.shader_fbx_prefix_check); r += 1

        self.stage_checks = {}
        for row_keys in [self.STAGE_KEYS[:3], self.STAGE_KEYS[3:]]:
            row_widget = m.CreateHorizontalContainer()
            for sk in row_keys:
                lbl = self._label(sk)
                chk = m.CreateCheckbox(partial(self._on_stage_check, sk))
                checked = self.settings.value(
                    "ShaderStage_%s" % sk,
                    "true" if self.STAGE_DEFAULTS[sk] else "false") == "true"
                m.SetWidgetChecked(chk, checked)
                m.AddWidget(row_widget, lbl)
                m.AddWidget(row_widget, chk)
                self.stage_checks[sk] = chk
            m.AddGridWidget(grid, r, 0, row_widget, 1, 2); r += 1

        # ── OK / Cancel ───────────────────────────────────────────────
        btn_row    = m.CreateHorizontalContainer()
        cancel_btn = m.CreateButton(lambda *a: m.CloseCurrentDialog(False))
        ok_btn     = m.CreateButton(self._accept)
        m.SetWidgetText(cancel_btn, "Cancel")
        m.SetWidgetText(ok_btn,     "OK")
        m.AddWidget(btn_row, cancel_btn)
        m.AddWidget(btn_row, ok_btn)
        m.AddGridWidget(grid, r, 0, btn_row, 1, 2)

        return self.widget

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_engine_changed(self, ctx, widget, text):
        self._apply_template(text)

    def _on_mode_changed(self, ctx, widget, text):
        self.settings.setValue("MeshMode", text)

    def _on_export_format_changed(self, ctx, widget, text):
        self.settings.setValue("ExportFormat", text)

    def _on_vsout_uv(self, ctx, widget, checked):
        self.settings.setValue("VSOutIncludeVSInUV",      "true" if checked else "false")

    def _on_vsout_uv2(self, ctx, widget, checked):
        self.settings.setValue("VSOutIncludeVSInUV2",     "true" if checked else "false")

    def _on_vsout_normal(self, ctx, widget, checked):
        self.settings.setValue("VSOutIncludeVSInNormal",  "true" if checked else "false")

    def _on_vsout_tangent(self, ctx, widget, checked):
        self.settings.setValue("VSOutIncludeVSInTangent", "true" if checked else "false")

    def _on_vsout_binorm(self, ctx, widget, checked):
        self.settings.setValue("VSOutIncludeVSInBinormal","true" if checked else "false")

    def _on_vsout_color(self, ctx, widget, checked):
        self.settings.setValue("VSOutIncludeVSInColor",   "true" if checked else "false")

    def _on_bake_world(self, ctx, widget, checked):
        self.settings.setValue("BakeWorldSpace", "true" if checked else "false")

    def _on_export_skin(self, ctx, widget, checked):
        self.settings.setValue("ExportSkin", "true" if checked else "false")

    def _on_batch_eids(self, ctx, widget, text):
        self.settings.setValue("BatchEIDs", text)

    def _on_flip_u(self, ctx, widget, checked):
        self.settings.setValue("FlipU", "true" if checked else "false")

    def _on_flip_v(self, ctx, widget, checked):
        self.settings.setValue("FlipV", "true" if checked else "false")

    def _on_tex_check(self, ctx, widget, checked):
        self.settings.setValue("ExportTextures", "true" if checked else "false")

    def _on_tex_output_check(self, ctx, widget, checked):
        self.settings.setValue("ExportOutputTextures", "true" if checked else "false")

    def _on_tex_fmt_changed(self, ctx, widget, text):
        self.settings.setValue("TexFormat", text)

    def _on_default_name(self, ctx, widget, checked):
        self.settings.setValue("TexDefaultName", "true" if checked else "false")
        self._set_naming_enabled(not checked)

    def _set_naming_enabled(self, enabled):
        for w in (self.tex_prefix_edit, self.tex_infix_edit, self.tex_suffix_edit):
            self.mqt.SetWidgetEnabled(w, enabled)

    def _on_tex_fbx_prefix(self, ctx, widget, checked):
        self.settings.setValue("TexFbxPrefix", "true" if checked else "false")
        enabled = not checked and not (self.settings.value("TexDefaultName", "true") == "true")
        self.mqt.SetWidgetEnabled(self.tex_prefix_edit, enabled)

    def _on_shader_fbx_prefix(self, ctx, widget, checked):
        self.settings.setValue("ShaderFbxPrefix", "true" if checked else "false")

    def _on_shader_check(self, ctx, widget, checked):
        self.settings.setValue("ExportShaders", "true" if checked else "false")

    def _on_shader_fmt_changed(self, ctx, widget, text):
        self.settings.setValue("ShaderFmt", text)

    def _on_stage_check(self, stage_key, ctx, widget, checked):
        self.settings.setValue("ShaderStage_%s" % stage_key,
                               "true" if checked else "false")

    def _on_attr_changed(self, key, ctx, widget, text):
        self.settings.setValue(key, text)

    def _accept(self, ctx, widget, text):
        m = self.mqt

        # Attribute mapping
        self.mapper = {}
        for key, edit in self.button_dict.items():
            self.mapper[key] = m.GetWidgetText(edit)

        # General export options
        self.mapper["ENGINE"]      = self.settings.value("Engine",     "unity")
        self.mapper["MESH_MODE"]   = self.settings.value("MeshMode",   "VS Input")
        self.mapper["EXPORT_FORMAT"]= self.settings.value("ExportFormat","FBX")
        # VS Output pass-through attributes
        self.mapper["VSOUT_INCLUDE_VSIN_UV"]      = m.IsWidgetChecked(self.vsout_uv_check)
        self.mapper["VSOUT_INCLUDE_VSIN_UV2"]     = m.IsWidgetChecked(self.vsout_uv2_check)
        self.mapper["VSOUT_INCLUDE_VSIN_NORMAL"]  = m.IsWidgetChecked(self.vsout_normal_check)
        self.mapper["VSOUT_INCLUDE_VSIN_TANGENT"] = m.IsWidgetChecked(self.vsout_tangent_check)
        self.mapper["VSOUT_INCLUDE_VSIN_BINORMAL"]= m.IsWidgetChecked(self.vsout_binorm_check)
        self.mapper["VSOUT_INCLUDE_VSIN_COLOR"]   = m.IsWidgetChecked(self.vsout_color_check)
        self.mapper["BAKE_WORLD_SPACE"]           = m.IsWidgetChecked(self.bake_world_check)
        self.mapper["EXPORT_SKIN"]                = m.IsWidgetChecked(self.export_skin_check)
        self.mapper["BATCH_EIDS"]                 = m.GetWidgetText(self.batch_eids_edit)
        self.mapper["FLIP_U"] = m.IsWidgetChecked(self.flip_u_check)
        self.mapper["FLIP_V"] = m.IsWidgetChecked(self.flip_v_check)

        # Texture options
        self.mapper["EXPORT_TEXTURES"]        = m.IsWidgetChecked(self.tex_check)
        self.mapper["EXPORT_OUTPUT_TEXTURES"] = m.IsWidgetChecked(self.tex_output_check)
        self.mapper["TEX_FORMAT"]             = self.settings.value("TexFormat",            "PNG")
        self.mapper["TEX_DEFAULT_NAME"]       = m.IsWidgetChecked(self.default_name_check)
        self.mapper["TEX_PREFIX"]             = m.GetWidgetText(self.tex_prefix_edit)
        self.mapper["TEX_INFIX"]              = m.GetWidgetText(self.tex_infix_edit)
        self.mapper["TEX_SUFFIX"]             = m.GetWidgetText(self.tex_suffix_edit)
        self.mapper["TEX_FBX_PREFIX"]         = m.IsWidgetChecked(self.tex_fbx_prefix_check)

        # Shader options
        self.mapper["EXPORT_SHADERS"]         = m.IsWidgetChecked(self.shader_check)
        self.mapper["SHADER_FMT"]             = self.settings.value("ShaderFmt",            "Binary")
        self.mapper["SHADER_FBX_PREFIX"]      = m.IsWidgetChecked(self.shader_fbx_prefix_check)
        self.mapper["SHADER_STAGES"]          = {
            k: m.IsWidgetChecked(v) for k, v in self.stage_checks.items()
        }

        m.CloseCurrentDialog(True)
