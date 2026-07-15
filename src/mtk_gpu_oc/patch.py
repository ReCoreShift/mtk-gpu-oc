# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import struct
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from . import elf
from .opp import OppEntry, OppTable, u3_for, u4_for, OPP_ENTRY_SIZE, VSRAM_FLOOR
from .voltage import quantize_volt, estimate_voltage


class PatchType(Enum):
    INSTRUCTION = 'instruction'
    DATA = 'data'
    RELOCATION = 'relocation'


@dataclass
class PatchRecord:
    name: str
    file_offset: int
    original: bytes
    replacement: bytes
    virtual_address: Optional[int] = None
    section_name: str = ''
    patch_type: PatchType = PatchType.DATA
    semantic_original: str = ''
    semantic_replacement: str = ''


@dataclass
class PatchPlan:
    records: list[PatchRecord] = field(default_factory=list)
    input_sha256: str = ''
    output_path: str = ''

    def add(self, record: PatchRecord):
        self.records.append(record)

    def validate(self, data: bytes) -> list[str]:
        errors = []
        seen_ranges = []

        for r in self.records:
            if r.file_offset + len(r.original) > len(data):
                errors.append(f'{r.name}: offset 0x{r.file_offset:x} out of range')
                continue
            actual = data[r.file_offset:r.file_offset + len(r.original)]
            if actual != r.original:
                errors.append(
                    f'{r.name}: expected original bytes at 0x{r.file_offset:x} do not match\n'
                    f'  expected: {r.original.hex()}\n'
                    f'  actual:   {actual.hex()}'
                )
            if len(r.original) != len(r.replacement):
                errors.append(f'{r.name}: length mismatch original({len(r.original)}) vs replacement({len(r.replacement)})')

            rng = (r.file_offset, r.file_offset + len(r.original))
            for existing in seen_ranges:
                if rng[0] < existing[1] and rng[1] > existing[0]:
                    errors.append(f'{r.name}: overlaps with another patch')
            seen_ranges.append(rng)

        return errors

    def apply(self, data: bytearray) -> bytearray:
        result = bytearray(data)
        for r in self.records:
            result[r.file_offset:r.file_offset + len(r.original)] = r.replacement
        return result

    def changed_ranges(self) -> list[tuple[int, int, bytes, bytes]]:
        ranges = []
        for r in self.records:
            if r.original != r.replacement:
                ranges.append((r.file_offset, r.file_offset + len(r.original), r.original, r.replacement))
        return ranges

    def __len__(self) -> int:
        return len(self.records)


def build_opp_patch_plan(profile, table: OppTable, ceil_khz: int, ceil_volt: int,
                         floor_khz: Optional[int] = None, floor_volt: Optional[int] = None) -> PatchPlan:
    plan = PatchPlan()
    floor_khz = floor_khz or table.entries[-1].freq_khz
    floor_volt = floor_volt or _default_floor_volt(table, ceil_khz, ceil_volt, floor_khz)

    stock_range_khz = table.entries[0].freq_khz - floor_khz
    new_range_khz = ceil_khz - floor_khz

    for i, entry in enumerate(table.entries):
        ratio = (entry.freq_khz - floor_khz) / stock_range_khz if stock_range_khz > 0 else 0
        new_freq = round((floor_khz + ratio * new_range_khz) / 1000) * 1000

        ratio_v = (new_freq - floor_khz) / (ceil_khz - floor_khz) if (ceil_khz - floor_khz) > 0 else 0
        new_volt = quantize_volt(round(floor_volt + ratio_v * (ceil_volt - floor_volt)))
        new_volt = max(50000, new_volt)
        new_vsram = max(new_volt, VSRAM_FLOOR)

        new_entry = OppEntry(
            freq_khz=new_freq,
            volt=new_volt,
            vsram=new_vsram,
            u3=u3_for(new_freq, profile.u3_threshold),
            u4=u4_for(new_freq, profile.u4_t1, profile.u4_t2, profile.u4_v1, profile.u4_v2, profile.u4_v3),
            u5=0,
        )

        original_bytes = entry.to_bytes()
        replacement_bytes = new_entry.to_bytes()

        plan.add(PatchRecord(
            name=f'opp_{i:02d}',
            file_offset=table.file_offset + i * OPP_ENTRY_SIZE,
            original=original_bytes,
            replacement=replacement_bytes,
            section_name=table.section_name,
            patch_type=PatchType.DATA,
            semantic_original=str(entry),
            semantic_replacement=str(new_entry),
        ))

    return plan


def build_code_patch_plan(profile, analysis) -> PatchPlan:
    plan = PatchPlan()

    for site in analysis.patch_sites:
        name = site['name']
        if name == 'avs_freq_check_bypass':
            plan.add(PatchRecord(
                name=name,
                file_offset=site['file_offset'],
                original=profile.avs_freq_check_pattern[4:8],
                replacement=profile.avs_freq_check_nop[4:8],
                patch_type=PatchType.INSTRUCTION,
                semantic_original='B.NE (branch if freq mismatch)',
                semantic_replacement='NOP (skip abort)',
            ))
        elif name == 'apply_adjust_probe_bypass':
            if 'rela_entry' in site:
                rela = site['rela_entry']
                plan.add(PatchRecord(
                    name=f'{name}_rela',
                    file_offset=rela['file_offset'] + 8,
                    original=struct.pack('<Q', 0x000004570000011b),
                    replacement=struct.pack('<Q', 0),
                    patch_type=PatchType.RELOCATION,
                    semantic_original=f'R_AARCH64_CALL26 -> {rela["target_symbol"]}',
                    semantic_replacement='R_AARCH64_NONE',
                ))
            plan.add(PatchRecord(
                name=name,
                file_offset=site['file_offset'],
                original=profile.apply_adjust_probe_pattern[8:12],
                replacement=profile.apply_adjust_probe_nop[8:12],
                patch_type=PatchType.INSTRUCTION,
                semantic_original='BL __gpufreq_apply_adjust',
                semantic_replacement='NOP',
            ))
        elif name == 'apply_adjust_avs_bypass':
            if 'rela_entry' in site:
                rela = site['rela_entry']
                plan.add(PatchRecord(
                    name=f'{name}_rela',
                    file_offset=rela['file_offset'] + 8,
                    original=struct.pack('<Q', 0x000004570000011b),
                    replacement=struct.pack('<Q', 0),
                    patch_type=PatchType.RELOCATION,
                    semantic_original=f'R_AARCH64_CALL26 -> {rela["target_symbol"]}',
                    semantic_replacement='R_AARCH64_NONE',
                ))
            plan.add(PatchRecord(
                name=name,
                file_offset=site['file_offset'],
                original=profile.apply_adjust_avs_pattern[8:12],
                replacement=profile.apply_adjust_avs_nop[8:12],
                patch_type=PatchType.INSTRUCTION,
                semantic_original='BL __gpufreq_apply_adjust',
                semantic_replacement='NOP',
            ))
        elif name == 'segment_adj_data':
            status = site.get('status', 'present')
            if status == 'already_patched':
                continue
            plan.add(PatchRecord(
                name=name,
                file_offset=site['file_offset'],
                original=profile.segment_adj_stock_bytes[:8],
                replacement=profile.segment_adj_patched_bytes[:8],
                patch_type=PatchType.DATA,
                semantic_original='g_segment_adj=25 (OPP index ceiling)',
                semantic_replacement='g_segment_adj=0 (uncapped)',
            ))

    return plan


def _default_floor_volt(table: OppTable, ceil_khz: int, ceil_volt: int, floor_khz: int) -> int:
    stock_ceil_volt = table.entries[0].volt
    stock_floor_volt = table.entries[-1].volt
    ratio = (floor_khz - table.entries[-1].freq_khz) / (table.entries[0].freq_khz - table.entries[-1].freq_khz)
    return quantize_volt(round(stock_floor_volt + ratio * (stock_ceil_volt - stock_floor_volt)))
