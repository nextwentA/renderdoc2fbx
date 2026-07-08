# renderdoc2fbx

RenderDoc Python extension for exporting mesh geometry, textures and shaders.

## Installation

Copy the `timmyliang` folder to `%appdata%\qrenderdoc\extensions`.

On Windows you can run `install.bat` to do this automatically.

## Features

### Mesh Export

Supports two output formats selectable from the dialog:

| Format | Notes |
|--------|-------|
| **FBX ASCII** | RenderDoc-native, supported by Maya/3dsMax/Unity/Unreal importers |
| **Wavefront OBJ** | Universal format; Blender, Houdini, etc. open it natively without FBX SDK |

Exported vertex channels:

- **Vertex Position**
- **Normal**
- **Tangent** / **BiNormal**
- **Vertex Color**
- **UV0** / **UV1**

Engine coordinate presets: **Unity**, **Unreal Engine**, **Godot**

Mesh modes: **VS Input** (raw mesh) or **VS Output** (post-vertex-shader, reconstructed from clip space)

### Convenience Features

| Feature | Description |
|---------|-------------|
| **Auto-detect Attributes** | The dialog scans the current Mesh Viewer table and shows available attribute names. Click **Auto-detect Attributes** to fill the mapping fields automatically. |
| **Quick Export** | Second menu item — skips the dialog entirely, uses the last saved settings, and only prompts for the output file path. |
| **UV Flip Control** | Independent **Flip U** / **Flip V** checkboxes (V-flip on by default for DX→OBJ/FBX convention). |
| **Texture Export** | Saves all input textures bound at the current draw call. |
| **Output Texture Export** | Saves render targets (color + depth) bound at the current draw call. |
| **Shader Export** | Saves VS / PS / GS / HS / DS / CS shaders as binary or disassembled text. |

### Settings Persistence

All dialog options are saved between sessions in a per-user INI file  
(`%TEMP%\RenderDoc_QueryDialog.ini`), so your last configuration is always  
restored when you re-open the dialog.

---

## Usage

1. Open RenderDoc and load a capture.  
2. Navigate to a draw call in the Event Browser.  
3. Open the **Mesh Viewer** panel.  
4. Click the **Extension** icon in the toolbar → choose one of:
   - **Export Mesh** — opens the full options dialog.  
   - **Quick Export (last settings)** — exports immediately using last options.
5. In **Export Mesh** dialog:
   - Choose **Engine** preset to auto-fill attribute names, *or*  
     click **Auto-detect Attributes** to fill from the live mesh table.  
   - Select **Format** (FBX / OBJ).  
   - Adjust UV flip, texture, and shader options as needed.  
   - Click **OK**, then choose an output path.
6. The output folder opens automatically on success.

![Export dialog location](image/03.png)

---

## Attribute Mapping Quick Reference

### Unity

| Channel  | Attribute  |
|----------|-----------|
| Position | `POSITION` |
| Normal   | `NORMAL`   |
| Tangent  | `TANGENT`  |
| UV0      | `TEXCOORD0`|
| UV1      | `TEXCOORD1`|
| Color    | `COLOR`    |

### Unreal Engine

| Channel  | Attribute    |
|----------|-------------|
| Position | `ATTRIBUTE0` |
| Normal   | `ATTRIBUTE2` |
| Tangent  | `ATTRIBUTE1` |
| UV0      | `ATTRIBUTE5` |
| UV1      | `ATTRIBUTE6` |
| Color    | `ATTRIBUTE13`|

### Godot

| Channel  | Attribute  |
|----------|-----------|
| Position | `VERTEX`   |
| Normal   | `NORMAL`   |
| Tangent  | `TANGENT`  |
| BiNormal | `BINORMAL` |
| UV0      | `UV`       |
| UV1      | `UV2`      |
| Color    | `COLOR`    |

---

## Changelog

### v1.1.0
- **NEW** Wavefront OBJ export format (universal DCC compatibility).
- **NEW** Quick Export menu item — re-exports with last settings, no dialog.
- **NEW** Auto-detect vertex attributes from the live Mesh Viewer table.
- **NEW** Godot engine coordinate preset.
- **NEW** Per-axis UV flip controls (Flip U / Flip V).
- Refactored shared mesh-data collection into `_collect_mesh_data` helper.
- Success dialog now shows export format name.

### v1.0.1
- Added texture (input/output) and shader export.
- Optimised dialog UI layout.

### v1.0.0
- Initial release: FBX ASCII export with Unity/Unreal presets.
