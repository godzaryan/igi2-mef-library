"""
igi2mef.models
~~~~~~~~~~~~~~
Data classes that represent a parsed IGI 2 MEF model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ._constants import MODEL_TYPE_NAMES

# ---------------------------------------------------------------------------
# Debug Experiments Matrix
# ---------------------------------------------------------------------------

@dataclass
class MefDebugParams:
    """Dynamic parameters for coordinate and scale experiments."""
    v_scale:      float = 0.01      # Multiplier for raw vertex floats
    b_scale:      float = 0.01      # Multiplier for raw bone floats
    swizzle_mode: str   = "XZY"     # Axis mapping (e.g. "XYZ", "XZY", "YXZ", etc.)
    bone_mode:    str   = "REL"     # "REL" (to parent), "ABS" (ignore hierarchy), "ROOT" (to bone 0)
    bone_id_bias: int   = 0         # Offset applied to b_id (0, -1, 1)
    flip_x:       bool  = False
    flip_y:       bool  = False
    flip_z:       bool  = False

    def swizzle(self, x: float, y: float, z: float, scale: float) -> Tuple[float, float, float]:
        """Apply dynamic axis mapping and scaling."""
        tx, ty, tz = x, y, z
        if self.flip_x: tx = -tx
        if self.flip_y: ty = -ty
        if self.flip_z: tz = -tz
        
        mode = self.swizzle_mode.upper()
        if mode == "XZY": # Standard IGI->GL (X->X, Z->Y, Y->Z)
            return tx * scale, tz * scale, ty * scale
        elif mode == "XYZ": # No mapping
            return tx * scale, ty * scale, tz * scale
        elif mode == "YXZ": # Swap X/Y
            return ty * scale, tx * scale, tz * scale
        elif mode == "ZXY": 
            return tz * scale, tx * scale, ty * scale
        elif mode == "YZX":
            return ty * scale, tz * scale, tx * scale
        elif mode == "ZYX":
            return tz * scale, ty * scale, tx * scale
        return tx * scale, ty * scale, tz * scale

# ---------------------------------------------------------------------------
# Core Components
# ---------------------------------------------------------------------------

@dataclass
class MefBone:
    bone_id:      int
    name:         str
    parent_id:    int   # -1 = root
    local_offset: Tuple[float, float, float]
    world_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    children:     List[int] = field(default_factory=list)

@dataclass
class MagicVertex:
    index:    int
    position: Tuple[float, float, float]
    normal:   Tuple[float, float, float] = (0.0, 1.0, 0.0)
    name:     str = ""

@dataclass
class Portal:
    index:    int
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    faces:    List[Tuple[int, int, int]]       = field(default_factory=list)

@dataclass
class CollisionMesh:
    mesh_type: int
    vertices:  List[Tuple[float, float, float]] = field(default_factory=list)
    faces:     List[Tuple[int, int, int]]       = field(default_factory=list)
    spheres:   List[Tuple[float, float, float, float]] = field(default_factory=list)

@dataclass
class GlowSprite:
    index:    int
    position: Tuple[float, float, float]
    radius:   float = 1.0
    color:    Tuple[float, float, float] = (1.0, 1.0, 0.5)

@dataclass
class ChunkInfo:
    tag:    str
    offset: int
    size:   int

@dataclass
class MefPart:
    index:    int
    position: Tuple[float, float, float]
    vertices: List[Tuple[float, float, float]]
    normals:  List[Tuple[float, float, float]]
    uvs:      List[Tuple[float, float]]
    faces:    List[Tuple[int, int, int]]

    @property
    def vertex_count(self) -> int: return len(self.vertices)
    @property
    def triangle_count(self) -> int: return len(self.faces)

@dataclass
class MefModel:
    path:      Path
    valid:     bool  = False
    error:     str   = ""
    model_type:    int   = 0
    hsem_version:  float = 0.0
    hsem_game_ver: int   = 0
    parts:          List[MefPart]      = field(default_factory=list)
    chunks:         List[ChunkInfo]    = field(default_factory=list)
    bones:          List[MefBone]      = field(default_factory=list)
    magic_vertices: List[MagicVertex]  = field(default_factory=list)
    portals:        List[Portal]       = field(default_factory=list)
    collision:      List[CollisionMesh]= field(default_factory=list)
    glow_sprites:   List[GlowSprite]   = field(default_factory=list)
    file_size:       int = 0
    total_vertices:  int = 0
    total_triangles: int = 0
    bounds_min: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    bounds_max: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def name(self) -> str: return self.path.name
    @property
    def model_type_name(self) -> str:
        return MODEL_TYPE_NAMES.get(self.model_type, f"Unknown ({self.model_type})")
    @property
    def total_parts(self) -> int: return len(self.parts)
    @property
    def file_size_human(self) -> str:
        s = self.file_size
        if s < 1024: return f"{s} B"
        if s < 1024*1024: return f"{s/1024:.1f} KB"
        return f"{s/1024/1024:.2f} MB"
    @property
    def center(self) -> Tuple[float, float, float]:
        return ((self.bounds_min[0]+self.bounds_max[0])*0.5,
                (self.bounds_min[1]+self.bounds_max[1])*0.5,
                (self.bounds_min[2]+self.bounds_max[2])*0.5)
    @property
    def extents(self) -> Tuple[float, float, float]:
        return (self.bounds_max[0]-self.bounds_min[0],
                self.bounds_max[1]-self.bounds_min[1],
                self.bounds_max[2]-self.bounds_min[2])
    @property
    def radius(self) -> float:
        e = self.extents
        return max(e[0], e[1], e[2]) * 0.5 or 1.0
