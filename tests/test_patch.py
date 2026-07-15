import struct
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mtk_gpu_oc.patch import PatchRecord, PatchPlan, build_opp_patch_plan
from mtk_gpu_oc.opp import OppTable, OPP_ENTRY_SIZE
from mtk_gpu_oc.profiles import MT6789


def _make_stock_table_data():
    entries = [
        (1100000, 90000, 90000, 1, 1875, 0),
        (1000000, 85000, 85000, 1, 1875, 0),
        (900000, 80000, 80000, 1, 1875, 0),
        (800000, 75000, 75000, 2, 1250, 0),
        (700000, 70000, 75000, 2, 1250, 0),
    ]
    return b''.join(struct.pack('<6I', *e) for e in entries), entries


def test_patch_plan_validation_ok():
    data = bytes(b'\x00\x01\x02\x03')
    plan = PatchPlan()
    plan.add(PatchRecord(name='test', file_offset=0, original=b'\x00\x01', replacement=b'\xff\xfe'))
    result = plan.validate(data)
    assert len(result) == 0
    print("  PASS test_patch_plan_validation_ok")


def test_patch_plan_validation_mismatch():
    data = bytes(b'\x00\x01\x02\x03')
    plan = PatchPlan()
    plan.add(PatchRecord(name='mismatch', file_offset=0, original=b'\xff\xff', replacement=b'\x00\x00'))
    result = plan.validate(data)
    assert len(result) > 0
    print("  PASS test_patch_plan_validation_mismatch")


def test_patch_plan_validation_out_of_range():
    data = bytes(b'\x00\x01')
    plan = PatchPlan()
    plan.add(PatchRecord(name='oor', file_offset=10, original=b'\x00\x01', replacement=b'\xff\xff'))
    result = plan.validate(data)
    assert len(result) > 0
    print("  PASS test_patch_plan_validation_out_of_range")


def test_patch_plan_apply():
    data = bytearray(b'\x00\x01\x02\x03\x04\x05')
    plan = PatchPlan()
    plan.add(PatchRecord(name='p1', file_offset=0, original=b'\x00\x01', replacement=b'\xff\xff'))
    plan.add(PatchRecord(name='p2', file_offset=4, original=b'\x04\x05', replacement=b'\xaa\xbb'))
    patched = plan.apply(data)
    assert bytes(patched) == b'\xff\xff\x02\x03\xaa\xbb'
    print("  PASS test_patch_plan_apply")


def test_patch_plan_overlap_detection():
    data = bytearray(b'\x00' * 10)
    plan = PatchPlan()
    plan.add(PatchRecord(name='a', file_offset=0, original=b'\x00\x02', replacement=b'\xff\xff'))
    plan.add(PatchRecord(name='b', file_offset=1, original=b'\x02\x04', replacement=b'\xee\xee'))
    errors = plan.validate(bytes(data))
    assert len(errors) > 0, "should detect overlap"
    print("  PASS test_patch_plan_overlap_detection")


def test_build_opp_patch_plan():
    table_bytes, stock_entries = _make_stock_table_data()
    table = OppTable.from_bytes(table_bytes, 0, len(stock_entries))

    plan = build_opp_patch_plan(MT6789, table, ceil_khz=1200000, ceil_volt=80000)
    assert len(plan) == len(stock_entries)
    non_noop = sum(1 for r in plan.records if r.original != r.replacement)
    assert non_noop >= len(stock_entries) - 1, f"only {non_noop} of {len(stock_entries)} entries changed"

    patched = plan.apply(bytearray(table_bytes))
    patched_table = OppTable.from_bytes(bytes(patched), 0, len(stock_entries))

    # Check frequencies increased
    assert patched_table[0].freq_khz == 1200000
    assert patched_table[0].volt == 80000

    # Check ordering preserved
    assert patched_table.is_descending_frequency()

    print(f"  PASS test_build_opp_patch_plan (entry 0: {patched_table[0].freq_mhz} MHz {patched_table[0].volt_mv} mV)")


def test_opp_plan_validation():
    """The plan should validate cleanly against its own source data."""
    table_bytes, stock_entries = _make_stock_table_data()
    table = OppTable.from_bytes(table_bytes, 0, len(stock_entries))
    plan = build_opp_patch_plan(MT6789, table, ceil_khz=1200000, ceil_volt=80000)
    errors = plan.validate(table_bytes)
    assert len(errors) == 0, f"validation errors: {errors}"
    print("  PASS test_opp_plan_validation")


def test_opp_round_trip_preservation():
    """Decode-modify-encode should produce consistent output."""
    table_bytes, stock_entries = _make_stock_table_data()
    table = OppTable.from_bytes(table_bytes, 0, len(stock_entries))
    plan = build_opp_patch_plan(MT6789, table, ceil_khz=1200000, ceil_volt=80000)
    patched = plan.apply(bytearray(table_bytes))

    # Decode patched result
    patched_table = OppTable.from_bytes(bytes(patched), 0, len(stock_entries))

    # Re-encode and compare - should be identical
    re_encoded = patched_table.to_bytes()
    assert re_encoded == bytes(patched), "round-trip mismatch"

    print("  PASS test_opp_round_trip_preservation")


if __name__ == '__main__':
    test_patch_plan_validation_ok()
    test_patch_plan_validation_mismatch()
    test_patch_plan_validation_out_of_range()
    test_patch_plan_apply()
    test_patch_plan_overlap_detection()
    test_build_opp_patch_plan()
    test_opp_plan_validation()
    test_opp_round_trip_preservation()
    print("\nAll patch tests passed.")
