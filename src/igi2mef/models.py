"""
igi2mef.models
~~~~~~~~~~~~~~
Data classes that represent a parsed IGI 2 MEF model.

These are plain Python objects — no rendering, no I/O.
All coordinates are returned in **Y-up** space
(X = right, Y = up, Z = toward viewer) at viewer scale
(IGI world units × 0.01).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from ._constants import MODEL_TYPE_NAMES


# ---------------------------------------------------------------------------
# Skeletal Bone Hierarchy (Dynamic Models)
# ---------------------------------------------------------------------------

@dataclass
class MefBone:
    """A single bone node from a Dynamic Model's HPRM/REIH/MANB chunks."""
    bone_id:      int
    name:         str
    parent_id:    int   # -1 = root
    local_offset: Tuple[float, float, float]
    world_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    children:     List[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Magic Vertices (Attachment / Effect Points)
# ---------------------------------------------------------------------------

@dataclass
class MagicVertex:
    """
    An XTVM magic vertex — a named attachment or effect-spawning point.

    Attributes
    ----------
    index : int
        Zero-based index into the XTVM chunk.
    position : tuple of 3 floats
        World-space position (Y-up, viewer scale).
    normal : tuple of 3 floats
        Surface normal at the vertex (Y-up).
    name : str
        Optional name decoded from the payload, blank if unavailable.
    """
    index:    int
    position: Tuple[float, float, float]
    normal:   Tuple[float, float, float] = (0.0, 1.0, 0.0)
    name:     str = ""


# ---------------------------------------------------------------------------
# Portals
# ---------------------------------------------------------------------------

@dataclass
class Portal:
    """
    One portal polygon from the TROP/XVTP/CFTP chunks.

    Portals define visibility zones used by the IGI 2 engine for
    occlusion culling.
    """
    index:    int
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    faces:    List[Tuple[int, int, int]]       = field(default_factory=list)


# ---------------------------------------------------------------------------
# Collision Mesh
# ---------------------------------------------------------------------------

@dataclass
class CollisionMesh:
    """
    A collision geometry set parsed from XTVC + ECFC chunks.

    IGI 2 stores two independent collision mesh sets per model
    (type-0 and type-1).
    """
    mesh_type: int   # 0 or 1
    vertices:  List[Tuple[float, float, float]] = field(default_factory=list)
    faces:     List[Tuple[int, int, int]]       = field(default_factory=list)
    spheres:   List[Tuple[float, float, float, float]] = field(default_factory=list)  # (cx,cy,cz,r)


# ---------------------------------------------------------------------------
# Glow Sprites
# ---------------------------------------------------------------------------

@dataclass
class GlowSprite:
    """
    A glow/lens-flare sprite from the WOLG chunk.
    """
    index:    int
    position: Tuple[float, float, float]
    radius:   float = 1.0
    color:    Tuple[float, float, float] = (1.0, 1.0, 0.5)


# ---------------------------------------------------------------------------
# Chunk metadata
# ---------------------------------------------------------------------------

@dataclass
class ChunkInfo:
    """
    Describes one four-CC chunk found inside the ILFF container.

    Attributes
    ----------
    tag : str
        Four-character chunk identifier (e.g. ``"XTRV"``).
    offset : int
        Byte offset of the chunk header from the start of the file.
    size : int
        Payload size in bytes (not including the 16-byte header).
    """
    tag:    str
    offset: int
    size:   int

    def __repr__(self) -> str:
        return f"ChunkInfo(tag={self.tag!r}, offset=0x{self.offset:08X}, size={self.size:,})"


# ---------------------------------------------------------------------------
# A single mesh part (sub-object) inside a model
# ---------------------------------------------------------------------------

@dataclass
class MefPart:
    """
    One mesh partition inside a MEF model.

    IGI 2 splits a model into several *parts*, each with its own
    world-space origin and a sub-set of the global vertex pool.
    """
    index:    int
    position: Tuple[float, float, float]
    vertices: List[Tuple[float, float, float]]
    normals:  List[Tuple[float, float, float]]
    uvs:      List[Tuple[float, float]]
    faces:    List[Tuple[int, int, int]]

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def triangle_count(self) -> int:
        return len(self.faces)

    @property
    def bounds(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        if not self.vertices:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        xs = [v[0] for v in self.vertices]
        ys = [v[1] for v in self.vertices]
        zs = [v[2] for v in self.vertices]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def __repr__(self) -> str:
        return f"MefPart(index={self.index}, verts={self.vertex_count}, tris={self.triangle_count})"


# ---------------------------------------------------------------------------
# The top-level model
# ---------------------------------------------------------------------------

@dataclass
class MefModel:
    """A fully-parsed IGI 2 binary MEF model."""

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
    def name(self) -> str:
        return self.path.name

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def total_parts(self) -> int:
        return len(self.parts)

    @property
    def model_type_name(self) -> str:
        return MODEL_TYPE_NAMES.get(self.model_type, f"Unknown (type {self.model_type})")

    @property
    def center(self) -> Tuple[float, float, float]:
        return (
            (self.bounds_min[0] + self.bounds_max[0]) * 0.5,
            (self.bounds_min[1] + self.bounds_max[1]) * 0.5,
            (self.bounds_min[2] + self.bounds_max[2]) * 0.5,
        )

    @property
    def extents(self) -> Tuple[float, float, float]:
        return (
            self.bounds_max[0] - self.bounds_min[0],
            self.bounds_max[1] - self.bounds_min[1],
            self.bounds_max[2] - self.bounds_min[2],
        )

    @property
    def radius(self) -> float:
        e = self.extents
        return max(e[0], e[1], e[2]) * 0.5 or 1.0

    @property
    def file_size_human(self) -> str:
        s = self.file_size
        if s < 1024:       return f"{s} B"
        if s < 1024 * 1024: return f"{s / 1024:.1f} KB"
        return f"{s / 1024 / 1024:.2f} MB"

    def get_chunk(self, tag: str) -> Optional[ChunkInfo]:
        for c in self.chunks:
            if c.tag == tag:
                return c
        return None

    def __repr__(self) -> str:
        status = "valid" if self.valid else f"invalid: {self.error}"
        return (f"MefModel({self.name!r}, parts={self.total_parts}, "
                f"verts={self.total_vertices}, tris={self.total_triangles}, "
                f"bones={len(self.bones)}, magic_verts={len(self.magic_vertices)}, "
                f"{status})")
