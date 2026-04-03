"""
igi2mef.parser
~~~~~~~~~~~~~~
Core parsing logic for IGI 2 binary MEF files.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ._constants import (
    CAFS_STRIDE,
    D3DR_MESH_COUNT_OFFSET,
    DNER_STRIDE,
    EGDE_STRIDE,
    KNOWN_CHUNK_TAGS,
    MAGIC_ILFF,
    SCALE,
    SEMS_STRIDE,
    XTRV_NORM_OFF,
    XTRV_POS_OFF,
    XTRV_STRIDE,
    XTRV_UV1_OFF,
    XTVS_STRIDE,
)
from .exceptions import MefParseError, MefValidationError
from .models import (
    ChunkInfo, CollisionMesh, GlowSprite, MagicVertex,
    MefBone, MefModel, MefPart, Portal,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_chunk(data: bytes, tag: bytes) -> Tuple[Optional[bytes], int]:
    """Locate the first occurrence of *tag* and return its payload."""
    idx = data.find(tag)
    if idx == -1:
        return None, -1
    if idx + 16 > len(data):
        return None, idx
    size  = struct.unpack_from("<I", data, idx + 4)[0]
    start = idx + 16
    end   = start + size
    return data[start: min(end, len(data))], idx


def _read_all_chunks(data: bytes, tag: bytes) -> List[bytes]:
    """Return payloads for ALL occurrences of *tag* (e.g. repeated XTVC)."""
    results = []
    pos = 0
    while True:
        idx = data.find(tag, pos)
        if idx == -1:
            break
        if idx + 16 > len(data):
            break
        size  = struct.unpack_from("<I", data, idx + 4)[0]
        start = idx + 16
        end   = start + size
        results.append(data[start: min(end, len(data))])
        pos = idx + 1
    return results


def _scan_all_chunks(data: bytes) -> List[ChunkInfo]:
    """Build a sorted list of every recognised ILFF chunk in *data*."""
    chunks: List[ChunkInfo] = []
    seen_tags = set()
    for tag in KNOWN_CHUNK_TAGS:
        pos = 0
        while True:
            idx = data.find(tag, pos)
            if idx == -1:
                break
            if idx + 8 <= len(data):
                size = struct.unpack_from("<I", data, idx + 4)[0]
                chunks.append(ChunkInfo(tag=tag.decode("latin-1"),
                                        offset=idx, size=size))
            pos = idx + 1
    chunks.sort(key=lambda c: c.offset)
    return chunks


def _swizzle(x: float, y: float, z: float) -> Tuple[float, float, float]:
    """IGI (X,Y,Z) → Y-up OpenGL (X, -Z, Y) with viewer scale."""
    return x * SCALE, -z * SCALE, y * SCALE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def quick_validate(path) -> bool:
    """Return ``True`` if *path* looks like an IGI 2 binary MEF file."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == MAGIC_ILFF
    except OSError:
        return False


def parse_mef(path, raise_on_error: bool = False) -> MefModel:
    """Fully parse an IGI 2 binary MEF file and return a :class:`~igi2mef.MefModel`."""
    path  = Path(path).resolve()
    model = MefModel(path=path)

    def _fail(reason: str) -> MefModel:
        model.error = reason
        if raise_on_error:
            raise MefParseError(reason, str(path))
        return model

    try:
        model.file_size = os.path.getsize(path)
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return _fail(f"Cannot read file: {exc}")

    # ── Magic ──────────────────────────────────────────────────────────────────
    if len(data) < 20 or data[:4] != MAGIC_ILFF:
        return _fail("Not a valid IGI 2 MEF file (ILFF magic not found)")

    # ── Chunk inventory ────────────────────────────────────────────────────────
    model.chunks = _scan_all_chunks(data)

    # ── HSEM — model header ───────────────────────────────────────────────────
    hsem_data, _ = _read_chunk(data, b"HSEM")
    if hsem_data is None:
        # If HSEM is missing, check if this is a shadow model (SEMS chunk present)
        sems_data, _ = _read_chunk(data, b"SEMS")
        if sems_data:
            model.model_type = 3  # Shadow model
            _parse_shadow_model(data, model)
            _parse_skeleton(data, model)  # Character shadows can have bones
            return model
        return _fail("Missing HSEM chunk")

    model_type = 0
    if len(hsem_data) >= 4:
        model.hsem_version  = struct.unpack_from("<f", hsem_data, 0)[0]
    if len(hsem_data) >= 8:
        model.hsem_game_ver = struct.unpack_from("<I", hsem_data, 4)[0]
    if len(hsem_data) >= 36:
        raw_type   = struct.unpack_from("<I", hsem_data, 32)[0]
        model_type = raw_type if raw_type in XTRV_STRIDE else 0

    model.model_type = model_type
    stride      = XTRV_STRIDE[model_type]
    pos_off     = XTRV_POS_OFF[model_type]
    norm_off    = XTRV_NORM_OFF[model_type]
    uv_off      = XTRV_UV1_OFF[model_type]
    dner_stride = DNER_STRIDE[model_type]
    mc_off      = D3DR_MESH_COUNT_OFFSET[model_type]

    # ── D3DR — render descriptor ───────────────────────────────────────────────
    d3dr_data, _ = _read_chunk(data, b"D3DR")
    if d3dr_data is None:
        return _fail("Missing D3DR chunk")
    if len(d3dr_data) < mc_off + 4:
        return _fail("D3DR chunk is too small to contain a mesh count")

    mesh_count = struct.unpack_from("<I", d3dr_data, mc_off)[0]
    if mesh_count == 0 or mesh_count > 65535:
        return _fail(f"Implausible mesh count: {mesh_count}")

    # ── DNER — part descriptors ────────────────────────────────────────────────
    dner_data, _ = _read_chunk(data, b"DNER")
    if dner_data is None:
        return _fail("Missing DNER chunk")

    parts_meta = []
    for i in range(mesh_count):
        base = i * dner_stride
        if base + 20 > len(dner_data):
            break
        px, py, pz = struct.unpack_from("<fff", dner_data, base + 4)
        idx_start, tri_count = struct.unpack_from("<HH", dner_data, base + 16)
        parts_meta.append({"pos": (px, py, pz),
                            "idx_start": idx_start,
                            "tri_count": tri_count})

    # ── XTRV — vertex pool ────────────────────────────────────────────────────
    xtrv_data, _ = _read_chunk(data, b"XTRV")
    if xtrv_data is None:
        return _fail("Missing XTRV chunk")

    pool_size = len(xtrv_data) // stride
    v_raw: List[Tuple] = []
    n_raw: List[Tuple] = []
    u_raw: List[Tuple] = []

    for i in range(pool_size):
        b = i * stride
        vx, vy, vz = struct.unpack_from("<fff", xtrv_data, b + pos_off)
        nx, ny, nz = (struct.unpack_from("<fff", xtrv_data, b + norm_off)
                      if b + norm_off + 12 <= len(xtrv_data) else (0.0, 0.0, 1.0))
        uv = (struct.unpack_from("<ff", xtrv_data, b + uv_off)
              if b + uv_off + 8 <= len(xtrv_data) else (0.0, 0.0))
        bone_id = 0
        if stride >= 40 and b + 37 < len(xtrv_data):
            bone_id = struct.unpack_from("<B", xtrv_data, b + 36)[0]
        v_raw.append((vx, vy, vz, bone_id))
        n_raw.append((nx, ny, nz))
        u_raw.append(uv)

    # ── ECAF — face index list ─────────────────────────────────────────────────
    ecaf_data, _ = _read_chunk(data, b"ECAF")
    if ecaf_data is None:
        return _fail("Missing ECAF chunk")

    # ── Skeleton (REIH + MANB) ────────────────────────────────────────────────
    _parse_skeleton(data, model)

    # ── Magic Vertices (XTVM) ─────────────────────────────────────────────────
    _parse_magic_vertices(data, model)

    # ── Portals (TROP + XVTP + CFTP) ─────────────────────────────────────────
    _parse_portals(data, model)

    # ── Collision Mesh (HSMC + XTVC + ECFC + HPSC) ──────────────────────────
    _parse_collision(data, model)

    # ── Glow Sprites (WOLG) ───────────────────────────────────────────────────
    _parse_glow_sprites(data, model)

    # ── Build per-part geometry ────────────────────────────────────────────────
    all_viewer_verts: List[Tuple] = []

    for i, meta in enumerate(parts_meta):
        ox, oy, oz = meta["pos"]
        byte_start  = meta["idx_start"] * 2
        tri_count   = meta["tri_count"]

        used: set = set()
        for t in range(tri_count):
            b = byte_start + t * 6
            if b + 6 > len(ecaf_data):
                break
            i0, i1, i2 = struct.unpack_from("<HHH", ecaf_data, b)
            used.add(i0); used.add(i1); used.add(i2)

        if not used:
            continue

        unique  = sorted(used)
        idx_map = {old: new for new, old in enumerate(unique)}

        local_verts:   List[Tuple] = []
        local_normals: List[Tuple] = []
        local_uvs:     List[Tuple] = []

        for gi in unique:
            if gi >= len(v_raw):
                continue
            vx, vy, vz, b_id = v_raw[gi]
            nx, ny, nz = n_raw[gi]
            u, v = u_raw[gi]
            dx, dy, dz = _swizzle(vx, vy, vz)
            local_verts.append((dx, dy, dz))
            local_normals.append(_swizzle(nx, ny, nz))
            local_uvs.append((u, 1.0 - v))

        local_faces: List[Tuple] = []
        for t in range(tri_count):
            b = byte_start + t * 6
            if b + 6 > len(ecaf_data):
                break
            i0, i1, i2 = struct.unpack_from("<HHH", ecaf_data, b)
            if i0 in idx_map and i1 in idx_map and i2 in idx_map:
                local_faces.append((idx_map[i0], idx_map[i1], idx_map[i2]))

        if not local_verts or not local_faces:
            continue

        model.parts.append(MefPart(
            index    = i,
            position = _swizzle(ox, oy, oz),
            vertices = local_verts,
            normals  = local_normals,
            uvs      = local_uvs,
            faces    = local_faces,
        ))
        all_viewer_verts.extend(local_verts)

    # ── Aggregate stats & bounds ───────────────────────────────────────────────
    model.total_vertices  = sum(p.vertex_count  for p in model.parts)
    model.total_triangles = sum(p.triangle_count for p in model.parts)

    if all_viewer_verts:
        xs = [v[0] for v in all_viewer_verts]
        ys = [v[1] for v in all_viewer_verts]
        zs = [v[2] for v in all_viewer_verts]
        model.bounds_min = (min(xs), min(ys), min(zs))
        model.bounds_max = (max(xs), max(ys), max(zs))

    model.valid = True
    return model


# ---------------------------------------------------------------------------
# Shadow Model parser
# ---------------------------------------------------------------------------

def _parse_shadow_model(data: bytes, model: MefModel) -> None:
    """Parse SEMS, XTVS, CAFS chunks for shadow model geometry."""
    sems_data, _ = _read_chunk(data, b"SEMS")
    xtvs_data, _ = _read_chunk(data, b"XTVS")
    cafs_data, _ = _read_chunk(data, b"CAFS")
    
    if not sems_data or not xtvs_data or not cafs_data:
        return

    # SEMS: Array of 28-byte records (from MEF.md)
    num_meshes = len(sems_data) // SEMS_STRIDE
    
    # XTVS: Pool of vertices (12 bytes each: x,y,z - from MEF.md)
    num_pool_verts = len(xtvs_data) // XTVS_STRIDE
    v_raw = [ _swizzle(*struct.unpack_from("<fff", xtvs_data, i * XTVS_STRIDE))
              for i in range(num_pool_verts) ]
        
    all_viewer_verts = []
    
    for i in range(num_meshes):
        off = i * SEMS_STRIDE
        if off + SEMS_STRIDE > len(sems_data):
            break
            
        # Format: start_v, start_f, start_e, count_v, count_f, count_e, bone_id (MEF.md:L257)
        (v_start, f_start, e_start, 
         v_cnt_raw, f_cnt_raw, _, b_id) = struct.unpack_from("<IIIIIII", sems_data, off)
        
        # Heuristic: sometimes v_count and f_count are swapped (e.g. Simple Shadow Models)
        if v_start + v_cnt_raw > len(v_raw) and v_start + f_cnt_raw <= len(v_raw):
             v_count, f_count = f_cnt_raw, v_cnt_raw
        else:
             v_count, f_count = v_cnt_raw, f_cnt_raw

        if v_start >= len(v_raw):
            continue
            
        local_v = v_raw[v_start : v_start + v_count]
        local_f = []
        
        # Normals are per-face in CAFS, but MefPart expects per-vertex.
        local_n = [(0.0, 1.0, 0.0)] * len(local_v)
        
        for f in range(f_count):
            foff = (f_start + f) * CAFS_STRIDE
            if foff + CAFS_STRIDE > len(cafs_data):
                break
            
            # CAFS: 3x uint32 indices, 4 bytes padding, 3x float normals (MEF.md:L253)
            i0, i1, i2 = struct.unpack_from("<III", cafs_data, foff)
            
            # Map global indices to part-local indices
            local_f.append((i0 - v_start, i1 - v_start, i2 - v_start))
        
        if local_v and local_f:
            model.parts.append(MefPart(
                index    = i,
                position = (0.0, 0.0, 0.0), # Origin-relative
                vertices = local_v,
                normals  = local_n,
                uvs      = [(0.0, 0.0)] * len(local_v),
                faces    = local_f,
            ))
            all_viewer_verts.extend(local_v)
            
    model.total_vertices  = sum(p.vertex_count for p in model.parts)
    model.total_triangles = sum(p.triangle_count for p in model.parts)

    if all_viewer_verts:
        xs = [v[0] for v in all_viewer_verts]
        ys = [v[1] for v in all_viewer_verts]
        zs = [v[2] for v in all_viewer_verts]
        model.bounds_min = (min(xs), min(ys), min(zs))
        model.bounds_max = (max(xs), max(ys), max(zs))

    model.valid = True


# ---------------------------------------------------------------------------
# Skeleton parser
# ---------------------------------------------------------------------------

def _parse_skeleton(data: bytes, model: MefModel) -> None:
    """Parse REIH + MANB chunks into model.bones."""
    reih_data, _ = _read_chunk(data, b"REIH")
    manb_data, _ = _read_chunk(data, b"MANB")

    if not reih_data:
        return

    # Parse REIH recursive bone hierarchy.
    bones_info = [] # List of (my_id, parent_id)
    pos = 0
    current_id = 0
    
    def parse_hbone(parent_id: int):
        nonlocal pos, current_id
        if pos >= len(reih_data): return
        
        my_id = current_id
        current_id += 1
        
        child_count = struct.unpack_from("<B", reih_data, pos)[0]
        pos += 1
        
        bones_info.append((my_id, parent_id))
        
        for _ in range(child_count):
            parse_hbone(my_id)
            
    parse_hbone(-1)
    
    # Align(4)
    if pos % 4 != 0:
        pos += 4 - (pos % 4)
        
    num_bones = len(bones_info)
    raw_bones: List[MefBone] = []

    for i in range(num_bones):
        my_id, parent_id = bones_info[i]

        # Name from MANB (16 bytes per string)
        name = f"bone_{i:02d}"
        if manb_data and len(manb_data) >= (i + 1) * 16:
            raw = manb_data[i * 16: (i + 1) * 16]
            name = raw.split(b'\x00')[0].decode('ascii', errors='replace').strip() or name

        # Position from REIH
        if pos + 12 <= len(reih_data):
            hx, hy, hz = struct.unpack_from("<fff", reih_data, pos)
            pos += 12
        else:
            hx, hy, hz = 0.0, 0.0, 0.0

        bone = MefBone(
            bone_id      = my_id,
            name         = name,
            parent_id    = parent_id,
            local_offset = _swizzle(hx, hy, hz),
        )
        raw_bones.append(bone)

    # Build children lists
    bone_map = {b.bone_id: b for b in raw_bones}
    for b in raw_bones:
        if b.parent_id >= 0 and b.parent_id in bone_map:
            bone_map[b.parent_id].children.append(b.bone_id)

    # Accumulate world offsets (DFS, cycle-safe)
    world_cache: Dict[int, Tuple] = {}

    def get_world(bid: int, stack: set = None) -> Tuple:
        if stack is None: stack = set()
        if bid in world_cache: return world_cache[bid]
        if bid not in bone_map or bid in stack: return (0.0, 0.0, 0.0)
        stack.add(bid)
        b = bone_map[bid]
        lx, ly, lz = b.local_offset
        if b.parent_id < 0 or b.parent_id not in bone_map:
            world_cache[bid] = (lx, ly, lz)
        else:
            px, py, pz = get_world(b.parent_id, stack)
            world_cache[bid] = (lx + px, ly + py, lz + pz)
        return world_cache[bid]

    for b in raw_bones:
        b.world_offset = get_world(b.bone_id)
        model.bones.append(b)


# ---------------------------------------------------------------------------
# Magic Vertices parser
# ---------------------------------------------------------------------------

def _parse_magic_vertices(data: bytes, model: MefModel) -> None:
    """Parse XTVM chunk into model.magic_vertices."""
    xtvm_data, _ = _read_chunk(data, b"XTVM")
    if not xtvm_data or len(xtvm_data) < 4:
        return

    # XTVM: 4-byte count, then 16-byte records: [pos xyz float*3, 4 bytes padding/ID]
    count = struct.unpack_from("<I", xtvm_data, 0)[0]
    stride = 16
    for i in range(count):
        off = 4 + i * stride
        if off + stride > len(xtvm_data):
            break
        vx, vy, vz = struct.unpack_from("<fff", xtvm_data, off)
        model.magic_vertices.append(MagicVertex(
            index    = i,
            position = _swizzle(vx, vy, vz),
            normal   = _swizzle(0.0, 1.0, 0.0), # No explicit normal in XTVM
        ))


# ---------------------------------------------------------------------------
# Portals parser
# ---------------------------------------------------------------------------

def _parse_portals(data: bytes, model: MefModel) -> None:
    """Parse TROP + XVTP + CFTP chunks into model.portals."""
    trop_data, _ = _read_chunk(data, b"TROP")
    xvtp_data, _ = _read_chunk(data, b"XVTP")
    cftp_data, _ = _read_chunk(data, b"CFTP")

    if not trop_data or not xvtp_data:
        return

    # TROP: 4-byte portal count
    if len(trop_data) < 4:
        return
    portal_count = struct.unpack_from("<I", trop_data, 0)[0]

    # XVTP: portal vertices (xyz floats, 12 bytes each)
    # CFTP: portal face indices (3 × uint16, 6 bytes each)
    n_verts = len(xvtp_data) // 12
    verts: List[Tuple] = []
    for i in range(n_verts):
        vx, vy, vz = struct.unpack_from("<fff", xvtp_data, i * 12)
        verts.append(_swizzle(vx, vy, vz))

    n_faces = len(cftp_data) // 6 if cftp_data else 0
    faces: List[Tuple] = []
    for i in range(n_faces):
        a, b, c = struct.unpack_from("<HHH", cftp_data, i * 6)
        faces.append((a, b, c))

    portal = Portal(index=0, vertices=verts, faces=faces)
    model.portals.append(portal)


# ---------------------------------------------------------------------------
# Collision Mesh parser
# ---------------------------------------------------------------------------

def _parse_collision(data: bytes, model: MefModel) -> None:
    """Parse HSMC + XTVC + ECFC + HPSC into model.collision."""
    hsmc_data, _ = _read_chunk(data, b"HSMC")
    if not hsmc_data or len(hsmc_data) < 32:
        return

    # HSMC layout: two sets of (n_face, n_vertex, n_material, n_sph, 4×zero)
    n_face0, n_vert0, n_mat0, n_sph0 = struct.unpack_from("<IIII", hsmc_data, 0)
    n_face1, n_vert1, n_mat1, n_sph1 = struct.unpack_from("<IIII", hsmc_data, 16)

    # XTVC appears twice: type-0 then type-1
    xtvc_all  = _read_all_chunks(data, b"XTVC")
    ecfc_all  = _read_all_chunks(data, b"ECFC")
    hpsc_all  = _read_all_chunks(data, b"HPSC")

    for mesh_idx, (n_v, n_f, n_s) in enumerate([(n_vert0, n_face0, n_sph0),
                                                   (n_vert1, n_face1, n_sph1)]):
        verts: List[Tuple] = []
        faces: List[Tuple] = []
        spheres: List[Tuple] = []

        # Parse collision vertices (20 bytes each: x,y,z,_,_)
        if mesh_idx < len(xtvc_all):
            vd = xtvc_all[mesh_idx]
            vstride = 20
            for i in range(len(vd) // vstride):
                vx, vy, vz = struct.unpack_from("<fff", vd, i * vstride)
                verts.append(_swizzle(vx, vy, vz))

        # Parse collision faces (12 bytes each: a,b,c, _, _, _  all uint16)
        if mesh_idx < len(ecfc_all):
            fd = ecfc_all[mesh_idx]
            fstride = 12
            for i in range(len(fd) // fstride):
                a, b, c = struct.unpack_from("<HHH", fd, i * fstride)
                faces.append((a, b, c))

        # Parse collision spheres (16 bytes each: cx,cy,cz,radius)
        if mesh_idx < len(hpsc_all):
            sd = hpsc_all[mesh_idx]
            sstride = 16
            for i in range(len(sd) // sstride):
                cx, cy, cz, r = struct.unpack_from("<ffff", sd, i * sstride)
                sx, sy, sz = _swizzle(cx, cy, cz)
                spheres.append((sx, sy, sz, r * SCALE))

        if verts or spheres:
            model.collision.append(CollisionMesh(
                mesh_type = mesh_idx,
                vertices  = verts,
                faces     = faces,
                spheres   = spheres,
            ))


# ---------------------------------------------------------------------------
# Glow Sprites parser
# ---------------------------------------------------------------------------

def _parse_glow_sprites(data: bytes, model: MefModel) -> None:
    """Parse WOLG chunk into model.glow_sprites."""
    wolg_data, _ = _read_chunk(data, b"WOLG")
    if not wolg_data or len(wolg_data) < 4:
        return

    # WOLG: 4-byte count, then variable records
    count = struct.unpack_from("<I", wolg_data, 0)[0]
    stride = 32
    for i in range(count):
        off = 4 + i * stride
        if off + stride > len(wolg_data):
            break
        gx, gy, gz = struct.unpack_from("<fff", wolg_data, off)
        model.glow_sprites.append(GlowSprite(
            index    = i,
            position = _swizzle(gx, gy, gz),
            radius   = 1.0 * SCALE, # Just a default size
        ))
