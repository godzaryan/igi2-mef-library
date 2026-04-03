"""
igi2mef.parser
~~~~~~~~~~~~~~
Core parsing logic for IGI 2 binary MEF files.
Highly robust version with bounds checking and error handling.
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
# Internal Safe Reader
# ---------------------------------------------------------------------------

class _MefReader:
    """Safe binary reader that raises MefParseError on OOB access."""
    def __init__(self, data: bytes, path: str = ""):
        self.data = data
        self.path = path

    def unpack(self, fmt: str, offset: int) -> Tuple:
        size = struct.calcsize(fmt)
        if offset + size > len(self.data):
            raise MefParseError(f"Unexpected EOF while reading {fmt} at 0x{offset:X}", self.path)
        return struct.unpack_from(fmt, self.data, offset)

    def get_chunk(self, tag: bytes) -> Optional[bytes]:
        """Find the first occurrence of a chunk tag and return its safe payload."""
        idx = self.data.find(tag)
        if idx == -1: return None
        if idx + 16 > len(self.data): return None
        size = struct.unpack_from("<I", self.data, idx + 4)[0]
        start, end = idx + 16, idx + 16 + size
        if start > len(self.data): return None
        return self.data[start: min(end, len(self.data))]

    def get_all_chunks(self, tag: bytes) -> List[bytes]:
        """Return payloads for ALL occurrences of a tag (e.g. repeated XTVC)."""
        res = []
        pos = 0
        while True:
            idx = self.data.find(tag, pos)
            if idx == -1: break
            if idx + 16 > len(self.data): break
            size = struct.unpack_from("<I", self.data, idx + 4)[0]
            start, end = idx + 16, idx + 16 + size
            res.append(self.data[start: min(end, len(self.data))])
            pos = idx + 1
        return res


def _scan_all_chunks(data: bytes) -> List[ChunkInfo]:
    """Scan file for all known chunks for metadata display."""
    chunks: List[ChunkInfo] = []
    for tag in KNOWN_CHUNK_TAGS:
        pos = 0
        while True:
            idx = data.find(tag, pos)
            if idx == -1: break
            if idx + 8 <= len(data):
                size = struct.unpack_from("<I", data, idx + 4)[0]
                chunks.append(ChunkInfo(tag=tag.decode("latin-1"), offset=idx, size=size))
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
    """Non-throwing check for MEF magic."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == MAGIC_ILFF
    except OSError:
        return False


def parse_mef(path, raise_on_error: bool = False) -> MefModel:
    """Fully parse an IGI 2 MEF file with full structural validation."""
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
        return _fail(f"File Access Error: {exc}")

    if len(data) < 20 or data[:4] != MAGIC_ILFF:
        return _fail("Invalid Header: ILFF magic not found")

    reader = _MefReader(data, str(path))
    model.chunks = _scan_all_chunks(data)

    try:
        # ── HSEM — Global Header ───────────────────────────────────────────────
        hsem_raw = reader.get_chunk(b"HSEM")
        if hsem_raw is None:
            # Handle shadow models (Shadow models don't have HSEM)
            if reader.get_chunk(b"SEMS"):
                model.model_type = 3
                _parse_shadow_model(reader, model)
                _parse_skeleton(reader, model) # Shadows can be skeletal
                return model
            return _fail("Missing HSEM chunk")

        hr = _MefReader(hsem_raw, f"{path.name}::HSEM")
        model.hsem_version  = hr.unpack("<f", 0)[0]
        model.hsem_game_ver = hr.unpack("<I", 4)[0]
        
        raw_type = hr.unpack("<I", 32)[0] if len(hsem_raw) >= 36 else 0
        model.model_type = raw_type if raw_type in XTRV_STRIDE else 0

        # Lookups from constants
        st, p_off, n_off, u_off = (XTRV_STRIDE[model.model_type], XTRV_POS_OFF[model.model_type], 
                                   XTRV_NORM_OFF[model.model_type], XTRV_UV1_OFF[model.model_type])
        dn_st, mc_off = DNER_STRIDE[model.model_type], D3DR_MESH_COUNT_OFFSET[model.model_type]

        # ── D3DR — Mesh Counter ───────────────────────────────────────────────
        d3dr_raw = reader.get_chunk(b"D3DR")
        if not d3dr_raw: return _fail("Missing D3DR render descriptor")
        mesh_count = _MefReader(d3dr_raw).unpack("<I", mc_off)[0]
        if mesh_count == 0 or mesh_count > 4096:
            return _fail(f"Corrupt mesh count: {mesh_count}")

        # ── DNER — Mesh Part Definitions ──────────────────────────────────────
        dner_raw = reader.get_chunk(b"DNER")
        if not dner_raw: return _fail("Missing DNER part descriptors")
        dr = _MefReader(dner_raw)
        parts_meta = []
        for i in range(mesh_count):
            base = i * dn_st
            px, py, pz = dr.unpack("<fff", base + 4)
            idx_st, tri_cnt = dr.unpack("<HH", base + 16)
            parts_meta.append({"pos": (px, py, pz), "start": idx_st, "count": tri_cnt})

        # ── XTRV — Vertex Pool ───────────────────────────────────────────────
        xtrv_raw = reader.get_chunk(b"XTRV")
        if not xtrv_raw: return _fail("Missing XTRV vertex pool")
        xr = _MefReader(xtrv_raw)
        p_size = len(xtrv_raw) // st
        
        v_raw, n_raw, u_raw = [], [], []
        for i in range(p_size):
            b = i * st
            vx, vy, vz = xr.unpack("<fff", b + p_off)
            nx, ny, nz = xr.unpack("<fff", b + n_off)
            u, v       = xr.unpack("<ff",  b + u_off)
            bid = xr.unpack("<B", b + 36)[0] if st >= 40 else 0
            v_raw.append((vx, vy, vz, bid))
            n_raw.append((nx, ny, nz))
            u_raw.append((u, v))

        # ── ECAF — Face Indices ──────────────────────────────────────────────
        ecaf_raw = reader.get_chunk(b"ECAF")
        if not ecaf_raw: return _fail("Missing ECAF face index list")
        er = _MefReader(ecaf_raw)

        # ── Build Logic ──────────────────────────────────────────────────────
        all_v = []
        for i, meta in enumerate(parts_meta):
            ox, oy, oz = meta["pos"]
            f_start, f_count = meta["start"], meta["count"]
            l_v, l_n, l_u, l_f = [], [], [], []
            used_map = {}

            for t in range(f_count):
                b = (f_start + t) * 6
                # Every index must be valid within the vertex pool
                i0, i1, i2 = er.unpack("<HHH", b)
                for g_idx in (i0, i1, i2):
                    if g_idx >= len(v_raw):
                        raise MefParseError(f"Mesh {i} references OOB vertex {g_idx}")
                    if g_idx not in used_map:
                        new_idx = len(l_v)
                        used_map[g_idx] = new_idx
                        vx, vy, vz, _ = v_raw[g_idx]
                        nx, ny, nz = n_raw[g_idx]
                        u, v = u_raw[g_idx]
                        l_v.append(_swizzle(vx, vy, vz))
                        l_n.append(_swizzle(nx, ny, nz))
                        l_u.append((u, 1.0 - v))
                l_f.append((used_map[i0], used_map[i1], used_map[i2]))

            if l_v:
                model.parts.append(MefPart(i, _swizzle(ox, oy, oz), l_v, l_n, l_u, l_f))
                all_v.extend(l_v)

        # ── Sub-systems ───────────────────────────────────────────────────────
        _parse_skeleton(reader, model)
        _parse_magic_vertices(reader, model)
        _parse_portals(reader, model)
        _parse_collision(reader, model)
        _parse_glow_sprites(reader, model)

        # ── Final Stats ───────────────────────────────────────────────────────
        if all_v:
            x_v, y_v, z_v = zip(*all_v)
            model.bounds_min = (min(x_v), min(y_v), min(z_v))
            model.bounds_max = (max(x_v), max(y_v), max(z_v))
        model.total_vertices  = sum(len(p.vertices) for p in model.parts)
        model.total_triangles = sum(len(p.faces) for p in model.parts)
        model.valid = True

    except (MefParseError, struct.error) as e:
        return _fail(f"Structural Integrity Failure: {e}")

    return model


# ---------------------------------------------------------------------------
# Shadow Mode Architecture
# ---------------------------------------------------------------------------

def _parse_shadow_model(reader: _MefReader, model: MefModel) -> None:
    sems, xtvs, cafs = reader.get_chunk(b"SEMS"), reader.get_chunk(b"XTVS"), reader.get_chunk(b"CAFS")
    if not (sems and xtvs and cafs): return

    sr, xr, cr = _MefReader(sems), _MefReader(xtvs), _MefReader(cafs)
    n_v = len(xtvs) // XTVS_STRIDE
    v_pool = [ _swizzle(*xr.unpack("<fff", i * XTVS_STRIDE)) for i in range(n_v) ]

    n_m = len(sems) // SEMS_STRIDE
    all_v = []
    for i in range(n_m):
        v_st, f_st, _, v_cr, f_cr, _, _ = sr.unpack("<IIIIIII", i * SEMS_STRIDE)
        v_c, f_c = (f_cr, v_cr) if v_st + v_cr > n_v else (v_cr, f_cr) # Heuristic
        if v_st + v_c > n_v: continue
        
        l_v = v_pool[v_st : v_st + v_c]
        l_f = []
        for f in range(f_c):
            i0, i1, i2 = cr.unpack("<III", (f_st + f) * CAFS_STRIDE)
            l_f.append((max(0, i0 - v_st), max(0, i1 - v_st), max(0, i2 - v_st)))
        
        if l_v and l_f:
            model.parts.append(MefPart(i, (0,0,0), l_v, [(0,1,0)] * len(l_v), [(0,0)] * len(l_v), l_f))
            all_v.extend(l_v)

    if all_v:
        xs, ys, zs = zip(*all_v)
        model.bounds_min, model.bounds_max = (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
    model.valid = True


# ---------------------------------------------------------------------------
# Bone hierarchy
# ---------------------------------------------------------------------------

def _parse_skeleton(reader: _MefReader, model: MefModel) -> None:
    reih, manb = reader.get_chunk(b"REIH"), reader.get_chunk(b"MANB")
    if not reih: return
    rr, mr = _MefReader(reih), _MefReader(manb) if manb else None
    
    bones_info = []
    pos, cur_id = 0, 0
    def walk(pid: int, depth: int):
        nonlocal pos, cur_id
        if depth > 128 or pos >= len(reih): return
        my_id = cur_id; cur_id += 1
        cnt = rr.unpack("<B", pos)[0]; pos += 1
        bones_info.append((my_id, pid))
        for _ in range(cnt): walk(my_id, depth + 1)

    walk(-1, 0)
    if pos % 4 != 0: pos += (4 - (pos % 4))
    
    raw = []
    for i, (bid, pid) in enumerate(bones_info):
        name = f"bone_{i}"
        if mr and len(manb) >= (i + 1) * 16:
            name = mr.data[i*16:(i+1)*16].split(b"\x00")[0].decode("ascii", "replace").strip() or name
        off = _swizzle(*rr.unpack("<fff", pos)) if pos + 12 <= len(reih) else (0,0,0)
        if pos + 12 <= len(reih): pos += 12
        raw.append(MefBone(bid, name, pid, off))

    bone_map = {b.bone_id: b for b in raw}
    for b in raw:
        if b.parent_id in bone_map: bone_map[b.parent_id].children.append(b.bone_id)
    
    memo = {}
    def get_world(bid: int, stack: set):
        if bid in memo: return memo[bid]
        if bid not in bone_map or bid in stack: return (0,0,0)
        stack.add(bid); b = bone_map[bid]; lx,ly,lz = b.local_offset
        if b.parent_id == -1: memo[bid] = (lx, ly, lz)
        else: px,py,pz = get_world(b.parent_id, stack); memo[bid] = (lx+px, ly+py, lz+pz)
        return memo[bid]

    for b in raw:
        b.world_offset = get_world(b.bone_id, set())
        model.bones.append(b)


# ---------------------------------------------------------------------------
# Attachment / Collision / Glow Side-systems
# ---------------------------------------------------------------------------

def _parse_magic_vertices(reader: _MefReader, model: MefModel) -> None:
    raw = reader.get_chunk(b"XTVM")
    if not (raw and len(raw) >= 4): return
    r = _MefReader(raw)
    for i in range(min(r.unpack("<I", 0)[0], 512)):
        off = 4 + i * 16
        if off + 12 > len(raw): break
        model.magic_vertices.append(MagicVertex(i, _swizzle(*r.unpack("<fff", off))))

def _parse_portals(reader: _MefReader, model: MefModel) -> None:
    xv, cf = reader.get_chunk(b"XVTP"), reader.get_chunk(b"CFTP")
    if not xv: return
    vl = [_swizzle(*struct.unpack_from("<fff", xv, j*12)) for j in range(len(xv)//12)]
    fl = [struct.unpack_from("<HHH", cf, j*6) for j in range(len(cf)//6)] if cf else []
    model.portals.append(Portal(0, vl, fl))

def _parse_collision(reader: _MefReader, model: MefModel) -> None:
    if not reader.get_chunk(b"HSMC"): return
    va, fa = reader.get_all_chunks(b"XTVC"), reader.get_all_chunks(b"ECFC")
    for i in range(min(len(va), 2)):
        vd, fd = va[i], fa[i] if i < len(fa) else None
        vl = [_swizzle(*struct.unpack_from("<fff", vd, j*20)) for j in range(len(vd)//20)]
        fl = [struct.unpack_from("<HHH", fd, j*12) for j in range(len(fd)//12)] if fd else []
        model.collision.append(CollisionMesh(i, vl, fl))

def _parse_glow_sprites(reader: _MefReader, model: MefModel) -> None:
    raw = reader.get_chunk(b"WOLG")
    if not (raw and len(raw) >= 4): return
    cnt = struct.unpack("<I", raw[:4])[0]
    for i in range(min(cnt, 256)):
        off = 4 + i * 32
        if off + 12 > len(raw): break
        model.glow_sprites.append(GlowSprite(i, _swizzle(*struct.unpack_from("<fff", raw, off))))
