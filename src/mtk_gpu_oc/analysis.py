# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from . import elf
from . import profiles
from .gpufreq import analyze as analyze_gpufreq


def analyze_module(path: str) -> dict:
    with open(path, 'rb') as f:
        data = f.read()

    elff = elf.Elf64(data)
    profile = profiles.detect_profile(elff)
    analysis = analyze_gpufreq(elff)

    return {
        'path': path,
        'file_size': len(data),
        'elf_class': 'ELF64',
        'architecture': 'AArch64',
        'endianness': 'little',
        'type': 'REL (relocatable)' if elff.is_relocatable() else str(elff.e_type),
        'stripped': analysis.is_stripped,
        'profile': profile.name if profile else 'unknown',
        'status': analysis.status,
        'module_name': analysis.module_name,
        'build_id': analysis.build_id,
        'opp_table': analysis.opp_table,
        'opp_table_file_offset': analysis.opp_table_file_offset,
        'opp_table_section': analysis.opp_table_section,
        'opp_table_symbol': analysis.opp_table_symbol,
        'segment_adj_offset': analysis.segment_adj_offset,
        'segment_adj_value': analysis.segment_adj_value,
        'patch_sites': analysis.patch_sites,
        'warnings': analysis.warnings,
        'notes': analysis.notes,
    }
