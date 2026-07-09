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
#
# Vulkan captures use location-based names: _input0, _input1, ...
# Common Unreal Vulkan layout: loc0=position, loc1=tangent, loc2=normal,
#   loc3/loc5=UV, loc4/loc6=UV2, loc13=color.
# Common Unity/DX11 captures: POSITION, NORMAL, TEXCOORD0 …
# Both sets are listed so the heuristic works for either API.
_AUTO_DETECT_MAP = {
    "POSITION": ["POSITION", "SV_Position",
                 "ATTRIBUTE0", "ATTR0", "_input0", "in_POSITION0"],
    "NORMAL":   ["NORMAL",
                 "ATTRIBUTE2", "ATTR2",  "_input2", "in_NORMAL0"],
    "TANGENT":  ["TANGENT",
                 "ATTRIBUTE1", "ATTR1",  "_input1", "in_TANGENT0"],
    "BINORMAL": ["BINORMAL",
                 "ATTRIBUTE3", "ATTR3",  "_input3", "in_BINORMAL0"],
    "COLOR":    ["COLOR",    "COLOR0",
                 "ATTRIBUTE13", "ATTR13", "_input13",
                 "ATTRIBUTE5",  "_input5", "in_COLOR0"],
    "UV":       ["TEXCOORD0", "TEXCOORD", "UV0", "UV",
                 "ATTRIBUTE5", "ATTR5",   "_input5",
                 "ATTRIBUTE3", "_input3", "in_TEXCOORD0"],
    "UV2":      ["TEXCOORD1", "UV1", "UV2",
                 "ATTRIBUTE6", "ATTR6", "_input6",
                 "ATTRIBUTE4", "_input4", "in_TEXCOORD1"],
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
        self.mqt              = mqt
        self.button_dict      = {}
        self.stage_checks     = {}
        self.mapper           = {}
        self.available_attrs  = available_attrs or []
        self._attr_is_combo   = False   # True when combo boxes used for attr fields
        name = "RenderDoc_%s.ini" % self.__class__.__name__
        path = os.path.join(tempfile.gettempdir(), name)
        self.settings = QtCore.QSettings(path, QtCore.QSettings.IniFormat)

    # ------------------------------------------------------------------
    # Low-level widget helpers
    # ------------------------------------------------------------------

    def _label(self, text):
        """Create a QLabel using PySide2 directly (works in PySide2 layouts)."""
        from PySide2 import QtWidgets
        return QtWidgets.QLabel(text)

    def _combo(self, options, saved, callback):
        m = self.mqt
        c = m.CreateComboBox(False, callback)
        m.SetComboOptions(c, options)
        m.SelectComboOption(c, saved if saved in options else options[0])
        return c

    def _add_row(self, _grid, row, label_text, widget):
        """Add a label+widget row to the PySide2 grid layout."""
        self._gl.addWidget(self._label(label_text), row, 0, 1, 1)
        self._gl.addWidget(widget,                  row, 1, 1, 1)

    def _add_two_per_row(self, grid, row, items_2col):
        """Compatibility wrapper — calls _add_n_per_row with n=2."""
        self._add_n_per_row(grid, row, items_2col, n=2)

    def _add_n_per_row(self, _grid, outer_row, items, n=2):
        """Place n checkboxes side-by-side in a PySide2 sub-widget.

        The sub-widget spans both columns (col 0-1), so it left-aligns at
        the dialog edge and never exceeds the Engine combo box right boundary.
        Each of the n checkboxes gets an equal share of that width.
        """
        from PySide2 import QtWidgets
        m = self.mqt
        sub = QtWidgets.QWidget()
        sub_gl = QtWidgets.QGridLayout(sub)
        sub_gl.setContentsMargins(0, 0, 0, 0)
        sub_gl.setSpacing(4)
        for ci, (attr_name, setting_key, label, cb_name, default) in enumerate(items[:n]):
            chk = m.CreateCheckbox(getattr(self, cb_name))
            m.SetWidgetChecked(chk, self.settings.value(setting_key, default) == "true")
            m.SetWidgetText(chk, label)   # label text on the checkbox itself
            setattr(self, attr_name, chk)
            sub_gl.addWidget(chk, 0, ci, 1, 1)
            sub_gl.setColumnStretch(ci, 1)   # equal column widths
        self._gl.addWidget(sub, outer_row, 0, 1, 2)   # span col 0+1

    def _add_check_row(self, _grid, row, label, chk_widget):
        """Single checkbox spanning both columns with inline label text.

        Consistent with _add_n_per_row style: label text is set directly on
        the checkbox, and the widget spans col 0 → col 1 (full dialog width).
        """
        from PySide2 import QtWidgets
        self.mqt.SetWidgetText(chk_widget, label)
        sub = QtWidgets.QWidget()
        sub_gl = QtWidgets.QGridLayout(sub)
        sub_gl.setContentsMargins(0, 0, 0, 0)
        sub_gl.setSpacing(0)
        sub_gl.addWidget(chk_widget, 0, 0, 1, 1)
        sub_gl.setColumnStretch(0, 1)
        self._gl.addWidget(sub, row, 0, 1, 2)

    def _section(self, _grid, row, title):
        """Add a section-title row spanning both columns."""
        self._gl.addWidget(self._label("-- %s --" % title), row, 0, 1, 2)

    # ------------------------------------------------------------------
    # Engine template preset
    # ------------------------------------------------------------------

    def _apply_template(self, text):
        config = _ENGINE_TEMPLATES.get(text, {})
        self.settings.setValue("Engine", text)
        for key, edit in self.button_dict.items():
            value = config.get(key, "")
            self.settings.setValue(key, value)
            if self._attr_is_combo:
                self.mqt.SelectComboOption(edit, value)
            else:
                self.mqt.SetWidgetText(edit, value)

    # ------------------------------------------------------------------
    # Auto-detect from available attributes
    # ------------------------------------------------------------------

    def _apply_auto_detect(self, *_):
        """Fill attribute fields from heuristic matching of *available_attrs*."""
        detected = _detect_attrs(self.available_attrs)
        for key, edit in self.button_dict.items():
            value = detected.get(key, "")
            if self._attr_is_combo:
                self.mqt.SelectComboOption(edit, value)
                if value:
                    self.settings.setValue(key, value)
            else:
                if value:
                    self.settings.setValue(key, value)
                    self.mqt.SetWidgetText(edit, value)

    # ------------------------------------------------------------------
    # Main UI builder
    # ------------------------------------------------------------------

    def init_ui(self):
        from PySide2 import QtWidgets, QtCore
        m = self.mqt

        # ── Pure PySide2 outer shell: QDialog → QScrollArea → QWidget ─────
        dlg = QtWidgets.QDialog()
        dlg.setWindowTitle(self.title)
        dlg.resize(440, 580)

        outer = QtWidgets.QVBoxLayout(dlg)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        outer.addWidget(scroll, 1)           # stretch=1, takes all spare space

        content = QtWidgets.QWidget()
        self._gl = QtWidgets.QGridLayout(content)
        self._gl.setContentsMargins(6, 6, 6, 6)
        self._gl.setSpacing(4)
        self._gl.setColumnStretch(1, 1)      # widget column stretches
        scroll.setWidget(content)

        # OK / Cancel row (outside scroll area — always visible)
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        def _on_ok():
            self._accept(None, None, None)
            dlg.accept()
        btn_box.accepted.connect(_on_ok)
        btn_box.rejected.connect(dlg.reject)
        outer.addWidget(btn_box)

        self.widget = dlg
        grid = None          # kept as dummy parameter for helper methods
        r = 0

        # ── Available Attributes (text box, scrollable) ───────────────────
        self._section(grid, r, "Mesh Export"); r += 1
        if self.available_attrs:
            from PySide2 import QtWidgets as _QW2
            _attrs_box = _QW2.QPlainTextEdit()
            _attrs_box.setReadOnly(True)
            _attrs_box.setFixedHeight(64)
            _attrs_box.setPlainText("  ".join(self.available_attrs))
            _attrs_box.setLineWrapMode(_QW2.QPlainTextEdit.WidgetWidth)
            self._gl.addWidget(self._label("Found attrs:"), r, 0, 1, 1)
            self._gl.addWidget(_attrs_box,                  r, 1, 1, 1)
            r += 1

        # ── Engine preset ──────────────────────────────────────────────
        saved_engine     = self.settings.value("Engine", "unity")
        self.engine_combo = self._combo(self.ENGINE_OPTIONS, saved_engine,
                                        self._on_engine_changed)
        self._add_row(grid, r, "Engine", self.engine_combo); r += 1

        # ── Mesh mode — two independent checkboxes ─────────────────────
        _mode_items = [
            ("vsin_check",  "ExportVSIn",  "VS Input",  "_on_vsin_check",  "true"),
            ("vsout_check", "ExportVSOut", "VS Output", "_on_vsout_check", "false"),
        ]
        self._add_n_per_row(grid, r, _mode_items, n=2); r += 1

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
        # When VS Input attrs are available: dropdown populated from found
        # attrs; initial selection = auto-detected name, fallback to saved.
        # When no attrs found: plain text box for manual input.
        self.button_dict     = {}
        self._attr_is_combo  = bool(self.available_attrs)
        _attr_options        = [""] + list(self.available_attrs)  # "" = no mapping
        _auto_initial        = _detect_attrs(self.available_attrs) if self.available_attrs else {}

        for key, label_text in self.edit_config:
            if self._attr_is_combo:
                # Pick initial selection: auto-detect > saved (if in list) > ""
                _saved   = self.settings.value(key, "")
                _initial = _auto_initial.get(key, "")
                if not _initial and _saved in _attr_options:
                    _initial = _saved
                # Persist initial value now — SelectComboOption may not fire
                # the callback, so settings might otherwise keep a stale value.
                self.settings.setValue(key, _initial)
                edit = self._combo(_attr_options, _initial,
                                   partial(self._on_attr_changed, key))
            else:
                edit = m.CreateTextBox(True, partial(self._on_attr_changed, key))
                saved = self.settings.value(key, "")
                if saved:
                    m.SetWidgetText(edit, saved)
            self.button_dict[key] = edit
            self._add_row(grid, r, label_text, edit); r += 1

        # ── Auto-detect button (reset combos / fill text boxes) ───────
        if self.available_attrs:
            detect_btn = m.CreateButton(self._apply_auto_detect)
            m.SetWidgetText(detect_btn, "Auto-detect Attributes")
            self._gl.addWidget(detect_btn, r, 0, 1, 2); r += 1

        # ── UV Flip ────────────────────────────────────────────────────
        self._section(grid, r, "UV Options"); r += 1

        _flip_items = [
            ("flip_u_check", "FlipU", "Flip U", "_on_flip_u", "false"),
            ("flip_v_check", "FlipV", "Flip V", "_on_flip_v", "true"),
        ]
        self._add_n_per_row(grid, r, _flip_items, n=2); r += 1

        # ── Texture ────────────────────────────────────────────────────
        self._section(grid, r, "Texture Export"); r += 1

        _tex_items = [
            ("tex_check",        "ExportTextures",       "Export Inputs",  "_on_tex_check",        "true"),
            ("tex_output_check", "ExportOutputTextures", "Export Outputs", "_on_tex_output_check", "true"),
        ]
        self._add_n_per_row(grid, r, _tex_items, n=2); r += 1

        saved_tex_fmt      = self.settings.value("TexFormat", "PNG")
        self.tex_fmt_combo = self._combo(self.FMT_OPTIONS, saved_tex_fmt,
                                         self._on_tex_fmt_changed)
        self._add_row(grid, r, "Tex Format", self.tex_fmt_combo); r += 1

        self.default_name_check = m.CreateCheckbox(self._on_default_name)
        use_default = self.settings.value("TexDefaultName", "true") == "true"
        m.SetWidgetChecked(self.default_name_check, use_default)
        self._add_check_row(grid, r, "Default Name", self.default_name_check); r += 1

        self.tex_fbx_prefix_check = m.CreateCheckbox(self._on_tex_fbx_prefix)
        tex_fbx_prefix = self.settings.value("TexFbxPrefix", "true") == "true"
        m.SetWidgetChecked(self.tex_fbx_prefix_check, tex_fbx_prefix)
        self._add_check_row(grid, r, "FBX Name Prefix", self.tex_fbx_prefix_check); r += 1

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
        self._add_check_row(grid, r, "Export Shaders", self.shader_check); r += 1

        self.shader_fmt_combo = self._combo(
            ["Binary", "Disasm (txt)"],
            self.settings.value("ShaderFmt", "Disasm (txt)"),
            self._on_shader_fmt_changed)
        self._add_row(grid, r, "Format", self.shader_fmt_combo); r += 1

        self.shader_fbx_prefix_check = m.CreateCheckbox(self._on_shader_fbx_prefix)
        shader_fbx_prefix = self.settings.value("ShaderFbxPrefix", "true") == "true"
        m.SetWidgetChecked(self.shader_fbx_prefix_check, shader_fbx_prefix)
        self._add_check_row(grid, r, "FBX Name Prefix", self.shader_fbx_prefix_check); r += 1

        self.stage_checks = {}
        for row_keys in [self.STAGE_KEYS[:3], self.STAGE_KEYS[3:]]:
            from PySide2 import QtWidgets as _QW
            row_widget = _QW.QWidget()
            row_layout = _QW.QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            for sk in row_keys:
                chk = m.CreateCheckbox(partial(self._on_stage_check, sk))
                m.SetWidgetText(chk, sk)
                checked = self.settings.value(
                    "ShaderStage_%s" % sk,
                    "true" if self.STAGE_DEFAULTS[sk] else "false") == "true"
                m.SetWidgetChecked(chk, checked)
                row_layout.addWidget(chk)
                self.stage_checks[sk] = chk
            row_layout.addStretch()
            self._gl.addWidget(row_widget, r, 0, 1, 2); r += 1

        # ── Config JSON Save / Load ───────────────────────────────────
        self._section(grid, r, "Config"); r += 1
        from PySide2 import QtWidgets as _QW3
        _cfg_row = _QW3.QWidget()
        _cfg_lay = _QW3.QHBoxLayout(_cfg_row)
        _cfg_lay.setContentsMargins(0, 0, 0, 0)
        _cfg_lay.setSpacing(4)
        _save_btn  = m.CreateButton(self._on_save_config)
        m.SetWidgetText(_save_btn, "Save Config")
        _load_btn  = m.CreateButton(self._on_load_config)
        m.SetWidgetText(_load_btn, "Load Config")
        _reset_btn = m.CreateButton(self._on_reset_config)
        m.SetWidgetText(_reset_btn, "Reset Defaults")
        _cfg_lay.addWidget(_save_btn)
        _cfg_lay.addWidget(_load_btn)
        _cfg_lay.addWidget(_reset_btn)
        _cfg_lay.addStretch()
        self._gl.addWidget(_cfg_row, r, 0, 1, 2); r += 1

        return self.widget

        return self.widget

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_save_config(self, *_):
        """Save all current settings to a user-chosen JSON file."""
        from PySide2 import QtWidgets as _QW
        path, _ = _QW.QFileDialog.getSaveFileName(
            None, "Save Config", "", "JSON Files (*.json)")
        if not path:
            return
        import json
        cfg = self._gather_config()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
        except Exception as e:
            _QW.QMessageBox.warning(None, "Save Config", "Failed to save:\n%s" % e)

    def _on_load_config(self, *_):
        """Load settings from a JSON file and apply them to the dialog."""
        from PySide2 import QtWidgets as _QW
        path, _ = _QW.QFileDialog.getOpenFileName(
            None, "Load Config", "", "JSON Files (*.json)")
        if not path:
            return
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            _QW.QMessageBox.warning(None, "Load Config", "Failed to load:\n%s" % e)
            return
        self._apply_config(cfg)

    def _on_reset_config(self, *_):
        """Reset all settings to factory defaults."""
        default_engine = "unity"
        unity_attrs    = _ENGINE_TEMPLATES.get(default_engine, {})
        cfg = {
            # Attribute mapping — unity preset
            "POSITION": unity_attrs.get("POSITION", ""),
            "NORMAL":   unity_attrs.get("NORMAL",   ""),
            "TANGENT":  unity_attrs.get("TANGENT",  ""),
            "BINORMAL": unity_attrs.get("BINORMAL", ""),
            "COLOR":    unity_attrs.get("COLOR",    ""),
            "UV":       unity_attrs.get("UV",       ""),
            "UV2":      unity_attrs.get("UV2",      ""),
            # Mesh mode
            "ExportVSIn":  True,
            "ExportVSOut": False,
            "ExportFormat": "FBX",
            "Engine":       default_engine,
            # VS Output extras
            "VSOutIncludeVSInUV":      True,
            "VSOutIncludeVSInUV2":     True,
            "VSOutIncludeVSInNormal":  True,
            "VSOutIncludeVSInTangent": True,
            "VSOutIncludeVSInBinormal":True,
            "VSOutIncludeVSInColor":   True,
            "BakeWorldSpace": False,
            "ExportSkin":     False,
            # UV
            "FlipU": False,
            "FlipV": True,
            # Texture
            "ExportTextures":       True,
            "ExportOutputTextures": True,
            "TexFormat":     "PNG",
            "TexDefaultName": True,
            "TexFbxPrefix":   True,
            "TexPrefix": "",
            "TexInfix":  "",
            "TexSuffix": "",
            # Shader
            "ExportShaders":   True,
            "ShaderFmt":       "Disasm (txt)",
            "ShaderFbxPrefix": True,
            "ShaderStages": {k: self.STAGE_DEFAULTS.get(k, False)
                             for k in self.STAGE_KEYS},
            # Batch
            "BatchEIDs": "",
        }
        self._apply_config(cfg)

    def _gather_config(self):
        """Collect all current settings into a plain dict suitable for JSON."""
        m   = self.mqt
        cfg = {}
        # Attribute mapping
        for key, edit in self.button_dict.items():
            if self._attr_is_combo:
                cfg[key] = self.settings.value(key, "")
            else:
                cfg[key] = m.GetWidgetText(edit)
        # Checkboxes
        cfg["ExportVSIn"]             = m.IsWidgetChecked(self.vsin_check)
        cfg["ExportVSOut"]            = m.IsWidgetChecked(self.vsout_check)
        cfg["VSOutIncludeVSInUV"]     = m.IsWidgetChecked(self.vsout_uv_check)
        cfg["VSOutIncludeVSInUV2"]    = m.IsWidgetChecked(self.vsout_uv2_check)
        cfg["VSOutIncludeVSInNormal"] = m.IsWidgetChecked(self.vsout_normal_check)
        cfg["VSOutIncludeVSInTangent"]= m.IsWidgetChecked(self.vsout_tangent_check)
        cfg["VSOutIncludeVSInBinormal"]=m.IsWidgetChecked(self.vsout_binorm_check)
        cfg["VSOutIncludeVSInColor"]  = m.IsWidgetChecked(self.vsout_color_check)
        cfg["BakeWorldSpace"]         = m.IsWidgetChecked(self.bake_world_check)
        cfg["ExportSkin"]             = m.IsWidgetChecked(self.export_skin_check)
        cfg["FlipU"]                  = m.IsWidgetChecked(self.flip_u_check)
        cfg["FlipV"]                  = m.IsWidgetChecked(self.flip_v_check)
        cfg["ExportTextures"]         = m.IsWidgetChecked(self.tex_check)
        cfg["ExportOutputTextures"]   = m.IsWidgetChecked(self.tex_output_check)
        cfg["TexDefaultName"]         = m.IsWidgetChecked(self.default_name_check)
        cfg["TexFbxPrefix"]           = m.IsWidgetChecked(self.tex_fbx_prefix_check)
        cfg["ExportShaders"]          = m.IsWidgetChecked(self.shader_check)
        cfg["ShaderFbxPrefix"]        = m.IsWidgetChecked(self.shader_fbx_prefix_check)
        cfg["ShaderStages"]           = {k: m.IsWidgetChecked(v)
                                         for k, v in self.stage_checks.items()}
        # Combos
        cfg["Engine"]      = self.settings.value("Engine",       "unity")
        cfg["ExportFormat"]= self.settings.value("ExportFormat", "FBX")
        cfg["TexFormat"]   = self.settings.value("TexFormat",    "PNG")
        cfg["ShaderFmt"]   = self.settings.value("ShaderFmt",    "Disasm (txt)")
        # Text fields
        cfg["BatchEIDs"]   = m.GetWidgetText(self.batch_eids_edit)
        cfg["TexPrefix"]   = m.GetWidgetText(self.tex_prefix_edit)
        cfg["TexInfix"]    = m.GetWidgetText(self.tex_infix_edit)
        cfg["TexSuffix"]   = m.GetWidgetText(self.tex_suffix_edit)
        return cfg

    def _apply_config(self, cfg):
        """Apply a config dict (loaded from JSON) to the dialog widgets and settings."""
        m    = self.mqt
        s    = self.settings
        _attr_options = [""] + list(self.available_attrs)

        # Attribute mapping
        _attr_options = [""] + list(self.available_attrs)
        for key, edit in self.button_dict.items():
            val = cfg.get(key, "")
            s.setValue(key, val)
            if self._attr_is_combo:
                # SelectComboOption requires exact match; fall back to "" if not in list
                _opt = val if val in _attr_options else ""
                m.SelectComboOption(edit, _opt)
                s.setValue(key, _opt)
            else:
                m.SetWidgetText(edit, val)

        def _set_check(widget, key, default=False):
            v = cfg.get(key, default)
            if isinstance(v, bool):
                m.SetWidgetChecked(widget, v)
            s.setValue(key, "true" if v else "false")

        _set_check(self.vsin_check,           "ExportVSIn",             True)
        _set_check(self.vsout_check,          "ExportVSOut",            False)
        _set_check(self.vsout_uv_check,       "VSOutIncludeVSInUV",     True)
        _set_check(self.vsout_uv2_check,      "VSOutIncludeVSInUV2",    True)
        _set_check(self.vsout_normal_check,   "VSOutIncludeVSInNormal", True)
        _set_check(self.vsout_tangent_check,  "VSOutIncludeVSInTangent",True)
        _set_check(self.vsout_binorm_check,   "VSOutIncludeVSInBinormal",True)
        _set_check(self.vsout_color_check,    "VSOutIncludeVSInColor",  True)
        _set_check(self.bake_world_check,     "BakeWorldSpace",         False)
        _set_check(self.export_skin_check,    "ExportSkin",             False)
        _set_check(self.flip_u_check,         "FlipU",                  False)
        _set_check(self.flip_v_check,         "FlipV",                  True)
        _set_check(self.tex_check,            "ExportTextures",         True)
        _set_check(self.tex_output_check,     "ExportOutputTextures",   True)
        _set_check(self.default_name_check,   "TexDefaultName",         True)
        _set_check(self.tex_fbx_prefix_check, "TexFbxPrefix",           True)
        _set_check(self.shader_check,         "ExportShaders",          True)
        _set_check(self.shader_fbx_prefix_check,"ShaderFbxPrefix",      True)

        for sk, chk in self.stage_checks.items():
            v = cfg.get("ShaderStages", {}).get(sk, self.STAGE_DEFAULTS.get(sk, False))
            m.SetWidgetChecked(chk, v)
            s.setValue("ShaderStage_%s" % sk, "true" if v else "false")

        # Combos — SelectComboOption via MiniQtHelper
        def _set_combo(widget, key, options, default):
            val = cfg.get(key, default)
            if val in options:
                m.SelectComboOption(widget, val)
            s.setValue(key, val)

        _set_combo(self.engine_combo,   "Engine",       self.ENGINE_OPTIONS, "unity")
        _set_combo(self.fmt_combo,      "ExportFormat", self.FORMAT_OPTIONS, "FBX")
        _set_combo(self.tex_fmt_combo,  "TexFormat",    self.FMT_OPTIONS,    "PNG")
        _set_combo(self.shader_fmt_combo,"ShaderFmt",   ["Binary","Disasm (txt)"], "Disasm (txt)")

        # Text fields
        def _set_text(widget, key, default=""):
            val = cfg.get(key, default)
            m.SetWidgetText(widget, val)
            s.setValue(key, val)

        _set_text(self.batch_eids_edit, "BatchEIDs")
        _set_text(self.tex_prefix_edit, "TexPrefix")
        _set_text(self.tex_infix_edit,  "TexInfix")
        _set_text(self.tex_suffix_edit, "TexSuffix")

    def _on_engine_changed(self, ctx, widget, text):
        self._apply_template(text)

    def _on_vsin_check(self, ctx, widget, checked):
        self.settings.setValue("ExportVSIn",  "true" if checked else "false")

    def _on_vsout_check(self, ctx, widget, checked):
        self.settings.setValue("ExportVSOut", "true" if checked else "false")

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
        # For combo boxes: read from settings (updated by _on_attr_changed
        # callback on every selection change, and saved during init_ui).
        # GetWidgetText is unreliable for MiniQtHelper combo boxes — it may
        # return "" instead of the selected option text.
        # For text boxes: read directly from the widget as before.
        self.mapper = {}
        for key, edit in self.button_dict.items():
            if self._attr_is_combo:
                val = self.settings.value(key, "")
            else:
                val = m.GetWidgetText(edit)
                self.settings.setValue(key, val)
            self.mapper[key] = val

        # General export options
        self.mapper["ENGINE"]        = self.settings.value("Engine",      "unity")
        self.mapper["EXPORT_VSIN"]   = m.IsWidgetChecked(self.vsin_check)
        self.mapper["EXPORT_VSOUT"]  = m.IsWidgetChecked(self.vsout_check)
        self.mapper["EXPORT_FORMAT"] = self.settings.value("ExportFormat", "FBX")
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
        # Dialog is closed by QDialogButtonBox's OK button in init_ui.
