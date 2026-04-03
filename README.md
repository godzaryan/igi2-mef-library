# IGI 2 MEF Parsing Library (`igi2mef`)

A high-performance, specification-driven Python library for parsing **IGI 2: Covert Strike** binary `.mef` models. Developed to be 100% accurate with the original game engine's coordinate systems, collision, and skeletal structures.

## 🚀 Quick Start

Ensure the library is installed (`pip install igi2mef`).

```python
from igi2mef import parse_mef

# 1. Load and parse a model
model = parse_mef("path/to/model.mef")

# 2. Access core metadata
if model.valid:
    print(f"Model: {model.name} ({model.model_type_name})")
    print(f"Stats: {model.total_vertices} Verts, {model.total_triangles} Tris")

    # 3. Traverse geometry (PARTS)
    for part in model.parts:
        print(f"Part {part.index} has {len(part.vertices)} vertices.")
        
    # 4. Traverse Skeleton (BONES)
    for bone in model.bones:
        print(f"Bone: {bone.name} (Parent: {bone.parent_id})")
else:
    print(f"Error loading model: {model.error}")
```

## 🛠️ Detailed API Reference

| Object | Attribute | Type | Description |
| :--- | :--- | :--- | :--- |
| **`MefModel`** | `model_type` | `int` | Raw model type ID (1=Rigid, 3=Bone, etc.). |
| | `model_type_name` | `str` | Professional name ("Rigid", "Bone", "Lightmap"). |
| | `hsem_version` | `float`| Internal HSEM specification version (e.g., 2.3). |
| | `parts` | `list` | List of `MefPart` objects (the geometry). |
| | `bones` | `list` | List of `MefBone` skeletons (if Bone model). |
| | `collision` | `list` | List of `CollisionMesh` for physics boundaries. |
| | `magic_vertices`| `list` | List of `MagicVertex` (attach points). |
| | `portals` | `list` | List of `Portal` objects (visibility logic). |
| | `glow_sprites` | `list` | List of `GlowSprite` (special FX). |
| | `bounds_min/max` | `tuple` | AABB bounding box (min/max corners). |
| | `center` | `tuple` | Computed geometric center of the model. |
| **`MefPart`** | `index` | `int` | The zero-based index of this submesh. |
| | `vertices` | `list` | List of `(x, y, z)` coordinate tuples. |
| | `faces` | `list` | List of `(v1, v2, v3)` triangle indices. |
| | `normals/uvs` | `list` | Per-vertex normal and texture coordinate data. |
| **`MefBone`** | `bone_id` | `int` | The bone's unique index. |
| | `parent_id` | `int` | Parent index (-1 for root). |
| | `local_offset` | `tuple` | Original relative offset. |
| | `world_offset` | `tuple` | Computed absolute position in object space. |

## 🧪 Debug & Experiments Matrix

The `parse_mef` function accepts an optional `debug` parameter (`MefDebugParams`) to handle coordinate system swizzling or scaling for different 3D engines (GL, DirectX, Unity).

```python
from igi2mef import parse_mef, MefDebugParams

params = MefDebugParams(
    v_scale=0.01,       # Scale vertices (1 IGI unit = 100 units)
    swizzle_mode="XZY", # Common IGI->OpenGL mapping
    flip_x=False,
    bone_id_bias=0      # Offset bone indices for certain rigs
)

model = parse_mef("anya_01.mef", debug=params)
```

## 📖 MEF Specification
For a deeper, byte-level look at the `.mef` file format, refer to [guidemef.md](guidemef.md).

## License
MIT License. **IGI 2: Covert Strike** is a trademark of Innerloop Studios. This library is for educational and modding purposes only.
