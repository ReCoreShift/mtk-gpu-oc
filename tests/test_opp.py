import struct
import sys
import os
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mtk_gpu_oc.opp import OppEntry, OppTable, detect_opp_table, OPP_ENTRY_SIZE


def make_opp_bytes(*entries):
    data = b''
    for freq, volt, vsram, u3, u4, u5 in entries:
        data += struct.pack('<6I', freq, volt, vsram, u3, u4, u5)
    return data


def test_opp_entry_roundtrip():
    entry = OppEntry(freq_khz=1100000, volt=90000, vsram=90000, u3=1, u4=1875, u5=0)
    encoded = entry.to_bytes()
    decoded = OppEntry.from_bytes(encoded)
    assert decoded.freq_khz == 1100000, f"freq mismatch: {decoded.freq_khz}"
    assert decoded.volt == 90000
    assert decoded.vsram == 90000
    assert decoded.u3 == 1
    assert decoded.u4 == 1875
    assert decoded.u5 == 0
    assert decoded.freq_mhz == 1100
    assert decoded.volt_mv == 900.00
    print("  PASS test_opp_entry_roundtrip")


def test_opp_table_descending():
    data = make_opp_bytes(
        (1100000, 90000, 90000, 1, 1875, 0),
        (1000000, 85000, 85000, 1, 1875, 0),
        (900000, 80000, 80000, 1, 1875, 0),
    )
    table = OppTable.from_bytes(data, 0, 3)
    assert len(table) == 3
    assert table.is_descending_frequency()
    assert not table.is_ascending_frequency()
    print("  PASS test_opp_table_descending")


def test_opp_table_ascending():
    data = make_opp_bytes(
        (390000, 67500, 75000, 2, 625, 0),
        (596000, 69375, 75000, 2, 625, 0),
        (835000, 76875, 76875, 2, 1250, 0),
    )
    table = OppTable.from_bytes(data, 0, 3)
    assert table.is_ascending_frequency()
    assert not table.is_descending_frequency()
    print("  PASS test_opp_table_ascending")


def test_detect_opp_table():
    data = make_opp_bytes(
        (1100000, 90000, 90000, 1, 1875, 0),
        (1000000, 85000, 85000, 1, 1875, 0),
        (900000, 80000, 80000, 1, 1875, 0),
        (0, 0, 0, 0, 0, 0),  # terminator
    )
    table = detect_opp_table(data, 0, max_entries=10)
    assert table is not None
    assert len(table) == 3
    print("  PASS test_detect_opp_table")


def test_detect_opp_table_invalid():
    data = b'\x00' * 48
    table = detect_opp_table(data, 0, max_entries=10)
    assert table is None
    print("  PASS test_detect_opp_table_invalid")


def test_opp_table_frequency_range():
    data = make_opp_bytes(
        (1100000, 90000, 90000, 1, 1875, 0),
        (390000, 67500, 75000, 2, 625, 0),
    )
    table = OppTable.from_bytes(data, 0, 2)
    fmin, fmax = table.frequency_range_mhz()
    assert fmin == 390
    assert fmax == 1100
    print("  PASS test_opp_table_frequency_range")


MTK_STOCK_MODULE = os.environ.get(
    'MTK_STOCK_MODULE',
    os.path.join(os.path.dirname(__file__), '..', 'research', 'stock', 'mtk_gpufreq_mt6789.ko'),
)


def test_opp_stock_roundtrip():
    """Round-trip the real stock OPP table (integration, needs MTK_STOCK_MODULE)."""
    try:
        with open(MTK_STOCK_MODULE, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        pytest.skip(f'stock module not found at {MTK_STOCK_MODULE}')
        return

    table = OppTable.from_bytes(data, 0xbd10, 45)
    encoded = table.to_bytes()
    assert encoded == data[0xbd10:0xbd10 + 45 * OPP_ENTRY_SIZE], "round-trip mismatch"
    print(f"  PASS test_opp_stock_roundtrip ({len(encoded)} bytes)")


if __name__ == '__main__':
    test_opp_entry_roundtrip()
    test_opp_table_descending()
    test_opp_table_ascending()
    test_detect_opp_table()
    test_detect_opp_table_invalid()
    test_opp_table_frequency_range()
    test_opp_stock_roundtrip()
    test_opp_modified_roundtrip()
    print("\nAll OPP tests passed.")
