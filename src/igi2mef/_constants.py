"""
igi2mef._constants
~~~~~~~~~~~~~~~~~~
All binary-format constants for the IGI 2 MEF model format.
Verified from io_scene_igi2_mef.py — zero assumptions made.
"""

# File magic
MAGIC_ILFF: bytes = b"ILFF"

# Scale: IGI world units → normalised viewer units
SCALE: float = 0.01
INV_SCALE: float = 100.0

# Per-model-type vertex stride (bytes)
XTRV_STRIDE: dict = {0: 32, 1: 40, 2: 44, 3: 28}

# Byte offset of the position vector inside one XTRV vertex record
XTRV_POS_OFF: dict = {0: 0, 1: 0, 2: 0, 3: 0}

# Byte offset of the normal vector inside one XTRV vertex record
XTRV_NORM_OFF: dict = {0: 12, 1: 12, 2: 20, 3: 20}

# Byte offset of the primary UV pair inside one XTRV vertex record
XTRV_UV1_OFF: dict = {0: 24, 1: 24, 2: 32, 3: 12}

# Per-model-type DNER (part-descriptor) record stride (bytes)
DNER_STRIDE: dict = {0: 32, 1: 32, 2: 32, 3: 28}

# Human-readable names for each model type
MODEL_TYPE_NAMES: dict = {
    0: "Standard (Rigid)",
    1: "Extended (Bone/Dynamic)",
    2: "Extended UV2 (Lightmap)",
    3: "Compact (Shadow)",
}

# All chunk four-character codes we know about
KNOWN_CHUNK_TAGS: list = [
    # --- Core Render ---
    b"HSEM",  # Mesh header / model metadata
    b"D3DR",  # Render descriptor (mesh count etc.)
    b"DNER",  # Part descriptors (position, index ranges)
    b"XTRV",  # Vertex pool (pos + normal + UV)
    b"ECAF",  # Face index list (triangle indices)
    b"PMTL",  # Render Mesh Lightmaps
    b"XTXM",  # Texture map references (optional)
    b"TCST",  # Texture coordinate sets (optional)
    # --- Skeleton / Bones ---
    b"REIH",  # Bone Hierarchy (parent index table)
    b"MANB",  # Bone Names (fixed 16-char strings)
    b"HPRM",  # Bone Parameters (local translation + rotation)
    # --- Magic Vertices ---
    b"XTVM",  # Magic Vertex List (attachment points)
    b"ATTA",  # Attachment definitions
    # --- Portals ---
    b"TROP",  # Portal Definition
    b"XVTP",  # Portal Vertices
    b"CFTP",  # Portal Faces
    # --- Collision Mesh ---
    b"HSMC",  # Collision Mesh Header
    b"XTVC",  # Collision Mesh Vertices
    b"ECFC",  # Collision Mesh Faces
    b"TAMC",  # Collision Mesh Materials
    b"HPSC",  # Collision Mesh Spheres
    # --- Glow Sprites ---
    b"WOLG",  # Glow Sprite List
    # --- Shadow Mesh ---
    b"SEMS",  # Shadow Mesh Header (mesh ranges)
    b"XTVS",  # Shadow Vertices (position only)
    b"CAFS",  # Shadow Faces (indices + normals)
    b"EGDE",  # Shadow Edges (vertex pairs)
    # --- Other ---
    b"LLUN",  # Null / terminator chunk (optional)
    b"XTRN",  # External reference (optional)
    b"NHSA",  # Animation skeleton hint (optional)
]

# Byte offset in D3DR payload where mesh_count lives (type-dependent)
D3DR_MESH_COUNT_OFFSET: dict = {
    0: 8, 1: 8, 2: 8, 3: 12,
}
# --- Shadow Model Specifics (from MEF.md) ---
SEMS_STRIDE: int = 28
XTVS_STRIDE: int = 12
CAFS_STRIDE: int = 28
EGDE_STRIDE: int = 8
