# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import hashlib
import struct
from dataclasses import dataclass, field
from typing import Optional

from . import elf
from .opp import OppTable, OppEntry, OPP_ENTRY_SIZE


@dataclass
class SemanticDiff:
    file_offset: int
    length: int
    section_name: str
    original_bytes: bytes
    modified_bytes: bytes
    semantic_purpose: str
    confidence: str
    original_value: str = ''
    modified_value: str = ''


@dataclass
class CompareResult:
    stock_path: str = ''
    modified_path: str = ''
    stock_sha256: str = ''
    modified_sha256: str = ''
    total_differing_bytes: int = 0
    diffs: list[SemanticDiff] = field(default_factory=list)
    opp_changes: list[tuple[int, OppEntry, OppEntry]] = field(default_factory=list)
    code_patches: list[SemanticDiff] = field(default_factory=list)
    data_patches: list[SemanticDiff] = field(default_factory=list)
    rela_nullifications: list[SemanticDiff] = field(default_factory=list)
    unchanged_metadata: bool = True


def compare(stock_path: str, modified_path: str) -> CompareResult:
    global _seen_opp_entries
    _seen_opp_entries = set()
    result = CompareResult()
    result.stock_path = stock_path
    result.modified_path = modified_path

    with open(stock_path, 'rb') as f:
        stock = f.read()
    with open(modified_path, 'rb') as f:
        modded = f.read()

    result.stock_sha256 = hashlib.sha256(stock).hexdigest()
    result.modified_sha256 = hashlib.sha256(modded).hexdigest()

    for i in range(min(len(stock), len(modded))):
        if stock[i] != modded[i]:
            result.total_differing_bytes += 1

    diff_ranges = _merge_diff_ranges(stock, modded)

    for r_start, r_end in diff_ranges:
        orig = stock[r_start:r_end + 1]
        mod = modded[r_start:r_end + 1]
        sec_name = _section_for_offset(stock, r_start)

        diff = SemanticDiff(
            file_offset=r_start,
            length=r_end - r_start + 1,
            section_name=sec_name,
            original_bytes=orig,
            modified_bytes=mod,
            semantic_purpose=_classify_diff(stock, modded, r_start, r_end),
            confidence='high',
        )

        if diff.semantic_purpose.startswith('OPP'):
            parsed = _parse_opp_diff(stock, modded, r_start)
            if parsed is not None:
                result.opp_changes.append(parsed)
            result.diffs.append(diff)
        elif 'NOP' in diff.semantic_purpose or 'BL' in diff.semantic_purpose:
            diff.confidence = 'high'
            result.code_patches.append(diff)
            result.diffs.append(diff)
        elif 'segment' in diff.semantic_purpose.lower():
            result.data_patches.append(diff)
            result.diffs.append(diff)
        elif 'relocation' in diff.semantic_purpose.lower():
            result.rela_nullifications.append(diff)
            result.diffs.append(diff)
        elif _patch_description(r_start) is not None:
            diff.semantic_purpose = _patch_description(r_start)
            result.code_patches.append(diff)
            result.diffs.append(diff)
        else:
            result.diffs.append(diff)

    return result


def _merge_diff_ranges(stock: bytes, modded: bytes, max_gap: int = 16) -> list[tuple[int, int]]:
    diffs = [i for i in range(min(len(stock), len(modded))) if stock[i] != modded[i]]
    if not diffs:
        return []
    ranges = []
    start = diffs[0]
    prev = diffs[0]
    for d in diffs[1:]:
        if d - prev > max_gap:
            ranges.append((start, prev))
            start = d
        prev = d
    ranges.append((start, prev))
    return ranges


def _classify_diff(stock: bytes, modded: bytes, start: int, end: int) -> str:
    length = end - start + 1
    sec = _section_for_offset(stock, start)

    # Detect OPP table by structural analysis rather than hardcoded offset
    try:
        elff = elf.Elf64(stock)
        from .gpufreq import analyze as gf_analyze
        gf = gf_analyze(elff)
        if gf.opp_table is not None:
            opp_base = gf.opp_table_file_offset
            opp_end = opp_base + len(gf.opp_table) * OPP_ENTRY_SIZE
            if opp_base <= start < opp_end:
                rel = start - opp_base
                entry_idx = rel // OPP_ENTRY_SIZE
                field_names = ['freq_khz', 'volt', 'vsram', 'u3', 'u4', 'u5']
                field_idx = (rel % OPP_ENTRY_SIZE) // 4
                field = field_names[field_idx] if field_idx < 6 else '?'
                return f'OPP entry[{entry_idx}].{field}'
    except Exception:
        pass

    known = {0x8da4: 'apply_adjust_probe: BL->NOP', 0x96fc: 'avs_freq_check: B.NE->NOP',
             0x98f8: 'apply_adjust_avs: BL->NOP', 0xc814: 'g_segment_adj: 25->0'}
    if start in known:
        return known[start]

    if sec.startswith('.rela'):
        return 'relocation nullification (R_AARCH64_NONE)'

    return f'{sec} [+0x{start:#x}]'


def _patch_description(offset: int) -> Optional[str]:
    descs = {
        0x8da4: 'apply_adjust_probe_bypass: BL -> NOP',
        0x96fc: 'avs_freq_check_bypass: B.NE -> NOP',
        0x98f8: 'apply_adjust_avs_bypass: BL -> NOP',
        0xc814: 'g_segment_adj: 25 -> 0',
        0x1afd8: 'relocation nullification (apply_adjust_probe rela entry)',
        0x1c4f0: 'relocation nullification (apply_adjust_avs rela entry)',
    }
    return descs.get(offset)


def _section_for_offset(data: bytes, offset: int) -> str:
    try:
        elff = elf.Elf64(data)
        sec = elff.section_containing_file_offset(offset)
        return sec.name if sec else '(unknown)'
    except Exception:
        return '(unknown)'


_seen_opp_entries: set = set()

def _detect_opp_table_base(stock: bytes) -> int:
    try:
        elff = elf.Elf64(stock)
        from .gpufreq import analyze as gf_analyze
        gf = gf_analyze(elff)
        if gf.opp_table is not None:
            return gf.opp_table_file_offset
    except Exception:
        pass
    return 0


def _parse_opp_diff(stock: bytes, modded: bytes, offset: int) -> Optional[tuple[int, OppEntry, OppEntry]]:
    global _seen_opp_entries
    opp_base = _detect_opp_table_base(stock)
    if opp_base == 0:
        return None
    rel = offset - opp_base
    if rel < 0:
        return None
    entry_idx = rel // OPP_ENTRY_SIZE
    if entry_idx in _seen_opp_entries:
        return None
    _seen_opp_entries.add(entry_idx)
    aligned = opp_base + entry_idx * OPP_ENTRY_SIZE
    if aligned + OPP_ENTRY_SIZE > len(stock):
        return None
    stock_entry = OppEntry.from_bytes(stock, aligned)
    modded_entry = OppEntry.from_bytes(modded, aligned)
    if stock_entry.freq_khz == modded_entry.freq_khz and stock_entry.volt == modded_entry.volt:
        return None
    return (entry_idx, stock_entry, modded_entry)
