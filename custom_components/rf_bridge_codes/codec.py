"""Parse Portisch B1 (bucket sniffing) frames and convert them to B0.

This is the same conversion the jonajona.nl / Tasmota "B1 to B0" tool
does, so captured codes can be sent straight back out with send_raw.

B1 frame:  AA B1 <n> <n x 2-byte bucket table> <pulse data> 55
B0 frame:  AA B0 <len> <n> <repeats> <bucket table> <pulse data> 55
"""
from __future__ import annotations

from collections import Counter
import re

B1_MAX_BUCKETS = 8
MIN_PULSE_BYTES = 4


def parse_bucket_frames(raw_hex: str) -> list[bytes]:
    """Pull every complete B1 frame out of a raw UART hex dump.

    Each returned frame is <n> + bucket table + pulse data (no header,
    no 0x55 terminator). 0x55 can legitimately appear inside a frame, but
    0xAA can't appear in pulse data, so a frame's pulses run until the
    next 0xAA (or the end of the dump) and must end with 0x55.
    """
    digits = re.sub(r"[^0-9A-Fa-f]", "", raw_hex or "")
    data = bytes.fromhex(digits[: len(digits) // 2 * 2])

    frames: list[bytes] = []
    i = 0
    while i + 2 < len(data):
        if data[i] != 0xAA or data[i + 1] != 0xB1:
            i += 1
            continue
        count = data[i + 2]
        pulses_start = i + 3 + count * 2
        if not 0 < count <= B1_MAX_BUCKETS or pulses_start >= len(data):
            i += 2
            continue
        end = data.find(b"\xaa", pulses_start)
        if end == -1:
            end = len(data)
        pulses = data[pulses_start:end]
        if pulses.endswith(b"\x55") and len(pulses) - 1 >= MIN_PULSE_BYTES:
            frames.append(data[i + 2 : pulses_start] + pulses[:-1])
        i = end
    return frames


def best_frame(frames: list[bytes]) -> bytes | None:
    """The frame seen most often in a burst (remotes repeat each press)."""
    if not frames:
        return None
    return Counter(frames).most_common(1)[0][0]


def single_repeat(pulses: bytes) -> bytes:
    """Trim pulse data holding the same signal back to back down to one copy.

    A long remote press can land two or more repeats in one B1 frame. Sending
    that as-is transmits the command twice per repeat, so find the shortest
    period the data repeats in full at least twice (a trailing partial copy
    is allowed) and keep just one period.
    """
    for period in range(MIN_PULSE_BYTES, len(pulses) // 2 + 1):
        copy = pulses[:period]
        if all(
            pulses[i : i + period] == copy[: len(pulses) - i]
            for i in range(period, len(pulses), period)
        ):
            return copy
    return pulses


def b1_to_b0(frame: bytes, repeats: int = 8) -> str:
    """Convert a parsed B1 frame into a sendable B0 hex string."""
    table_end = 1 + frame[0] * 2
    frame = frame[:table_end] + single_repeat(frame[table_end:])
    payload = bytes([frame[0], repeats]) + frame[1:]
    if len(payload) > 0xFF:
        raise ValueError("Captured code is too long to send as a B0 frame")
    return f"AAB0{len(payload):02X}{payload.hex().upper()}55"
