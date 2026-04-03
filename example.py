"""
example.py — Developer Quick Start for `igi2mef`

This script demonstrates how to load a model and access every 
major component: Metadata, Geometry, Bones, and Collision.
"""

import sys
from pathlib import Path
from igi2mef import parse_mef, MefDebugParams

def inspect_model(mef_path: str):
    # 1. Parse with custom debug parameters (optional)
    # Here we swizzle to XZY (OpenGL-style) and scale by 0.01
    params = MefDebugParams(v_scale=0.01, swizzle_mode="XZY")
    model = parse_mef(mef_path, debug=params)

    # 2. Safety check
    if not model.valid:
        print(f"FAILED: {model.error}")
        return

    # 3. Model Metadata
    print(f"--- Model: {model.name} ---")
    print(f"Type: {model.model_type_name} (HSEM v{model.hsem_version})")
    print(f"Stats: {model.total_vertices:,} Verts | {model.total_triangles:,} Tris")
    print(f"Size: {model.file_size_human} on disk")

    # 4. Geometry (PARTS)
    print(f"\nParts: {len(model.parts)}")
    for part in model.parts:
        print(f"  [Part {part.index}] Position: {part.position}")
        print(f"    Vertices: {len(part.vertices)} | Triangles: {len(part.faces)}")

    # 5. Skeleton (BONES) - Only for Bone models
    if model.bones:
        print(f"\nBones: {len(model.bones)}")
        for bone in model.bones[:5]: # Show first 5
            print(f"  [Bone {bone.bone_id}] {bone.name} | Parent: {bone.parent_id}")
            print(f"    World Position: {bone.world_offset}")

    # 6. Physics (COLLISION)
    if model.collision:
        print(f"\nCollision Meshes: {len(model.collision)}")
        for cm in model.collision:
            print(f"  Type {cm.mesh_type} | Verts: {len(cm.vertices)}")

    # 7. Visibility (PORTALS & GLOW)
    if model.portals:
        print(f"\nPortals: {len(model.portals)}")
    if model.glow_sprites:
        print(f"Glow Sprites: {len(model.glow_sprites)}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python example.py [model.mef]")
        sys.exit(1)
    inspect_model(sys.argv[1])
