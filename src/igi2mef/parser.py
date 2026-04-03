"""
igi2mef.parser
~~~~~~~~~~~~~~
Core parsing logic for IGI 2 binary MEF files, including debugging experiments.
"""

import os, struct
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import (
    MefModel, MefPart, MefBone, MagicVertex, Portal, 
    CollisionMesh, GlowSprite, ChunkInfo, MefDebugParams
)
from ._constants import (
    MAGIC_ILFF, XTRV_STRIDE, XTRV_POS_OFF, XTRV_NORM_OFF, XTRV_UV1_OFF,
    DNER_STRIDE, D3DR_MESH_COUNT_OFFSET, KNOWN_CHUNK_TAGS,
    SEMS_STRIDE, XTVS_STRIDE, CAFS_STRIDE
)
from .exceptions import MefParseError

def _read_chunk(data: bytes, tag: bytes) -> Tuple[Optional[bytes], int]:
    idx = data.find(tag)
    if idx == -1 or idx + 16 > len(data): return None, idx
    size = struct.unpack_from("<I", data, idx + 4)[0]
    start = idx + 16; end = start + size
    return data[start: min(end, len(data))], idx

def _read_all_chunks(data: bytes, tag: bytes) -> List[bytes]:
    results, pos = [], 0
    while True:
        idx = data.find(tag, pos)
        if idx == -1 or idx + 16 > len(data): break
        size = struct.unpack_from("<I", data, idx + 4)[0]
        results.append(data[idx + 16: idx + 16 + size]); pos = idx + 1
    return results

def _scan_all_chunks(data: bytes) -> List[ChunkInfo]:
    chunks = []
    for tag in KNOWN_CHUNK_TAGS:
        pos = 0
        while True:
            idx = data.find(tag, pos)
            if idx == -1: break
            if idx + 8 <= len(data):
                size = struct.unpack_from("<I", data, idx + 4)[0]
                chunks.append(ChunkInfo(tag=tag.decode("latin-1"), offset=idx, size=size))
            pos = idx + 1
    return sorted(chunks, key=lambda c: c.offset)

def parse_mef(path, debug: Optional[MefDebugParams] = None) -> MefModel:
    path = Path(path).resolve(); m = MefModel(path=path)
    if debug is None: debug = MefDebugParams()
    try:
        m.file_size = os.path.getsize(path)
        with open(path, "rb") as fh: data = fh.read()
    except OSError as e: m.error = str(e); return m

    if data[:4] != MAGIC_ILFF: m.error = "Invalid ILFF Magic"; return m
    m.chunks = _scan_all_chunks(data)

    hsem, _ = _read_chunk(data, b"HSEM")
    if hsem:
        m.hsem_version = struct.unpack_from("<f", hsem, 0)[0]
        m.hsem_game_ver = struct.unpack_from("<I", hsem, 4)[0]
        raw_type = struct.unpack_from("<I", hsem, 32)[0] if len(hsem) >= 36 else 0
        m.model_type = raw_type if raw_type in XTRV_STRIDE else 0
    elif data.find(b"SEMS") != -1:
        m.model_type = 3; _parse_shadow(data, m, debug); return m
    else: m.error = "Missing HSEM"; return m

    stride, po, no, uo = XTRV_STRIDE[m.model_type], XTRV_POS_OFF[m.model_type], XTRV_NORM_OFF[m.model_type], XTRV_UV1_OFF[m.model_type]
    
    d3dr, _ = _read_chunk(data, b"D3DR")
    mc_off = D3DR_MESH_COUNT_OFFSET.get(m.model_type, 8)
    mesh_cnt = struct.unpack_from("<I", d3dr, mc_off)[0] if d3dr else 0

    dner, _ = _read_chunk(data, b"DNER")
    ds = DNER_STRIDE.get(m.model_type, 32)
    meta = []
    for i in range(mesh_cnt):
        b = i * ds
        px, py, pz = struct.unpack_from("<fff", dner, b + 4)
        is_, tc = struct.unpack_from("<HH", dner, b + 16)
        meta.append({"pos": (px, py, pz), "start": is_, "cnt": tc})

    xtrv, _ = _read_chunk(data, b"XTRV")
    vpool, npool, upool = [], [], []
    for i in range(len(xtrv) // stride):
        b = i * stride
        pos = struct.unpack_from("<fff", xtrv, b + po)
        norm = struct.unpack_from("<fff", xtrv, b + no) if b+no+12 <= len(xtrv) else (0,0,1)
        uv = struct.unpack_from("<ff", xtrv, b + uo) if b+uo+8 <= len(xtrv) else (0,0)
        bid = struct.unpack_from("<H", xtrv, b + 38)[0] if stride >= 40 else 0
        vpool.append((*pos, bid)); npool.append(norm); upool.append(uv)

    ecaf, _ = _read_chunk(data, b"ECAF")
    _parse_skel(data, m, debug); _parse_magic(data, m, debug); _parse_coll(data, m, debug)

    all_v = []
    for i, p_m in enumerate(meta):
        used, b_st = set(), p_m["start"] * 2
        for t in range(p_m["cnt"]):
            idx = struct.unpack_from("<HHH", ecaf, b_st + t*6)
            for v_i in idx: used.add(v_i)
        if not used: continue
        unique = sorted(used); imap = {old: new for new, old in enumerate(unique)}
        lv, ln, lu = [], [], []
        for gi in unique:
            vx, vy, vz, b_id = vpool[gi]; nx, ny, nz = npool[gi]; u, v = upool[gi]
            dx, dy, dz = debug.swizzle(vx, vy, vz, debug.v_scale)
            if m.model_type == 1 and m.bones:
                eff = b_id + debug.bone_id_bias
                if 0 <= eff < len(m.bones):
                    bx, by, bz = m.bones[eff].world_offset
                    dx += bx; dy += by; dz += bz
            lv.append((dx, dy, dz)); ln.append(debug.swizzle(nx, ny, nz, 1.0)); lu.append((u, 1.0-v))
        lf = []
        for t in range(p_m["cnt"]):
            idx = struct.unpack_from("<HHH", ecaf, b_st + t*6)
            lf.append(tuple(imap[vi] for vi in idx))
        m.parts.append(MefPart(index=i, position=debug.swizzle(*p_m["pos"], debug.b_scale), 
                               vertices=lv, normals=ln, uvs=lu, faces=lf))
        all_v.extend(lv)

    m.total_vertices = sum(p.vertex_count for p in m.parts)
    m.total_triangles = sum(p.triangle_count for p in m.parts)
    if all_v:
        xs, ys, zs = [v[0] for v in all_v], [v[1] for v in all_v], [v[2] for v in all_v]
        m.bounds_min, m.bounds_max = (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
    m.valid = True; return m

def _parse_skel(data, m, debug):
    reih, _ = _read_chunk(data, b"REIH"); manb, _ = _read_chunk(data, b"MANB")
    if not reih or not manb: return
    n = len(manb) // 16; cc = list(reih[:n]); pids = [-1] * n
    if n > 0:
        import collections; q = collections.deque([0]); ni = 1
        while q and ni < n:
            curr = q.popleft()
            for _ in range(cc[curr]):
                if ni < n: pids[ni] = curr; q.append(ni); ni += 1
    pos = n + (4 - n % 4) if n % 4 else n
    bones, world = [], {}
    for i in range(n):
        name = manb[i*16:(i+1)*16].split(b'\x00')[0].decode('ascii', 'replace').strip() or f"bone_{i}"
        hx, hy, hz = struct.unpack_from("<fff", reih, pos) if pos+12 <= len(reih) else (0,0,0)
        pos += 12; b = MefBone(bone_id=i, name=name, parent_id=pids[i], local_offset=debug.swizzle(hx, hy, hz, debug.b_scale))
        bones.append(b)
    bmap = {b.bone_id: b for b in bones}
    for b in bones:
        if b.parent_id >= 0: bmap[b.parent_id].children.append(b.bone_id)
    def get_w(bid, stack):
        if bid in world: return world[bid]
        if bid not in bmap or bid in stack: return (0,0,0)
        stack.add(bid); b = bmap[bid]; lx, ly, lz = b.local_offset
        if debug.bone_mode == "ABS": world[bid] = (lx, ly, lz)
        elif debug.bone_mode == "ROOT":
            rx, ry, rz = get_w(0, stack); world[bid] = (lx+rx, ly+ry, lz+rz)
        else:
            if b.parent_id < 0: world[bid] = (lx, ly, lz)
            else: px, py, pz = get_w(b.parent_id, stack); world[bid] = (lx+px, ly+py, lz+pz)
        return world[bid]
    for b in bones: b.world_offset = get_w(b.bone_id, set()); m.bones.append(b)

def _parse_magic(data, m, debug):
    xtvm, _ = _read_chunk(data, b"XTVM")
    if not xtvm:
        return
    cnt = struct.unpack_from("<I", xtvm, 0)[0]
    for i in range(cnt):
        pos = struct.unpack_from("<fff", xtvm, 4 + i*16)
        m.magic_vertices.append(MagicVertex(index=i, position=debug.swizzle(*pos, debug.v_scale)))

def _parse_coll(data, m, debug):
    hsmc, _ = _read_chunk(data, b"HSMC")
    if not hsmc:
        return
    nf0, nv0, nm0, ns0 = struct.unpack_from("<IIII", hsmc, 0)
    nf1, nv1, nm1, ns1 = struct.unpack_from("<IIII", hsmc, 16)
    v_a, f_a, s_a = _read_all_chunks(data, b"XTVC"), _read_all_chunks(data, b"ECFC"), _read_all_chunks(data, b"HPSC")
    for i, (n_v, n_f, n_s) in enumerate([(nv0, nf0, ns0), (nv1, nf1, ns1)]):
        lv, lf, ls = [], [], []
        if i < len(v_a):
            vd = v_a[i]
            for v_i in range(len(vd)//20):
                px, py, pz = struct.unpack_from("<fff", vd, v_i*20)
                dx, dy, dz = debug.swizzle(px, py, pz, debug.v_scale)
                if m.model_type == 1 and m.bones:
                    bid = struct.unpack_from("<H", vd, v_i*20 + 12)[0]
                    eff = bid + debug.bone_id_bias
                    if 0 <= eff < len(m.bones):
                        bx, by, bz = m.bones[eff].world_offset
                        dx += bx; dy += by; dz += bz
                lv.append((dx, dy, dz))
        if i < len(f_a):
            fd = f_a[i]
            for f_i in range(len(fd)//12):
                lf.append(struct.unpack_from("<HHH", fd, f_i*12))
        if i < len(s_a):
            sd = s_a[i]
            for s_i in range(len(sd)//16):
                cx, cy, cz, r = struct.unpack_from("<ffff", sd, s_i*16)
                sx, sy, sz = debug.swizzle(cx, cy, cz, debug.v_scale)
                if m.model_type == 1 and m.bones:
                    bx, by, bz = m.bones[0].world_offset
                    sx += bx
                    sy += by
                    sz += bz
                ls.append((sx, sy, sz, r*debug.v_scale))
        if lv or ls: m.collision.append(CollisionMesh(mesh_type=i, vertices=lv, faces=lf, spheres=ls))

def _parse_shadow(data, m, debug):
    sems, _ = _read_chunk(data, b"SEMS")
    xtvs, _ = _read_chunk(data, b"XTVS")
    cafs, _ = _read_chunk(data, b"CAFS")
    if not sems or not xtvs or not cafs:
        return
    v_raw = [debug.swizzle(*struct.unpack_from("<fff", xtvs, i*12), debug.v_scale) for i in range(len(xtvs)//12)]
    all_v = []
    for i in range(len(sems)//28):
        off = i * 28; v_st, f_st, e_st, v_c, f_c, _, bid = struct.unpack_from("<IIIIIII", sems, off)
        if v_st + v_c > len(v_raw): v_c, f_c = f_c, v_c # Count swap heuristic
        lv = v_raw[v_st:v_st+v_c]; lf = []
        for f in range(f_c):
            i0, i1, i2 = struct.unpack_from("<III", cafs, (f_st+f)*28)
            lf.append((i0-v_st, i1-v_st, i2-v_st))
        if lv and lf:
            m.parts.append(MefPart(index=i, position=(0,0,0), vertices=lv, normals=[(0,1,0)]*len(lv), uvs=[(0,0)]*len(lv), faces=lf))
            all_v.extend(lv)
    m.total_vertices, m.total_triangles = sum(p.vertex_count for p in m.parts), sum(p.triangle_count for p in m.parts)
    if all_v:
        xs, ys, zs = [v[0] for v in all_v], [v[1] for v in all_v], [v[2] for v in all_v]
        m.bounds_min, m.bounds_max = (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
    m.valid = True

def quick_validate(path):
    try:
        with open(path, "rb") as f: return f.read(4) == MAGIC_ILFF
    except: return False
