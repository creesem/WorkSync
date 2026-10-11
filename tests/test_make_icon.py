"""Tests for the icon generator (scripts/make_icon.py)."""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_icon.py"
_spec = importlib.util.spec_from_file_location("worksync_make_icon", SCRIPT)
assert _spec is not None and _spec.loader is not None
make_icon = importlib.util.module_from_spec(_spec)
sys.modules["worksync_make_icon"] = make_icon
_spec.loader.exec_module(make_icon)

REPO = Path(__file__).resolve().parents[1]
TILE = (20, 60, 200, 250)
SHADOW = (150, 150, 150, 210)


def synthetic_artwork(tile_width: int = 80) -> bytes:
    """A coloured tile with grey shadow rows below it, encoded as an RGBA PNG."""
    side = tile_width + 16
    tile_height = tile_width - 4
    rgba = bytearray(side * side * 4)
    for y in range(side):
        for x in range(side):
            offset = (y * side + x) * 4
            if not 8 <= x < 8 + tile_width:
                continue
            if 8 <= y < 8 + tile_height:
                rgba[offset : offset + 4] = bytes(TILE)
            elif 8 + tile_height <= y < 8 + tile_height + 8:
                rgba[offset : offset + 4] = bytes(SHADOW)
    return make_icon._png_frame(bytes(rgba), side)


def parse_ico(data: bytes) -> list[tuple[int, int, int, bytes]]:
    """Return (side, planes, bits, frame bytes) for every directory entry."""
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1)
    frames = []
    for index in range(count):
        width, height, _, _, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
        assert (width or 256) == (height or 256)
        frames.append((width or 256, planes, bits, data[offset : offset + size]))
    return frames


def test_crop_tile_squares_on_the_tile_and_drops_the_shadow() -> None:
    width = height = 96
    _, _, rgba, stride = make_icon.decode_png(synthetic_artwork())
    crop, side = make_icon.crop_tile(rgba, stride, width, height)

    assert side == 80, "crop is the tile's width, so the window stays square"
    # Crop rows below the tile (y=84..85 in the source) were grey shadow: they must be clear.
    for y in (78, 79):
        assert crop[(y * side) * 4 + 3] == 0, "grey shadow below the tile must be dropped"
    # Crop rows above the tile (source y=6..7) were background: still clear.
    assert crop[0 * 4 + 3] == 0
    # The tile itself is opaque: alpha is lifted from the source's 250 to full.
    assert crop[(10 * side + 10) * 4 + 3] == 255
    assert tuple(crop[(10 * side + 10) * 4 : (10 * side + 10) * 4 + 3]) == TILE[:3]


def test_build_icon_writes_one_sized_frame_per_request() -> None:
    data = make_icon.build_icon(synthetic_artwork(), sizes=(16, 32, 48))
    frames = parse_ico(data)

    assert [side for side, _, _, _ in frames] == [48, 32, 16]
    for side, planes, bits, blob in frames:
        assert (planes, bits) == (1, 32)
        # Below PNG_FROM the frame is a 32-bit DIB holding both XOR image and AND mask.
        header = struct.unpack_from("<IiiHHIIiiII", blob, 0)
        assert header[0] == 40
        assert (header[1], header[2], header[3], header[4]) == (side, side * 2, 1, 32)


def test_build_icon_switches_to_png_frames_at_the_boundary() -> None:
    frames = parse_ico(make_icon.build_icon(synthetic_artwork(tile_width=144), sizes=(64, 128)))
    formats = {side: blob[:8] for side, _, _, blob in frames}

    assert formats[64] != b"\x89PNG\r\n\x1a\n", "frames below PNG_FROM stay 32-bit DIBs"
    assert formats[128] == b"\x89PNG\r\n\x1a\n", "frames at or above PNG_FROM are PNGs"
    for side, _, _, blob in frames:
        if blob[:8] == b"\x89PNG\r\n\x1a\n":
            assert struct.unpack_from(">II", blob, 16) == (side, side)


def test_build_icon_is_deterministic() -> None:
    source = synthetic_artwork()
    assert make_icon.build_icon(source, sizes=(16, 32)) == make_icon.build_icon(source, sizes=(16, 32))


def test_build_icon_refuses_sizes_larger_than_the_tile() -> None:
    try:
        make_icon.build_icon(synthetic_artwork(tile_width=16), sizes=(64,))
    except make_icon.IconError as exc:
        assert "exceeds" in str(exc)
    else:  # pragma: no cover - the guard is the point
        raise AssertionError("expected IconError for an upscaled frame")


def test_decode_png_rejects_input_that_is_not_a_png() -> None:
    try:
        make_icon.decode_png(b"not a png at all")
    except make_icon.IconError as exc:
        assert "PNG" in str(exc)
    else:  # pragma: no cover - the guard is the point
        raise AssertionError("expected IconError for non-PNG input")


def test_committed_icon_is_a_complete_multi_resolution_icon() -> None:
    data = (REPO / "assets" / "worksync.ico").read_bytes()
    frames = parse_ico(data)

    assert sorted(side for side, _, _, _ in frames) == sorted(make_icon.DEFAULT_SIZES)
    assert all(len(blob) > 0 for _, _, _, blob in frames)
