# -*- coding: utf-8 -*-
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

    ENGINE_OPTIONS = ["unity", "unreal"]
    MODE_OPTIONS   = ["VS Input", "VS Output"]
    FMT_OPTIONS    = ["PNG", "DDS", "TGA", "BMP", "HDR", "EXR"]
    STAGE_KEYS     = ["VS", "PS", "GS", "HS", "DS", "CS"]
    STAGE_DEFAULTS = {"VS": True, "PS": True, "GS": False,
                      "HS": False, "DS": False, "CS": False}

    def __init__(self, mqt):
        self.mqt = mqt
        self.button_dict  = {}
        self.stage_checks = {}
        self.mapper       = {}
        name = "RenderDoc_%s.ini" % self.__class__.__name__
        path = os.path.join(tempfile.gettempdir(), name)
        self.settings = QtCore.QSettings(path, QtCore.QSettings.IniFormat)

    # ------------------------------------------------------------------
    # helpers
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
        """Add a label+widget pair as one grid row."""
        self.mqt.AddGridWidget(grid, row, 0, self._label(label_text), 1, 1)
        self.mqt.AddGridWidget(grid, row, 1, widget, 1, 1)

    def _section(self, grid, row, title):
        """Add a section header spanning both columns."""
        self.mqt.AddGridWidget(grid, row, 0, self._label("-- %s --" % title), 1, 2)

    # ------------------------------------------------------------------
    # engine template preset
    # ------------------------------------------------------------------
    def _apply_template(self, text):
        config = {}
        if text == "unity":
            config = {
                "POSITION": "POSITION",  "TANGENT": "TANGENT",
                "BINORMAL": "",          "NORMAL":  "NORMAL",
                "COLOR":    "COLOR",     "UV":      "TEXCOORD0",
                "UV2":      "TEXCOORD1",
            }
        elif text == "unreal":
            config = {
                "POSITION": "ATTRIBUTE0", "TANGENT": "ATTRIBUTE1",
                "BINORMAL": "",           "NORMAL":  "ATTRIBUTE2",
                "COLOR":    "ATTRIBUTE13","UV":      "ATTRIBUTE5",
                "UV2":      "ATTRIBUTE6",
            }
        self.settings.setValue("Engine", text)
        for key, edit in self.button_dict.items():
            value = config.get(key, "")
            self.settings.setValue(key, value)
            self.mqt.SetWidgetText(edit, value)

    # ------------------------------------------------------------------
    # main UI builder
    # ------------------------------------------------------------------
    def init_ui(self):
        m = self.mqt
        self.widget = m.CreateToplevelWidget(self.title, None)
        grid = m.CreateGridContainer()
        m.AddWidget(self.widget, grid)

        r = 0   # current row counter

        # ── Mesh ──────────────────────────────────────────────────────
        self._section(grid, r, "Mesh Export"); r += 1

        saved_engine = self.settings.value("Engine", "unity")
        self.engine_combo = self._combo(self.ENGINE_OPTIONS, saved_engine,
                                        self._on_engine_changed)
        self._add_row(grid, r, "Engine", self.engine_combo); r += 1

        saved_mode = self.settings.value("MeshMode", "VS Input")
        self.mode_combo = self._combo(self.MODE_OPTIONS, saved_mode,
                                      self._on_mode_changed)
        self._add_row(grid, r, "Mesh Mode", self.mode_combo); r += 1

        self.button_dict = {}
        for key, label_text in self.edit_config:
            edit = m.CreateTextBox(True, partial(self._on_attr_changed, key))
            m.SetWidgetText(edit, "")
            saved = self.settings.value(key, "")
            if saved:
                m.SetWidgetText(edit, saved)
            self.button_dict[key] = edit
            self._add_row(grid, r, label_text, edit); r += 1

        # ── Texture ───────────────────────────────────────────────────
        self._section(grid, r, "Texture Export"); r += 1

        self.tex_check = m.CreateCheckbox(self._on_tex_check)
        m.SetWidgetChecked(self.tex_check,
            self.settings.value("ExportTextures", "true") == "true")
        self._add_row(grid, r, "Export Inputs", self.tex_check); r += 1

        self.tex_output_check = m.CreateCheckbox(self._on_tex_output_check)
        m.SetWidgetChecked(self.tex_output_check,
            self.settings.value("ExportOutputTextures", "true") == "true")
        self._add_row(grid, r, "Export Outputs", self.tex_output_check); r += 1

        saved_fmt = self.settings.value("TexFormat", "PNG")
        self.tex_fmt_combo = self._combo(self.FMT_OPTIONS, saved_fmt,
                                         self._on_fmt_changed)
        self._add_row(grid, r, "Format", self.tex_fmt_combo); r += 1

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
        # if FBX prefix is on, disable the manual prefix field
        if tex_fbx_prefix:
            m.SetWidgetEnabled(self.tex_prefix_edit, False)

        # ── Shader ────────────────────────────────────────────────────
        self._section(grid, r, "Shader Export"); r += 1

        self.shader_check = m.CreateCheckbox(self._on_shader_check)
        m.SetWidgetChecked(self.shader_check,
            self.settings.value("ExportShaders", "true") == "true")
        self._add_row(grid, r, "Export", self.shader_check); r += 1

        # shader output format: Binary / Disasm(txt)
        self.shader_fmt_combo = self._combo(
            ["Binary", "Disasm (txt)"],
            self.settings.value("ShaderFmt", "Disasm (txt)"),
            self._on_shader_fmt_changed)
        self._add_row(grid, r, "Format", self.shader_fmt_combo); r += 1

        self.shader_fbx_prefix_check = m.CreateCheckbox(self._on_shader_fbx_prefix)
        shader_fbx_prefix = self.settings.value("ShaderFbxPrefix", "true") == "true"
        m.SetWidgetChecked(self.shader_fbx_prefix_check, shader_fbx_prefix)
        self._add_row(grid, r, "FBX Name Prefix", self.shader_fbx_prefix_check); r += 1

        # stages: two rows of 3, packed into a single horizontal container each
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
        btn_row = m.CreateHorizontalContainer()
        cancel_btn = m.CreateButton(lambda *a: m.CloseCurrentDialog(False))
        ok_btn     = m.CreateButton(self._accept)
        m.SetWidgetText(cancel_btn, "Cancel")
        m.SetWidgetText(ok_btn,     "OK")
        m.AddWidget(btn_row, cancel_btn)
        m.AddWidget(btn_row, ok_btn)
        m.AddGridWidget(grid, r, 0, btn_row, 1, 2)

        return self.widget

    # ------------------------------------------------------------------
    # callbacks
    # ------------------------------------------------------------------
    def _on_engine_changed(self, ctx, widget, text):
        self._apply_template(text)

    def _on_mode_changed(self, ctx, widget, text):
        self.settings.setValue("MeshMode", text)

    def _on_tex_check(self, ctx, widget, checked):
        self.settings.setValue("ExportTextures", "true" if checked else "false")

    def _on_tex_output_check(self, ctx, widget, checked):
        self.settings.setValue("ExportOutputTextures", "true" if checked else "false")

    def _on_fmt_changed(self, ctx, widget, text):
        self.settings.setValue("TexFormat", text)

    def _on_default_name(self, ctx, widget, checked):
        self.settings.setValue("TexDefaultName", "true" if checked else "false")
        self._set_naming_enabled(not checked)

    def _set_naming_enabled(self, enabled):
        for w in (self.tex_prefix_edit, self.tex_infix_edit, self.tex_suffix_edit):
            self.mqt.SetWidgetEnabled(w, enabled)

    def _on_tex_fbx_prefix(self, ctx, widget, checked):
        self.settings.setValue("TexFbxPrefix", "true" if checked else "false")
        # when enabled, disable the manual prefix field
        enabled = not checked and not (self.settings.value("TexDefaultName","true") == "true")
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
        self.mapper = {}
        for key, edit in self.button_dict.items():
            self.mapper[key] = m.GetWidgetText(edit)

        self.mapper["ENGINE"]           = self.settings.value("Engine",    "unity")
        self.mapper["MESH_MODE"]        = self.settings.value("MeshMode", "VS Input")
        self.mapper["EXPORT_TEXTURES"]       = m.IsWidgetChecked(self.tex_check)
        self.mapper["EXPORT_OUTPUT_TEXTURES"] = m.IsWidgetChecked(self.tex_output_check)
        self.mapper["TEX_FORMAT"]       = self.settings.value("TexFormat", "PNG")
        self.mapper["TEX_DEFAULT_NAME"] = m.IsWidgetChecked(self.default_name_check)
        self.mapper["TEX_PREFIX"]       = m.GetWidgetText(self.tex_prefix_edit)
        self.mapper["TEX_INFIX"]        = m.GetWidgetText(self.tex_infix_edit)
        self.mapper["TEX_SUFFIX"]       = m.GetWidgetText(self.tex_suffix_edit)
        self.mapper["TEX_FBX_PREFIX"]   = m.IsWidgetChecked(self.tex_fbx_prefix_check)
        self.mapper["EXPORT_SHADERS"]   = m.IsWidgetChecked(self.shader_check)
        self.mapper["SHADER_FMT"]       = self.settings.value("ShaderFmt", "Binary")
        self.mapper["SHADER_FBX_PREFIX"]= m.IsWidgetChecked(self.shader_fbx_prefix_check)
        self.mapper["SHADER_STAGES"]    = {
            k: m.IsWidgetChecked(v) for k, v in self.stage_checks.items()
        }

        m.CloseCurrentDialog(True)
