"""Windows adapter: per-adapter engine utilization (Intel iGPU, NPU, NVIDIA) from the
`\\GPU Engine(*)\\Utilization Percentage` performance counters via PDH (ctypes, no subprocess).

Counter instances look like `pid_1234_luid_0x00000000_0x0001A2B3_phys_0_eng_0_engtype_3D`.
LUIDs are mapped to adapter names with DXGI; a LUID that DXGI does not list but that has
Compute engines is the NPU (compute-only adapters are invisible to DXGI). Best effort:
`EngineSampler.available` is False off Windows or when the counters are missing.
"""
from __future__ import annotations

import ctypes
import re
import sys
from collections import defaultdict

_INST = re.compile(r"luid_0x([0-9A-Fa-f]+)_0x([0-9A-Fa-f]+)_phys_\d+_eng_\d+_engtype_(.*)$")
PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2


def dxgi_adapters() -> dict[str, str]:
    """{'<high>_<low>' (hex, 8 digits each): description} for every DXGI adapter."""
    if sys.platform != "win32":
        return {}
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class DESC1(ctypes.Structure):
        _fields_ = [("Description", ctypes.c_wchar * 128), ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
                    ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint), ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                    ("AdapterLuid", LUID), ("Flags", ctypes.c_uint)]

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

    iid = GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = ctypes.c_void_p()
    try:
        if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
            return {}
    except OSError:
        return {}

    def vcall(obj, index, restype, *argtypes):
        vtbl = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[index])

    out = {}
    i = 0
    while True:
        adapter = ctypes.c_void_p()
        hr = vcall(factory, 12, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
            factory, i, ctypes.byref(adapter))
        if hr != 0:
            break
        desc = DESC1()
        if vcall(adapter, 10, ctypes.c_long, ctypes.POINTER(DESC1))(adapter, ctypes.byref(desc)) == 0:
            luid = desc.AdapterLuid
            out[f"{luid.HighPart & 0xFFFFFFFF:08X}_{luid.LowPart:08X}"] = desc.Description
        vcall(adapter, 2, ctypes.c_ulong)(adapter)  # Release
        i += 1
    vcall(factory, 2, ctypes.c_ulong)(factory)
    return out


def classify(description: str | None, engtypes: set[str]) -> str:
    d = (description or "").lower()
    if "nvidia" in d:
        return "nvidia"
    if "intel" in d and ("arc" in d or "graphics" in d):
        return "igpu"
    if "basic render" in d:
        return "basic"
    if description is None and any("compute" in e.lower() for e in engtypes):
        return "npu"
    return "other"


class EngineSampler:
    """Call sample() every interval; returns {'igpu_3d': %, 'igpu_compute': %, 'npu': %, ...}."""

    def __init__(self):
        self.available = False
        self._names = {}
        if sys.platform != "win32":
            return
        from ctypes import wintypes

        self._pdh = ctypes.windll.pdh
        self._query = wintypes.HANDLE()
        self._counter = wintypes.HANDLE()
        if self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query)) != 0:
            return
        if self._pdh.PdhAddEnglishCounterW(self._query, "\\GPU Engine(*)\\Utilization Percentage", None,
                                           ctypes.byref(self._counter)) != 0:
            return
        # Effective CPU clock: % Processor Performance x base MHz (psutil reports only the base clock).
        self._cpu_perf = wintypes.HANDLE()
        if self._pdh.PdhAddEnglishCounterW(self._query, "\Processor Information(_Total)\% Processor Performance",
                                           None, ctypes.byref(self._cpu_perf)) != 0:
            self._cpu_perf = None
        # ACPI thermal zones (Kelvin): on this ASUS _TZ.THRM tracks the CPU package. No admin rights needed.
        self._tz = {}
        for key, path in (("tz_temp", "\Thermal Zone Information(*)\Temperature"),
                          ("tz_passive", "\Thermal Zone Information(*)\% Passive Limit")):
            h = wintypes.HANDLE()
            if self._pdh.PdhAddEnglishCounterW(self._query, path, None, ctypes.byref(h)) == 0:
                self._tz[key] = h
        self._pdh.PdhCollectQueryData(self._query)
        self._names = dxgi_adapters()
        self.available = True

    def _items(self, counter=None) -> list[tuple[str, float]]:
        from ctypes import wintypes

        counter = counter or self._counter

        class VALUE(ctypes.Structure):
            _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]

        class ITEM(ctypes.Structure):
            _fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", VALUE)]

        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        st = self._pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ctypes.byref(size),
                                                    ctypes.byref(count), None)
        if (st & 0xFFFFFFFF) != PDH_MORE_DATA:
            return []
        buf = (ctypes.c_byte * size.value)()
        st = self._pdh.PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ctypes.byref(size),
                                                    ctypes.byref(count), buf)
        if st != 0:
            return []
        items = ctypes.cast(buf, ctypes.POINTER(ITEM))
        return [(items[i].szName, items[i].FmtValue.doubleValue) for i in range(count.value)]

    def sample(self) -> dict[str, float]:
        if not self.available:
            return {}
        if self._pdh.PdhCollectQueryData(self._query) != 0:
            return {}
        per = defaultdict(float)
        engtypes = defaultdict(set)
        for name, value in self._items():
            m = _INST.search(name or "")
            if not m:
                continue
            luid = f"{int(m.group(1), 16):08X}_{int(m.group(2), 16):08X}"
            eng = m.group(3).strip().lower().replace(" ", "_") or "unknown"
            per[(luid, eng)] += value
            engtypes[luid].add(eng)
        out: dict[str, float] = {}
        for (luid, eng), v in per.items():
            kind = classify(self._names.get(luid), engtypes[luid])
            if kind in ("basic", "other"):
                continue
            key = f"{kind}_{eng}"
            out[key] = max(out.get(key, 0.0), min(100.0, v))
        for kind in ("igpu", "npu"):
            vals = [v for k, v in out.items() if k.startswith(kind + "_")]
            if vals:
                out[kind] = max(vals)  # busiest engine = adapter utilization (Task Manager convention)
        for name, value in self._items(self._tz["tz_temp"]) if "tz_temp" in self._tz else []:
            zone = (name or "").strip("\\").lower().replace("_tz.", "")
            out[f"tz_{zone}_c"] = round(value - 273.15, 1)
        for name, value in self._items(self._tz["tz_passive"]) if "tz_passive" in self._tz else []:
            zone = (name or "").strip("\\").lower().replace("_tz.", "")
            out[f"tz_{zone}_passive_pct"] = value
        if self._cpu_perf is not None:
            from ctypes import wintypes

            class VALUE(ctypes.Structure):
                _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]

            v = VALUE()
            if self._pdh.PdhGetFormattedCounterValue(self._cpu_perf, PDH_FMT_DOUBLE, None, ctypes.byref(v)) == 0:
                out["cpu_perf_pct"] = v.doubleValue
        return out
