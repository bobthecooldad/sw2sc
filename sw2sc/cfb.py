"""Minimal, read-only Compound File Binary (OLE2) reader.

Written from Microsoft's public [MS-CFB] specification. Pre-2015 SolidWorks
files use this container. Input is treated as untrusted: every offset and
chain is bounds-checked and loops are capped.
"""
from __future__ import annotations

import struct

MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
FREESECT, ENDOFCHAIN, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF
MAX_CHAIN = 1 << 22


class CfbError(Exception):
    pass


class CompoundFile:
    def __init__(self, data: bytes):
        if len(data) < 512 or data[:8] != MAGIC:
            raise CfbError("not a compound file")
        self.data = data
        major, = struct.unpack_from("<H", data, 0x1A)
        shift, mini_shift = struct.unpack_from("<HH", data, 0x1E)
        if shift not in (9, 12) or mini_shift != 6:
            raise CfbError(f"bad sector shift {shift}/{mini_shift}")
        self.sector_size = 1 << shift
        self.mini_size = 1 << mini_shift
        (n_fat, first_dir, _tx, self.mini_cutoff, first_minifat, n_minifat,
         first_difat, n_difat) = struct.unpack_from("<IIIIIIII", data, 0x2C)
        difat = list(struct.unpack_from("<109I", data, 0x4C))
        sec, guard = first_difat, 0
        per = self.sector_size // 4 - 1
        while sec not in (ENDOFCHAIN, FREESECT) and guard < max(n_difat, 1) + 1:
            buf = self._sector(sec)
            vals = struct.unpack_from(f"<{per + 1}I", buf)
            difat.extend(vals[:per])
            sec = vals[per]
            guard += 1
        fat: list[int] = []
        for s in difat[:n_fat]:
            if s in (FREESECT, ENDOFCHAIN):
                continue
            buf = self._sector(s)
            fat.extend(struct.unpack_from(f"<{self.sector_size // 4}I", buf))
        self.fat = fat
        self.entries = self._read_dir(first_dir)
        root = self.entries[0] if self.entries else None
        if not root:
            raise CfbError("no root entry")
        self.ministream = self._chain_bytes(root["start"], root["size"], self.fat, self._sector)
        mf = self._chain_bytes(first_minifat, None, self.fat, self._sector) if n_minifat else b""
        self.minifat = list(struct.unpack_from(f"<{len(mf) // 4}I", mf)) if mf else []
        self.paths = self._build_paths()

    # -- low level -------------------------------------------------------
    def _sector(self, idx: int) -> bytes:
        off = (idx + 1) * self.sector_size
        if idx >= 0xFFFFFFFA or off + self.sector_size > len(self.data) + self.sector_size:
            raise CfbError(f"sector {idx} out of range")
        return self.data[off:off + self.sector_size].ljust(self.sector_size, b"\0")

    def _mini(self, idx: int) -> bytes:
        off = idx * self.mini_size
        if off + self.mini_size > len(self.ministream):
            raise CfbError(f"mini sector {idx} out of range")
        return self.ministream[off:off + self.mini_size]

    def _chain_bytes(self, start, size, table, reader) -> bytes:
        out, sec, n = [], start, 0
        while sec not in (ENDOFCHAIN, FREESECT):
            if sec >= len(table) or n > MAX_CHAIN:
                raise CfbError("broken sector chain")
            out.append(reader(sec))
            sec = table[sec]
            n += 1
            if size is not None and n * len(out[0]) >= size:
                break
        buf = b"".join(out)
        return buf[:size] if size is not None else buf

    def _read_dir(self, first: int) -> list[dict]:
        raw = self._chain_bytes(first, None, self.fat, self._sector)
        entries = []
        for i in range(len(raw) // 128):
            e = raw[i * 128:(i + 1) * 128]
            name_len, = struct.unpack_from("<H", e, 0x40)
            name = e[:max(0, min(name_len, 64) - 2)].decode("utf-16-le", "replace")
            etype = e[0x42]
            left, right, child = struct.unpack_from("<III", e, 0x44)
            start, size = struct.unpack_from("<IQ", e, 0x74)
            if self.sector_size == 512:
                size &= 0xFFFFFFFF
            entries.append(dict(name=name, type=etype, left=left, right=right,
                                child=child, start=start, size=size))
        return entries

    def _build_paths(self) -> dict[str, int]:
        paths: dict[str, int] = {}
        seen: set[int] = set()
        stack = [(self.entries[0]["child"], "")]
        while stack:
            idx, prefix = stack.pop()
            if idx == NOSTREAM or idx >= len(self.entries) or idx in seen:
                continue
            seen.add(idx)
            e = self.entries[idx]
            stack.append((e["left"], prefix))
            stack.append((e["right"], prefix))
            path = prefix + e["name"]
            if e["type"] == 2:
                paths[path] = idx
            elif e["type"] == 1:
                stack.append((e["child"], path + "/"))
        return paths

    # -- public ----------------------------------------------------------
    def list(self) -> list[str]:
        return sorted(self.paths)

    def read(self, path: str) -> bytes:
        e = self.entries[self.paths[path]]
        if e["size"] < self.mini_cutoff:
            return self._chain_bytes(e["start"], e["size"], self.minifat, self._mini)
        return self._chain_bytes(e["start"], e["size"], self.fat, self._sector)
