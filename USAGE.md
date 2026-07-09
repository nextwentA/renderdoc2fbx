# RenderDoc FBX/OBJ Mesh Exporter — 使用说明与技术摘要

---

## 一、安装

运行 `install.bat`，将 `timmyliang/` 目录复制到  
`%APPDATA%\qrenderdoc\extensions\`。

重启 RenderDoc 后，在 **Mesh Viewer** 面板右键菜单（或工具栏扩展菜单）中出现：

| 菜单项 | 说明 |
|--------|------|
| **Export Mesh** | 打开完整配置对话框，逐项设置后导出 |
| **Quick Export (last settings)** | 跳过对话框，直接使用上次保存的配置导出 |

---

## 二、对话框功能说明

### 2.1 Mesh Export（网格导出）

| 控件 | 选项 | 说明 |
|------|------|------|
| **Engine** | unity / unreal / godot | 引擎预设，自动填充属性名映射 |
| **VS Input** | ☑ checkbox | 导出顶点着色器输入数据（模型原始顶点，Object Space） |
| **VS Output** | ☑ checkbox | 导出顶点着色器输出数据（经 VS 变换后，重建到 View Space） |
| **Format** | FBX / OBJ | 输出格式 |

> VS Input 和 VS Output **可同时勾选**；同时勾选时输出文件名自动加 `_vsin`/`_vsout` 后缀。  
> 两者都不勾选时点 OK 会报错提醒。

---

### 2.2 VS Output Extras（VS Output 附加通道）

VS Output 顶点位置来自裁剪空间重建，本节控制从 **VS Input** 中提取哪些通道写入 VS Output 的 FBX，使 DCC 工具无需二次导入即可得到完整材质数据。

| checkbox | 说明 |
|----------|------|
| UV / UV2 | 从 VS Input 读取 UV 坐标写入 VS Output FBX |
| Normal | 从 VS Input 读取法线 |
| Tangent / BiNormal | 从 VS Input 读取切线 / 副法线 |
| Color | 从 VS Input 读取顶点颜色 |
| **Bake World** | 将 VS Output 顶点从 View Space 变换回 World Space（需要 View Matrix） |
| **Skin Weights** | 扫描顶点缓冲区中的骨骼权重/骨骼索引并写入 FBX Skin Deformer |

---

### 2.3 批量 EID 导出

**批量EID** 输入框格式：`448,456-470,500`

- 逗号分隔单个 EID
- 连字符表示范围（含两端）
- 填写后点 OK → 选择一个输出目录 → 每个 EID 在该目录下建子文件夹 `eid_NNNNN/`

批量导出流程与单次完全相同：  
`SetEventID` 导航 → Mesh Viewer 表格更新 → 读表格数据 → 导出 FBX/OBJ + 贴图 + Shader

> 导出完成后 UI 自动恢复到批量开始前的 EID，不影响当前工作状态。  
> 导出失败（无顶点数据）的 EID 子文件夹会被自动删除。

---

### 2.4 属性映射（Attribute Mapping）

7 个手动输入框，分别对应：

| 映射键 | 含义 |
|--------|------|
| Position | 顶点位置 |
| Normal | 法线 |
| Tangent | 切线 |
| BiNormal | 副法线 |
| Color | 顶点颜色 |
| UV | 第一套 UV |
| UV2 | 第二套 UV |

填写对应的属性名（如 Unreal 的 `ATTRIBUTE0`、Unity 的 `POSITION`）。

**Auto-detect Attributes** 按钮：自动扫描当前 Mesh Viewer 表格的列名，按启发式规则填入。

---

### 2.5 UV Options

| checkbox | 默认 | 说明 |
|----------|------|------|
| **Flip U** | ☐ 关 | 对 U 坐标执行 `1 - u` |
| **Flip V** | ☑ 开 | 对 V 坐标执行 `1 - v`（DX 到 OpenGL/FBX 约定转换） |

两项独立控制，对 UV0 和 UV2 同时生效。

---

### 2.6 Texture Export（贴图导出）

| 控件 | 说明 |
|------|------|
| Export Inputs | 导出当前 Draw Call 绑定的所有输入贴图 |
| Export Outputs | 导出当前 Draw Call 绑定的 Render Target / Depth |
| Tex Format | PNG / DDS / TGA / BMP / HDR / EXR |
| Default Name | 使用 RenderDoc 内置名称（不可自定义前缀/后缀） |
| FBX Name Prefix | 以 FBX 文件名为前缀命名贴图 |
| Prefix / Infix / Suffix | 贴图文件名的自定义前缀、中缀、后缀 |

导出的贴图保存在与 FBX 同一目录，FBX 内自动建立 Material + Texture 节点连接（Phong 材质，Diffuse / NormalMap / Roughness / Emissive 自动分类）。

---

### 2.7 Shader Export（着色器导出）

| 控件 | 说明 |
|------|------|
| Export Shaders | 总开关 |
| Format | Binary（原始二进制）/ Disasm txt（反汇编文本） |
| FBX Name Prefix | 以 FBX 文件名为前缀 |
| VS / PS / GS / HS / DS / CS | 选择要导出的着色器阶段 |

---

## 三、引擎属性名预设

### Unity
| 通道 | 属性名 |
|------|--------|
| Position | `POSITION` |
| Normal | `NORMAL` |
| Tangent | `TANGENT` |
| UV0 | `TEXCOORD0` |
| UV1 | `TEXCOORD1` |
| Color | `COLOR` |

### Unreal Engine
| 通道 | 属性名 |
|------|--------|
| Position | `ATTRIBUTE0` |
| Normal | `ATTRIBUTE2` |
| Tangent | `ATTRIBUTE1` |
| UV0 | `ATTRIBUTE5` |
| UV1 | `ATTRIBUTE6` |
| Color | `ATTRIBUTE13` |

### Godot
| 通道 | 属性名 |
|------|--------|
| Position | `VERTEX` |
| Normal | `NORMAL` |
| Tangent | `TANGENT` |
| BiNormal | `BINORMAL` |
| UV0 | `UV` |
| UV1 | `UV2` |
| Color | `COLOR` |

---

## 四、设置持久化

所有对话框选项保存在：  
`%TEMP%\RenderDoc_QueryDialog.ini`

下次打开插件时自动恢复上次配置。

---

---

# 技术点摘要

## T1 — 数据读取路径

### VS Input（单次 / 批量）

```
Mesh Viewer 表格 (Qt QTableView)
  └─ _collect_mesh_data(main_window)
       ├─ 扫描列名 "ATTR.x/.y/.z" → data[attr][row] = [x,y,z]
       ├─ IDX 列（无"."）→ data["IDX"] = [顶点索引序列]
       └─ float() 转换所有分量
  └─ _add_vsin_aliases(data, attr_list)
       ├─ _inputN ↔ ATTRIBUTE{N} 双向别名
       └─ 语义别名: POSITION←_input0, TEXCOORD0←_input3 …
  └─ export_fbx / export_obj
```

**批量时**，先调用 `pyrenderdoc.SetEventID([], eid, eid)` 导航，  
再循环 `QApplication.processEvents()` 等待 Mesh Viewer 表格填充完毕（最多 2 秒），  
然后走与单次完全相同的读取路径。

### VS Output

```
BlockInvoke → controller.GetPostVSData(0, 0, VSOut)
  ├─ 读 clip-space SV_Position (xyzw)
  ├─ 反透视除法: xyz_ndc = xyz_clip / w
  ├─ 从 NDC 反投影回 View Space: z_view = near*far/(far - ndc_z*(far-near))
  │     x_view = ndc_x * z_view / proj_m[0][0]
  │     y_view = ndc_y * z_view / proj_m[1][1]  
  ├─ 可选 Bake World: view_pos * inv(ViewMatrix)
  └─ 索引缓冲区：GetPostVSData(VSOut) 的 index buffer
```

VS Input 通道（UV / Normal 等）从 VS Input 表格数据中按同名索引提取，  
写入 VS Output FBX 的对应 LayerElement。

---

## T2 — FBX ASCII 结构

```
Definitions → Geometry + Model + Deformer 对象类型声明
Objects
  ├─ Geometry (Mesh)
  │     ├─ Vertices, PolygonVertexIndex
  │     ├─ LayerElementNormal  (ByPolygonVertex, Direct)
  │     ├─ LayerElementBinormal / Tangent (ByPolygonVertex)
  │     ├─ LayerElementColor   (ByPolygonVertex, IndexToDirect)
  │     ├─ LayerElementUV      (ByPolygonVertex, IndexToDirect)
  │     └─ LayerElementUV (map2)
  ├─ Model (Node)
  ├─ Material (Phong) — 自动绑定同目录贴图
  ├─ Texture × N
  └─ Skin + Cluster × 骨骼数（可选）
Connections: Model→Root, Geometry→Model, Material→Model, Texture→Material
```

- 多边形索引：最后一个顶点写负数 `-(i+1)`（FBX 规范）
- 顶点坐标与 RenderDoc Mesh Viewer 完全一致，不做任何旋转/缩放变换
- UV Flip: `u' = 1 - u`（Flip U），`v' = 1 - v`（Flip V）

---

## T3 — 骨骼权重导出

```
BlockInvoke → GetPipelineState().GetVertexBuffers()
  └─ _scan_bone_data(vb_data, stride, nv, nat_cum)
       ├─ 扫描顶点步长中 nat_cum 之后的"额外区域"
       ├─ BoneWeights: N个float/uint8，各值∈[0,1]，求和≈1.0
       ├─ BoneIndices: N个uint8/uint16，值为小整数（骨骼索引）
       └─ 输出 weights_list, indices_list
  └─ _build_fbx_skin(weights, indices, n_verts)
       └─ 生成 Skin + Cluster 节点（每骨骼一个 Cluster，含权重列表）
```

骨骼没有世界矩阵，仅输出权重绑定，导入 DCC 后需手动关联骨骼层级。

---

## T4 — 批量导出细节

```
prepare_export
  └─ _parse_eids("448,456-470") → [448,456,457,…,470]
  └─ _batch_eid_export(eids, out_dir, mapper, pyrenderdoc, info_list)
       └─ for eid in eids:
            mkdir eid_NNNNN/
            SetEventID([], eid, eid)           # UI 级别导航
            loop processEvents() until rowCount > 0  # 等表格更新
            _collect_mesh_data → _add_vsin_aliases
            export_fbx/obj  (VS Input, ctrl=None)
            BlockInvoke → _export_vsout_fbx    (VS Output, 需 replay 线程)
            _run_secondary_exports              (贴图 + Shader)
            失败 → 删除空目录
       └─ finally: SetEventID 恢复原始 EID
```

---

## T5 — 对话框架构

```
QDialog (PySide2, exec() 模式)
  └─ QScrollArea → QWidget → QGridLayout
       ├─ MiniQtHelper widget (Checkbox / Combo / TextBox)
       │    由 RenderDoc 扩展 API 创建，回调在扩展上下文中执行
       └─ PySide2 widget (QLabel, QWidget 容器行)
            用于布局复合行（多 checkbox 并排）
```

- **MiniQtHelper** 负责与 RenderDoc 内部事件系统的交互（checkbox 状态、文本输入回调）
- **PySide2** 负责外层 Dialog 结构、ScrollArea、布局管理
- 所有配置通过 `QSettings` 持久化，key 对应各控件的 `setting_key`

---

## T6 — VS Output 裁剪空间位置重建

```
clip = (cx, cy, cz, cw)   ← SV_Position from VS Output buffer
ndc  = (cx/cw, cy/cw, cz/cw)

z_view = (near * far) / (far - ndc_z * (far - near))
x_view = ndc_x * (-z_view) / proj[0][0]   # -z 因为 RenderDoc 使用右手坐标系
y_view = ndc_y * (-z_view) / proj[1][1]

若 Bake World Space:
  world = inv(ViewMatrix) × (x_view, y_view, z_view, 1)
```

投影矩阵从 `GetPipelineState().GetViewport()` + `CameraProperties` 推算，  
若无法获取则 fallback 到 NDC 坐标直出。

---

## T7 — 贴图与 Shader 导出

```
_run_secondary_exports(eid_dir, mapper, pyrenderdoc)
  ├─ _export_textures (输入贴图)
  │     BlockInvoke → GetShaderReflection → bound textures
  │     SaveTexture(texture_id, path, format)
  ├─ _export_output_textures (RT / Depth)
  │     GetFramebufferAttachments → SaveTexture
  └─ _export_shaders
        BlockInvoke → GetShaderReflection
        GetShaderBytecode → 写 .spv/.dxbc / 反汇编文本
```

---

## T8 — 关键约束与已知限制

| 项目 | 说明 |
|------|------|
| 坐标系 | 导出原始 GPU buffer 坐标，无引擎变换；3dsMax 导入后按需手动旋转 |
| UV Seam | 每个顶点只存第一次出现的 UV（`if idx not in vertex_data`），UV 缝合线可能丢失 |
| 骨骼矩阵 | 不包含骨骼世界矩阵，只有权重绑定关系 |
| VS Output | 仅重建位置，不输出 VS Output 法线（法线仍来自 VS Input） |
| 批量导航 | 依赖 `SetEventID` + `processEvents()` 等待 Mesh Viewer 更新，极少数情况下可能超时（2 秒）报告空数据 |
| 多实例 | `GetPostVSData(0, 0, ...)` 固定读取第 0 实例，GPU Instancing 场景只导出第一个实例 |
