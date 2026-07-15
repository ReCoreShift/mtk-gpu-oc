# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from dataclasses import dataclass, field
from typing import Optional

from . import elf
from .opp import OppTable, OppEntry, OPP_ENTRY_SIZE


OPP_TABLE_SYMBOL = 'g_default_gpu'
SEGMENT_ADJ_SYMBOL = 'g_segment_adj'
APPLY_ADJUST_SYMBOL = 'gpufreq_apply_adjust'
AVS_ADJUSTMENT_SYMBOL = 'gpufreq_avs_adjustment'
PDRV_PROBE_SYMBOL = 'gpufreq_pdrv_probe'
INIT_OPP_IDX_SYMBOL = 'gpufreq_init_opp_idx'


class DetectionStatus:
    SUPPORTED = 'supported'
    UNSUPPORTED = 'unsupported'
    AMBIGUOUS = 'ambiguous'
    ALREADY_PATCHED = 'already_patched'
    CORRUPT = 'corrupt'


@dataclass
class GpufreqAnalysis:
    status: str = DetectionStatus.UNSUPPORTED
    module_name: str = ''
    module_version: str = ''
    build_id: str = ''
    is_stripped: bool = False

    opp_table: Optional[OppTable] = None
    opp_table_file_offset: Optional[int] = None
    opp_table_section: str = ''
    opp_table_symbol: str = ''

    segment_adj_offset: Optional[int] = None
    segment_adj_value: Optional[int] = None
    segment_adj_section: str = ''

    avs_freq_check_offset: Optional[int] = None
    avs_freq_check_present: bool = False
    avs_freq_check_already_patched: bool = False

    apply_adjust_probe_offset: Optional[int] = None
    apply_adjust_probe_present: bool = False
    apply_adjust_probe_already_patched: bool = False

    apply_adjust_avs_offset: Optional[int] = None
    apply_adjust_avs_present: bool = False
    apply_adjust_avs_already_patched: bool = False

    patch_sites: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


_AVS_FREQ_CHECK_PATTERN = bytes.fromhex('9f 00 05 6b 21 22 00 54')
_AVS_FREQ_CHECK_NOP = bytes.fromhex('9f 00 05 6b 1f 20 03 d5')

_APPLY_ADJUST_PROBE_PATTERN = bytes.fromhex('e0 03 14 aa e1 03 13 2a 00 00 00 94')
_APPLY_ADJUST_PROBE_NOP = bytes.fromhex('e0 03 14 aa e1 03 13 2a 1f 20 03 d5')

_APPLY_ADJUST_AVS_PATTERN = bytes.fromhex('61 00 80 52 e0 03 13 aa 00 00 00 94')
_APPLY_ADJUST_AVS_NOP = bytes.fromhex('61 00 80 52 e0 03 13 aa 1f 20 03 d5')

_SEGMENT_ADJ_STOCK = bytes.fromhex('19 00 00 00 00 00 00 00 e8 fd 00 00')
_SEGMENT_ADJ_PATCHED = bytes.fromhex('00 00 00 00 00 00 00 00 e8 fd 00 00')


def analyze(elf_file: elf.Elf64) -> GpufreqAnalysis:
    result = GpufreqAnalysis()
    data = elf_file.raw()

    _detect_module_info(elf_file, result)
    _detect_opp_table(elf_file, result)
    _detect_segment_adj(elf_file, data, result)
    _detect_patch_sites(elf_file, data, result)

    if (result.opp_table is not None
            and result.segment_adj_offset is not None
            and result.avs_freq_check_present
            and result.apply_adjust_probe_present
            and result.apply_adjust_avs_present):
        result.status = DetectionStatus.SUPPORTED

    return result


def _detect_module_info(elf_file: elf.Elf64, result: GpufreqAnalysis):
    modinfo = elf_file.find_section('.modinfo')
    if modinfo is not None:
        d = elf_file.raw()
        text = d[modinfo.offset:modinfo.offset + modinfo.size]
        for line in text.split(b'\x00'):
            if b'=' in line:
                k, v = line.split(b'=', 1)
                decoded = v.decode('ascii', errors='replace')
                if k == b'name':
                    result.module_name = decoded

    note_gnu = elf_file.find_section('.note.gnu.build-id')
    if note_gnu is not None:
        d = elf_file.raw()
        desc = d[note_gnu.offset + 16:note_gnu.offset + note_gnu.size]
        import hashlib
        h = hashlib.sha256(desc).hexdigest()[:12]
        result.build_id = desc.hex() if len(desc) <= 32 else desc[:32].hex()

    symtab = elf_file.find_section_by_type(elf.SHT_SYMTAB)
    if symtab is None or symtab.size == 0:
        result.is_stripped = True


def _detect_opp_table(elf_file: elf.Elf64, result: GpufreqAnalysis):
    sym = elf_file.find_symbol(OPP_TABLE_SYMBOL)
    if sym is not None and sym.shndx < len(elf_file.sections()):
        sec = elf_file.sections()[sym.shndx]
        file_offset = sec.offset + sym.value
        count = sym.size // OPP_ENTRY_SIZE
        if count > 0 and file_offset + count * OPP_ENTRY_SIZE <= elf_file.file_size():
            table = OppTable.from_bytes(elf_file.raw(), file_offset, count)
            if table.is_descending_frequency() and len(table) >= 2:
                result.opp_table = table
                result.opp_table_file_offset = file_offset
                result.opp_table_section = sec.name
                result.opp_table_symbol = sym.name
                return

    data_sec = elf_file.find_section('.data')
    if data_sec is not None:
        d = elf_file.raw()
        for off in range(data_sec.offset, data_sec.offset + data_sec.size - OPP_ENTRY_SIZE, 4):
            table = OppTable.detect_opp_table(d, off, max_entries=64)
            if table is not None and len(table) >= 10:
                result.opp_table = table
                result.opp_table_file_offset = off
                result.opp_table_section = '.data'
                result.warnings.append('OPP table detected structurally (no symbol)')
                return

    result.warnings.append('OPP table not found')


def _detect_segment_adj(elf_file: elf.Elf64, data: bytes, result: GpufreqAnalysis):
    sym = elf_file.find_symbol(SEGMENT_ADJ_SYMBOL)
    if sym is not None and sym.shndx < len(elf_file.sections()):
        sec = elf_file.sections()[sym.shndx]
        file_offset = sec.offset + sym.value
        if file_offset + 4 <= elf_file.file_size():
            import struct
            val = struct.unpack_from('<I', data, file_offset)[0]
            result.segment_adj_offset = file_offset
            result.segment_adj_value = val
            result.segment_adj_section = sec.name
            return

    pos = data.find(_SEGMENT_ADJ_STOCK)
    if pos >= 0:
        import struct
        val = struct.unpack_from('<I', data, pos)[0]
        result.segment_adj_offset = pos
        result.segment_adj_value = val
        result.warnings.append('g_segment_adj detected by pattern (no symbol)')
        return

    pos = data.find(_SEGMENT_ADJ_PATCHED)
    if pos >= 0:
        result.segment_adj_offset = pos
        result.segment_adj_value = 0
        result.warnings.append('g_segment_adj appears already patched (value=0)')
        return

    result.warnings.append('g_segment_adj not found')


def _detect_patch_sites(elf_file: elf.Elf64, data: bytes, result: GpufreqAnalysis):
    text_sec = elf_file.find_section('.text')
    text_base = text_sec.offset if text_sec else 0

    if text_sec is None:
        result.warnings.append('.text section not found')
        return

    pos = data.find(_AVS_FREQ_CHECK_PATTERN)
    if pos >= 0:
        result.avs_freq_check_offset = pos
        result.avs_freq_check_present = True
        text_rel = pos - text_base
        result.patch_sites.append({
            'name': 'avs_freq_check_bypass',
            'file_offset': pos + 4,
            'text_offset': text_rel + 4,
            'patch_type': 'instruction',
            'description': 'AVS freq check B.NE abort',
        })
    else:
        pos = data.find(_AVS_FREQ_CHECK_NOP)
        if pos >= 0:
            result.avs_freq_check_offset = pos
            result.avs_freq_check_present = True
            result.avs_freq_check_already_patched = True
            result.patch_sites.append({
                'name': 'avs_freq_check_bypass',
                'file_offset': pos + 4,
                'patch_type': 'instruction',
                'status': 'already_patched',
                'description': 'AVS freq check B.NE already NOP\'d',
            })

    pos = data.find(_APPLY_ADJUST_PROBE_PATTERN)
    if pos >= 0:
        result.apply_adjust_probe_offset = pos
        result.apply_adjust_probe_present = True
        bl_offset = pos + 8
        text_rel = bl_offset - text_base
        result.patch_sites.append({
            'name': 'apply_adjust_probe_bypass',
            'file_offset': bl_offset,
            'text_offset': text_rel,
            'patch_type': 'instruction',
            'description': 'BL __gpufreq_apply_adjust in probe path',
        })
        _check_relocation(elf_file, text_rel, result)
    else:
        pos = data.find(_APPLY_ADJUST_PROBE_NOP)
        if pos >= 0:
            result.apply_adjust_probe_offset = pos
            result.apply_adjust_probe_present = True
            result.apply_adjust_probe_already_patched = True

    pos = data.find(_APPLY_ADJUST_AVS_PATTERN)
    if pos >= 0:
        result.apply_adjust_avs_offset = pos
        result.apply_adjust_avs_present = True
        bl_offset = pos + 8
        text_rel = bl_offset - text_base
        result.patch_sites.append({
            'name': 'apply_adjust_avs_bypass',
            'file_offset': bl_offset,
            'text_offset': text_rel,
            'patch_type': 'instruction',
            'description': 'BL __gpufreq_apply_adjust in AVS path',
        })
        _check_relocation(elf_file, text_rel, result)
    else:
        pos = data.find(_APPLY_ADJUST_AVS_NOP)
        if pos >= 0:
            result.apply_adjust_avs_offset = pos
            result.apply_adjust_avs_present = True
            result.apply_adjust_avs_already_patched = True

    if result.segment_adj_offset is not None:
        status = 'already_patched' if result.segment_adj_value == 0 else 'present'
        result.patch_sites.append({
            'name': 'segment_adj_data',
            'file_offset': result.segment_adj_offset,
            'patch_type': 'data',
            'status': status,
            'description': f'g_segment_adj ceiling (value={result.segment_adj_value})',
        })


def _check_relocation(elf_file: elf.Elf64, text_offset: int, result: GpufreqAnalysis):
    text_sec = elf_file.find_section('.text')
    if text_sec is None:
        return
    rela_info = elf_file.find_rela_entry(text_sec, text_offset)
    if rela_info is not None:
        rela_sec, entry_idx, entry = rela_info
        if entry.r_type == elf.R_AARCH64_CALL26:
            target_sym = None
            for sym in elf_file.symbols():
                if sym.index == entry.r_sym:
                    target_sym = sym
                    break
            target_name = target_sym.name if target_sym else f'sym#{entry.r_sym}'
            result.patch_sites[-1]['rela_entry'] = {
                'section': rela_sec.name,
                'index': entry_idx,
                'target_symbol': target_name,
                'file_offset': rela_sec.offset + entry_idx * rela_sec.entsize,
            }
