"""Parse Portisch B1 (bucket sniffing) frames and convert them to B0.

This is the same conversion the jonajona.nl / Tasmota "B1 to B0" tool
does, so captured codes can be sent straight back out with send_raw.

B1 frame:  AA B1 <n> <n x 2-byte bucket table> <pulse data> 55
B0 frame:  AA B0 <len> <n> <repeats> <bucket table> <pulse data> 55
"""
from __future__ import annotations

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


def pulse_data(frame: bytes) -> bytes:
    """The pulse part of a parsed B1 frame, trimmed to a single repeat."""
    return single_repeat(frame[1 + frame[0] * 2 :])


def distinct_frames(frames: list[bytes]) -> list[bytes]:
    """Drop frames carrying the same signal as an earlier one, keeping order.

    Bucket timings jitter a little between bursts, so frames are compared
    by their pulse data only.
    """
    seen: set[bytes] = set()
    unique: list[bytes] = []
    for frame in frames:
        pulses = pulse_data(frame)
        if pulses not in seen:
            seen.add(pulses)
            unique.append(frame)
    return unique


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
    frame = frame[: 1 + frame[0] * 2] + pulse_data(frame)
    payload = bytes([frame[0], repeats]) + frame[1:]
    if len(payload) > 0xFF:
        raise ValueError("Captured code is too long to send as a B0 frame")
    return f"AAB0{len(payload):02X}{payload.hex().upper()}55"


def with_repeats(code: str, repeats: int) -> str:
    """Set the repeat count of a B0 code (AA B0 <len> <n> <repeats> ...)."""
    code = re.sub(r"\s", "", code).upper()
    if not code.startswith("AAB0") or len(code) < 10:
        return code
    return f"{code[:8]}{repeats:02X}{code[10:]}"


def b0_pulse_data(code: str) -> bytes | None:
    """The pulse part of a B0 code, for matching against received frames."""
    digits = re.sub(r"\s", "", code)
    try:
        data = bytes.fromhex(digits)
    except ValueError:
        return None
    if len(data) < 6 or data[:2] != b"\xaa\xb0" or data[-1] != 0x55:
        return None
    return data[5 + data[3] * 2 : -1] or None
