import struct

from remixer.adapters.cpu_topology import parse_cpu_sets
from remixer.cpu.runtime import configured_workers
from remixer.cpu.tuner import knee


def test_knee_chooses_smallest_near_peak():
    rows = [{"workers": workers, "chunk_size": 1, "units_per_minute": rate}
            for workers, rate in [(1, 10), (4, 35), (8, 70), (12, 72), (16, 71)]]
    assert knee(rows)["workers"] == 8
    assert 1 <= configured_workers(10000) <= 21


def test_windows_cpu_set_parser_uses_record_sizes():
    records = []
    for logical, efficiency in [(0, 8), (12, 0)]:
        value = bytearray(32)
        struct.pack_into("<II", value, 0, 32, 0)
        value[14], value[18] = logical, efficiency
        records.append(bytes(value))
    rows = parse_cpu_sets(b"".join(records))
    assert rows[0]["logical_processor"] == 0
    assert rows[0]["efficiency_class"] == 8
    assert rows[1]["logical_processor"] == 12
