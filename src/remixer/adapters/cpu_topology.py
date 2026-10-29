"""Read-only Windows CPU-set discovery; no OS, power or firmware changes."""
from __future__ import annotations

import os
import struct


def parse_cpu_sets(buffer: bytes) -> list[dict]:
    rows, offset = [], 0
    while offset + 8 <= len(buffer):
        size, kind = struct.unpack_from("<II", buffer, offset)
        if size < 8 or offset + size > len(buffer):
            raise ValueError("invalid CPU-set record size")
        if kind == 0 and size >= 20:
            group = struct.unpack_from("<H", buffer, offset + 12)[0]
            rows.append({"group": group, "logical_processor": buffer[offset+14],
                         "core_index": buffer[offset+15], "efficiency_class": buffer[offset+18]})
        offset += size
    return rows


def cpu_sets() -> dict:
    if os.name != "nt":
        return {"rows": [], "reason": "Windows CPU-set API unavailable on this platform"}
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel.GetSystemCpuSetInformation
    function.argtypes = [ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), wintypes.HANDLE, wintypes.ULONG]
    function.restype = wintypes.BOOL
    needed = wintypes.ULONG()
    function(None, 0, ctypes.byref(needed), None, 0)
    if not needed.value:
        return {"rows": [], "reason": f"CPU-set size query failed: {ctypes.get_last_error()}"}
    buffer = ctypes.create_string_buffer(needed.value)
    if not function(buffer, needed, ctypes.byref(needed), None, 0):
        return {"rows": [], "reason": f"CPU-set query failed: {ctypes.get_last_error()}"}
    rows = parse_cpu_sets(buffer.raw[:needed.value])
    # psutil's list affinity does not express processor groups; avoid guessing.
    if any(row["group"] != 0 for row in rows):
        return {"rows": rows, "reason": "Multiple processor groups; affinity comparison skipped"}
    classes = sorted({row["efficiency_class"] for row in rows})
    if len(classes) < 2:
        return {"rows": rows, "reason": "OS reports no distinct efficiency classes"}
    return {"rows": rows, "performance": [row["logical_processor"] for row in rows if row["efficiency_class"] == max(classes)],
            "efficiency": [row["logical_processor"] for row in rows if row["efficiency_class"] < max(classes)],
            "reason": None}
