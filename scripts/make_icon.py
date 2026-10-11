"""Generate the WorkSync Windows icon from the source artwork.

``assets/worksync.ico`` is build output; ``assets/worksync-icon.png`` is the source of
truth. Regenerate it with::

    py -3 scripts/make_icon.py

The script uses only the standard library, so it runs without the project virtual
environment. The pipeline decodes the RGBA source, crops it to the artwork's rounded tile
(dropping the drop shadow the source carries below the tile), area-averages it down to
every shell size, and packs a single multi-resolution ``.ico``: 32-bit DIB frames below
``PNG_FROM`` pixels and PNG frames at or above it, which is what Windows expects.

The output is deterministic — the same source always produces the same bytes.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from array import array
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "assets" / "worksync-icon.png"
DEFAULT_OUTPUT = REPO_ROOT / "assets" / "worksync.ico"
DEFAULT_SIZES = (16, 24, 32, 48, 64, 128, 256)

#: Frames at or above this size are stored as PNG; smaller frames as 32-bit DIBs.
PNG_FROM = 128
#: Alpha at which a pixel counts as tile rather than background.
TILE_ALPHA = 128
#: Channel spread that separates the coloured tile from the grey drop shadow.
TILE_SPREAD = 40
SHADOW_SPREAD = 24

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ICO_HEADER = struct.Struct("<HHH")
_ICO_ENTRY = struct.Struct("<BBBBHHII")
_BITMAPINFOHEADER = struct.Struct("<IiiHHIIiiII")
_CHANNELS = {2: 3, 6: 4}


class IconError(Exception):
    """The source artwork could not be turned into an icon."""


def decode_png(data: bytes) -> tuple[int, int, bytearray, int]:
    """Decode an 8-bit RGB or RGBA, non-interlaced PNG into straight RGBA rows."""
    if data[:8] != _PNG_SIGNATURE:
        raise IconError("source is not a PNG file")
    header: tuple[int, int, int, int, int, int, int] | None = None
    compressed = bytearray()
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break
        elif kind == b"PLTE":
            raise IconError("palette PNGs are not supported; export the artwork as RGB or RGBA")
        pos += length + 12
    if header is None:
        raise IconError("PNG has no IHDR chunk")
    width, height, depth, colour, _, _, interlace = header
    if depth != 8 or colour not in _CHANNELS or interlace != 0:
        raise IconError(f"unsupported PNG: depth={depth} colour={colour} interlace={interlace}")
    channels = _CHANNELS[colour]
    flat = _unfilter(zlib.decompress(bytes(compressed)), width, height, channels)
    if channels == 4:
        return width, height, flat, width * 4
    rgba = bytearray(width * height * 4)
    for index in range(width * height):
        rgba[index * 4 : index * 4 + 3] = flat[index * 3 : index * 3 + 3]
        rgba[index * 4 + 3] = 255
    return width, height, rgba, width * 4


def _unfilter(data: bytes, width: int, height: int, channels: int) -> bytearray:
    """Reverse the per-row PNG filters into packed pixel bytes."""
    stride = width * channels
    if len(data) != (stride + 1) * height:
        raise IconError(f"truncated PNG image data: {len(data)} bytes, expected {(stride + 1) * height}")
    out = bytearray(stride * height)
    previous = bytearray(stride)
    pos = 0
    for y in range(height):
        kind = data[pos]
        if kind > 4:
            raise IconError(f"unknown PNG filter type {kind} on row {y}")
        pos += 1
        line = bytearray(data[pos : pos + stride])
        pos += stride
        _apply_filter(kind, line, previous, channels)
        out[y * stride : (y + 1) * stride] = line
        previous = line
    return out


def _apply_filter(kind: int, line: bytearray, previous: bytearray, channels: int) -> None:
    """Undo one PNG row filter, in place."""
    if kind == 0:
        return
    for i in range(len(line)):
        left = line[i - channels] if i >= channels else 0
        above = previous[i]
        if kind == 1:
            line[i] = (line[i] + left) & 0xFF
        elif kind == 2:
            line[i] = (line[i] + above) & 0xFF
        elif kind == 3:
            line[i] = (line[i] + ((left + above) >> 1)) & 0xFF
        else:
            corner = previous[i - channels] if i >= channels else 0
            estimate = left + above - corner
            distances = (abs(estimate - left), abs(estimate - above), abs(estimate - corner))
            predictor = (left, above, corner)[distances.index(min(distances))]
            line[i] = (line[i] + predictor) & 0xFF


def _find_tile(rgba: bytearray, stride: int, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Bounding box of the coloured, opaque tile, excluded of the grey drop shadow."""
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        row = y * stride
        for x in range(width):
            offset = row + x * 4
            if rgba[offset + 3] < TILE_ALPHA:
                continue
            red, green, blue = rgba[offset], rgba[offset + 1], rgba[offset + 2]
            if max(red, green, blue) - min(red, green, blue) < TILE_SPREAD:
                continue
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)
    if right < 0:
        return None
    return left, top, right, bottom


def crop_tile(rgba: bytearray, stride: int, width: int, height: int) -> tuple[bytearray, int]:
    """Crop to a square around the artwork's tile and drop the shadow beneath it.

    The tile's own alpha carries the rounded corners, so the crop keeps them for free. The
    shadow is semi-transparent grey below the tile's bottom edge; those pixels are removed
    so the icon does not smear a soft dark edge onto the desktop.
    """
    tile = _find_tile(rgba, stride, width, height)
    if tile is None:
        raise IconError("no coloured tile found in the source artwork")
    left, top, right, bottom = tile
    side = right - left + 1
    if side > width or side > height:
        raise IconError("source artwork is smaller than its own tile")
    left = min(max(left, 0), width - side)
    top = min(max(int(round((top + bottom + 1) / 2 - side / 2)), 0), height - side)
    out = bytearray(side * side * 4)
    peak = 0
    for y in range(side):
        source_row = (top + y) * stride
        target_row = y * side * 4
        below_tile = top + y > bottom
        for x in range(side):
            source = source_row + (left + x) * 4
            alpha = rgba[source + 3]
            if below_tile:
                red, green, blue = rgba[source], rgba[source + 1], rgba[source + 2]
                if max(red, green, blue) - min(red, green, blue) < SHADOW_SPREAD:
                    alpha = 0
            target = target_row + x * 4
            out[target : target + 3] = rgba[source : source + 3]
            out[target + 3] = alpha
            peak = max(peak, alpha)
    if peak < 255:
        # The source art is a touch translucent overall; lift it so the tile is solid.
        for index in range(3, len(out), 4):
            out[index] = min(255, (out[index] * 255 + peak // 2) // peak)
    return out, side


def _premultiply(rgba: bytearray, side: int) -> tuple[array, array, array, array]:
    """Split into premultiplied colour planes so downscaling never bleeds dark edges."""
    count = side * side
    reds = array("i", bytes(4 * count))
    greens = array("i", bytes(4 * count))
    blues = array("i", bytes(4 * count))
    alphas = array("i", bytes(4 * count))
    for index in range(count):
        offset = index * 4
        alpha = rgba[offset + 3]
        reds[index] = rgba[offset] * alpha
        greens[index] = rgba[offset + 1] * alpha
        blues[index] = rgba[offset + 2] * alpha
        alphas[index] = alpha
    return reds, greens, blues, alphas


def _halve(planes: tuple[array, array, array, array], side: int) -> tuple[tuple[array, array, array, array], int]:
    """Exact 2x2 box average; the fast path for the big drop from source to shell size."""
    half = side // 2
    count = half * half
    out = [array("i", bytes(4 * count)) for _ in range(4)]
    for y in range(half):
        upper = (2 * y) * side
        lower = upper + side
        target = y * half
        for x in range(half):
            a, b = upper + 2 * x, upper + 2 * x + 1
            c, d = lower + 2 * x, lower + 2 * x + 1
            for channel in range(4):
                plane = planes[channel]
                out[channel][target + x] = (plane[a] + plane[b] + plane[c] + plane[d] + 2) // 4
    return (out[0], out[1], out[2], out[3]), half


def _resample(planes: tuple[array, array, array, array], side: int, target: int) -> bytearray:
    """Area-average the planes down to ``target`` and return straight RGBA pixels."""
    reds, greens, blues, alphas = planes
    rgba = bytearray(target * target * 4)
    scale = side / target
    for y in range(target):
        y0 = y * scale
        y1 = y0 + scale
        y_start = int(y0)
        y_stop = min(int(y1) + 1, side)
        for x in range(target):
            x0 = x * scale
            x1 = x0 + scale
            x_start = int(x0)
            x_stop = min(int(x1) + 1, side)
            sums = [0.0, 0.0, 0.0, 0.0]
            weight = 0.0
            for sy in range(y_start, y_stop):
                row_weight = min(y1, sy + 1.0) - max(y0, float(sy))
                if row_weight <= 0.0:
                    continue
                row = sy * side
                for sx in range(x_start, x_stop):
                    column_weight = min(x1, sx + 1.0) - max(x0, float(sx))
                    if column_weight <= 0.0:
                        continue
                    cell = row_weight * column_weight
                    index = row + sx
                    sums[0] += reds[index] * cell
                    sums[1] += greens[index] * cell
                    sums[2] += blues[index] * cell
                    sums[3] += alphas[index] * cell
                    weight += cell
            offset = (y * target + x) * 4
            if weight <= 0.0:
                continue
            alpha = sums[3] / weight
            serialised = int(alpha + 0.5)
            rgba[offset + 3] = serialised
            if serialised == 0:
                continue
            for channel in range(3):
                value = (sums[channel] / weight) / alpha
                rgba[offset + channel] = min(255, max(0, int(value + 0.5)))
    return rgba


def render_frames(source: Path | bytes, sizes: Iterable[int] = DEFAULT_SIZES) -> list[tuple[int, bytearray]]:
    """Render straight-RGBA frames at every requested size, largest first."""
    data = source.read_bytes() if isinstance(source, Path) else source
    width, height, rgba, stride = decode_png(data)
    crop, side = crop_tile(rgba, stride, width, height)
    requested = sorted(set(sizes), reverse=True)
    if not requested:
        raise IconError("no sizes requested")
    if requested[0] > side:
        raise IconError(f"requested size {requested[0]} exceeds the {side}px source tile")
    planes = _premultiply(crop, side)
    while side % 2 == 0 and side // 2 >= requested[0]:
        planes, side = _halve(planes, side)
    return [(size, _resample(planes, side, size)) for size in requested]


def _dib_frame(rgba: bytearray, side: int) -> bytes:
    """Encode a 32-bit bottom-up DIB with its 1-bit transparency mask."""
    header = _BITMAPINFOHEADER.pack(40, side, side * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    mask_stride = ((side + 31) // 32) * 4
    pixels = bytearray(side * side * 4)
    mask = bytearray(side * mask_stride)
    for y in range(side):
        source_row = y * side * 4
        target_row = (side - 1 - y) * side * 4
        mask_row = (side - 1 - y) * mask_stride
        for x in range(side):
            offset = source_row + x * 4
            target = target_row + x * 4
            pixels[target] = rgba[offset + 2]
            pixels[target + 1] = rgba[offset + 1]
            pixels[target + 2] = rgba[offset]
            pixels[target + 3] = rgba[offset + 3]
            if rgba[offset + 3] < 128:
                mask[mask_row + (x >> 3)] |= 0x80 >> (x & 7)
    return header + bytes(pixels) + bytes(mask)


def _png_frame(rgba: bytearray, side: int) -> bytes:
    """Encode a PNG frame with no row filtering, so the output stays byte-stable."""
    stride = side * 4
    raw = bytearray()
    for y in range(side):
        raw.append(0)
        raw += rgba[y * stride : (y + 1) * stride]
    return (
        _PNG_SIGNATURE
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def pack_ico(frames: Sequence[tuple[int, bytes]]) -> bytes:
    """Pack encoded frames into an ``.ico`` container."""
    offset = _ICO_HEADER.size + _ICO_ENTRY.size * len(frames)
    directory = bytearray(_ICO_HEADER.pack(0, 1, len(frames)))
    payload = bytearray()
    for side, blob in frames:
        dimension = 0 if side >= 256 else side
        directory += _ICO_ENTRY.pack(dimension, dimension, 0, 0, 1, 32, len(blob), offset)
        payload += blob
        offset += len(blob)
    return bytes(directory + payload)


def build_icon(source: Path | bytes, sizes: Iterable[int] = DEFAULT_SIZES) -> bytes:
    """Render and pack the complete multi-resolution icon."""
    frames = render_frames(source, sizes)
    encoded = [(size, _png_frame(data, size) if size >= PNG_FROM else _dib_frame(data, size)) for size, data in frames]
    return pack_ico(encoded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make_icon", description="Generate assets/worksync.ico from the source artwork."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="source PNG artwork")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="icon to write")
    parser.add_argument(
        "--sizes", default=",".join(str(size) for size in DEFAULT_SIZES), help="comma-separated frame sizes"
    )
    parser.add_argument("--preview", type=Path, default=None, help="also write the largest frame as a PNG")
    args = parser.parse_args(argv)
    sizes = tuple(int(part) for part in args.sizes.split(",") if part.strip())
    try:
        frames = render_frames(args.source, sizes)
        encoded = [
            (size, _png_frame(data, size) if size >= PNG_FROM else _dib_frame(data, size)) for size, data in frames
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(pack_ico(encoded))
    except (IconError, OSError) as exc:
        print(f"make_icon: {exc}", file=sys.stderr)
        return 1
    if args.preview is not None:
        side, data = frames[0]
        args.preview.write_bytes(_png_frame(data, side))
        print(f"preview: {args.preview} ({side}px)")
    print(f"wrote {args.output} ({', '.join(f'{size}px' for size, _ in frames)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
