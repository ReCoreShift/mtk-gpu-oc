# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import struct
from dataclasses import dataclass
from typing import Optional


EI_NIDENT = 16
SHT_SYMTAB = 2
SHT_RELA = 4
SHT_STRTAB = 3
SHT_NOBITS = 8

R_AARCH64_NONE = 0
R_AARCH64_CALL26 = 0x11b


class ElfError(Exception):
    ...


class NotAnElfFile(ElfError):
    ...


class UnsupportedElfClass(ElfError):
    ...


@dataclass
class Section:
    name: str
    index: int
    sh_type: int
    flags: int
    addr: int
    offset: int
    size: int
    entsize: int
    link: int
    info: int
    addralign: int


@dataclass
class Symbol:
    name: str
    index: int
    value: int
    size: int
    bind: int
    typ: int
    shndx: int


@dataclass
class RelaEntry:
    offset: int
    info: int
    addend: int

    @property
    def r_sym(self) -> int:
        return self.info >> 32

    @property
    def r_type(self) -> int:
        return self.info & 0xFFFFFFFF


class Elf64:
    def __init__(self, data: bytes):
        if len(data) < 64:
            raise NotAnElfFile("too short for ELF header")
        if data[:4] != b'\x7fELF':
            raise NotAnElfFile("no ELF magic")
        if data[4] != 2:
            raise UnsupportedElfClass("only ELF64 is supported")
        if data[5] != 1:
            raise ElfError("only little-endian ELF is supported")

        self._data = data
        self._parse_header()

    def _parse_header(self):
        d = self._data
        self.e_type = struct.unpack_from('<H', d, 16)[0]
        self.e_machine = struct.unpack_from('<H', d, 18)[0]
        self.e_entry = struct.unpack_from('<Q', d, 24)[0]
        self.e_shoff = struct.unpack_from('<Q', d, 0x28)[0]
        self.e_flags = struct.unpack_from('<I', d, 0x30)[0]
        self.e_ehsize = struct.unpack_from('<H', d, 0x34)[0]
        self.e_shentsize = struct.unpack_from('<H', d, 0x3a)[0]
        self.e_shnum = struct.unpack_from('<H', d, 0x3c)[0]
        self.e_shstrndx = struct.unpack_from('<H', d, 0x3e)[0]

    def file_size(self) -> int:
        return len(self._data)

    def raw(self) -> bytes:
        return self._data

    def is_relocatable(self) -> bool:
        return self.e_type == 1  # ET_REL

    def _section_header_offset(self, index: int) -> int:
        return self.e_shoff + index * self.e_shentsize

    def _read_section_name(self, index: int) -> str:
        stroff = self._section_header_offset(self.e_shstrndx)
        str_off = struct.unpack_from('<Q', self._data, stroff + 0x18)[0]
        name_off = struct.unpack_from('<I', self._data, self._section_header_offset(index))[0]
        end = self._data.index(b'\x00', str_off + name_off)
        return self._data[str_off + name_off:end].decode('ascii', errors='replace')

    def sections(self) -> list[Section]:
        result = []
        for i in range(self.e_shnum):
            sh_off = self._section_header_offset(i)
            d = self._data
            result.append(Section(
                name=self._read_section_name(i),
                index=i,
                sh_type=struct.unpack_from('<I', d, sh_off + 4)[0],
                flags=struct.unpack_from('<Q', d, sh_off + 8)[0],
                addr=struct.unpack_from('<Q', d, sh_off + 0x10)[0],
                offset=struct.unpack_from('<Q', d, sh_off + 0x18)[0],
                size=struct.unpack_from('<Q', d, sh_off + 0x20)[0],
                entsize=struct.unpack_from('<Q', d, sh_off + 0x38)[0],
                link=struct.unpack_from('<I', d, sh_off + 0x28)[0],
                info=struct.unpack_from('<I', d, sh_off + 0x2c)[0],
                addralign=struct.unpack_from('<Q', d, sh_off + 0x30)[0],
            ))
        return result

    def find_section(self, name: str) -> Optional[Section]:
        for s in self.sections():
            if s.name == name:
                return s
        return None

    def find_sections_by_type(self, sh_type: int) -> list[Section]:
        return [s for s in self.sections() if s.sh_type == sh_type]

    def symbols(self) -> list[Symbol]:
        symtab = self.find_section_by_type(SHT_SYMTAB)
        if symtab is None:
            return []

        strtab_sec = self.sections()[symtab.link] if symtab.link < len(self.sections()) else None
        strtab_data = self._data[strtab_sec.offset:strtab_sec.offset + strtab_sec.size] if strtab_sec else b''

        result = []
        for i in range(symtab.size // symtab.entsize):
            off = symtab.offset + i * symtab.entsize
            st_name = struct.unpack_from('<I', self._data, off)[0]
            st_info = self._data[off + 4]
            st_other = self._data[off + 5]
            st_shndx = struct.unpack_from('<H', self._data, off + 6)[0]
            st_value = struct.unpack_from('<Q', self._data, off + 8)[0]
            st_size = struct.unpack_from('<Q', self._data, off + 16)[0]

            name = ''
            if st_name > 0 and st_name < len(strtab_data):
                end = strtab_data.index(b'\x00', st_name)
                name = strtab_data[st_name:end].decode('ascii', errors='replace')

            result.append(Symbol(
                name=name,
                index=i,
                value=st_value,
                size=st_size,
                bind=st_info >> 4,
                typ=st_info & 0x0F,
                shndx=st_shndx,
            ))
        return result

    def find_symbol(self, name: str) -> Optional[Symbol]:
        for sym in self.symbols():
            if sym.name == name:
                return sym
        return None

    def find_symbols_by_prefix(self, prefix: str) -> list[Symbol]:
        return [s for s in self.symbols() if s.name.startswith(prefix)]

    def section_containing_file_offset(self, file_offset: int) -> Optional[Section]:
        for sec in self.sections():
            if sec.sh_type == SHT_NOBITS:
                continue
            if sec.offset <= file_offset < sec.offset + sec.size:
                return sec
        return None

    def find_section_by_type(self, sh_type: int) -> Optional[Section]:
        for s in self.sections():
            if s.sh_type == sh_type:
                return s
        return None

    def relocations_for_section(self, target_section: Section) -> list[RelaEntry]:
        result = []
        for sec in self.sections():
            if sec.sh_type != SHT_RELA:
                continue
            if sec.info != target_section.index:
                continue
            for j in range(0, sec.size, sec.entsize):
                off = sec.offset + j
                r_offset = struct.unpack_from('<Q', self._data, off)[0]
                r_info = struct.unpack_from('<Q', self._data, off + 8)[0]
                r_addend = struct.unpack_from('<Q', self._data, off + 16)[0]
                result.append(RelaEntry(r_offset, r_info, r_addend))
        return result

    def find_rela_entry(self, target_section: Section, r_offset: int) -> Optional[tuple[Section, int, RelaEntry]]:
        for sec in self.sections():
            if sec.sh_type != SHT_RELA:
                continue
            if sec.info != target_section.index:
                continue
            for j in range(0, sec.size, sec.entsize):
                off = sec.offset + j
                ro = struct.unpack_from('<Q', self._data, off)[0]
                if ro == r_offset:
                    r_info = struct.unpack_from('<Q', self._data, off + 8)[0]
                    r_addend = struct.unpack_from('<Q', self._data, off + 16)[0]
                    entry_idx = j // sec.entsize
                    return (sec, entry_idx, RelaEntry(ro, r_info, r_addend))
        return None
