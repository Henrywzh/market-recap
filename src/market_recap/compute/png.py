"""A minimal PNG decoder: 8-bit greyscale, RGB, RGBA and palette images,
non-interlaced -- what chart images use. Returns an H x W x 3 uint8 array.

Enough to read a published chart's pixels without adding an imaging
library to the build for one source.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> np.ndarray:
    stride = width * bpp
    out = np.zeros((height, stride), dtype=np.uint8)
    previous = np.zeros(stride, dtype=np.int32)
    pos = 0
    for row in range(height):
        kind = raw[pos]
        line = np.frombuffer(raw, dtype=np.uint8, count=stride, offset=pos + 1).astype(np.int32)
        pos += stride + 1
        if kind == 0:
            current = line
        elif kind == 2:
            current = (line + previous) & 0xFF
        else:
            current = np.zeros(stride, dtype=np.int32)
            for i in range(stride):
                left = current[i - bpp] if i >= bpp else 0
                up = previous[i]
                if kind == 1:
                    value = line[i] + left
                elif kind == 3:
                    value = line[i] + ((left + up) >> 1)
                elif kind == 4:
                    corner = previous[i - bpp] if i >= bpp else 0
                    p = left + up - corner
                    pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                    value = line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)
                else:
                    raise ValueError(f"unknown PNG filter {kind}")
                current[i] = value & 0xFF
        out[row] = current
        previous = current
    return out


def decode(data: bytes) -> np.ndarray:
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG")
    pos, idat, palette = len(SIGNATURE), [], None
    width = height = depth = color = interlace = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = np.frombuffer(body, dtype=np.uint8).reshape(-1, 3)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if depth != 8 or interlace or color not in CHANNELS:
        raise ValueError(f"unsupported PNG (depth {depth}, colour type {color}, interlace {interlace})")
    bpp = CHANNELS[color]
    rows = _unfilter(zlib.decompress(b"".join(idat)), width, height, bpp).reshape(height, width, bpp)
    if color == 3:
        return palette[rows[:, :, 0]]
    if color in (0, 4):
        return np.repeat(rows[:, :, :1], 3, axis=2)
    return rows[:, :, :3]
