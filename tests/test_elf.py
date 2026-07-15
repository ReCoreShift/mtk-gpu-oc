import struct
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from mtk_gpu_oc.elf import Elf64, NotAnElfFile, UnsupportedElfClass


def _make_elf64_header(e_type=1, e_machine=0x3e, e_shoff=0x200, e_shnum=5, e_shentsize=64, e_shstrndx=4):
    """Create a minimal ELF64 header with section headers."""
    hdr = bytearray(64)
    hdr[0:4] = b'\x7fELF'
    hdr[4] = 2   # ELF64
    hdr[5] = 1   # little-endian
    hdr[6] = 1   # version
    hdr[16:18] = struct.pack('<H', e_type)
    hdr[18:20] = struct.pack('<H', e_machine)
    hdr[0x3a:0x3c] = struct.pack('<H', e_shentsize)
    hdr[0x3c:0x3e] = struct.pack('<H', e_shnum)
    hdr[0x3e:0x40] = struct.pack('<H', e_shstrndx)
    hdr[0x28:0x30] = struct.pack('<Q', e_shoff)
    return bytes(hdr)


def _make_section(name_bytes, sh_type=1, offset=0x300, size=64, entsize=0, addr=0, link=0, info=0):
    sec = bytearray(64)
    # st_name is in shstrtab, just use 0 for simplicity
    sec[0:4] = b'\x00\x00\x00\x00'
    sec[4:8] = struct.pack('<I', sh_type)
    sec[8:16] = struct.pack('<Q', 0x3)  # SHF_ALLOC | SHF_WRITE
    sec[0x10:0x18] = struct.pack('<Q', addr)
    sec[0x18:0x20] = struct.pack('<Q', offset)
    sec[0x20:0x28] = struct.pack('<Q', size)
    sec[0x28:0x2c] = struct.pack('<I', link)
    sec[0x2c:0x30] = struct.pack('<I', info)
    sec[0x30:0x38] = struct.pack('<Q', 0x4)  # addralign
    sec[0x38:0x40] = struct.pack('<Q', entsize)
    return bytes(sec)


def _make_shstrtab(names):
    data = b'\x00'
    for n in names:
        data += n.encode() + b'\x00'
    return data


def test_elf64_parse_header():
    data = _make_elf64_header()
    elff = Elf64(data)
    assert elff.is_relocatable()
    assert elff.file_size() == len(data)
    print("  PASS test_elf64_parse_header")


def test_not_elf():
    try:
        Elf64(b'not an elf file')
        assert False, "should have raised"
    except NotAnElfFile:
        pass
    print("  PASS test_not_elf")


def test_invalid_class():
    hdr = bytearray(64)
    hdr[0:4] = b'\x7fELF'
    hdr[4] = 1   # ELF32
    try:
        Elf64(bytes(hdr))
        assert False, "should have raised"
    except UnsupportedElfClass:
        pass
    print("  PASS test_invalid_class")


def test_too_short():
    try:
        Elf64(b'\x7fELF')
        assert False, "should have raised"
    except NotAnElfFile:
        pass
    print("  PASS test_too_short")


def test_sections():
    shstrtab = b'\x00' + b'.text\x00' + b'\x00' * (32 - 6)
    shstrtab_data = bytearray(shstrtab)

    hdr = _make_elf64_header(e_shoff=0x200, e_shnum=3, e_shstrndx=2, e_shentsize=64)
    data = bytearray(hdr)
    data.extend(b'\x00' * (0x200 - len(hdr)))

    null_sec = bytearray(64)
    data.extend(null_sec)

    text_sec = bytearray(64)
    text_sec[0:4] = struct.pack('<I', 1)
    text_sec[4:8] = struct.pack('<I', 1)
    text_sec[8:16] = struct.pack('<Q', 6)
    text_sec[0x18:0x20] = struct.pack('<Q', 0x300)
    text_sec[0x20:0x28] = struct.pack('<Q', 128)
    data.extend(text_sec)

    shstr_sec = bytearray(64)
    shstr_sec[4:8] = struct.pack('<I', 3)
    shstr_sec[8:16] = struct.pack('<Q', 2)
    shstr_sec[0x18:0x20] = struct.pack('<Q', 0x400)
    shstr_sec[0x20:0x28] = struct.pack('<Q', 32)
    data.extend(shstr_sec)

    data.extend(b'\x00' * (0x300 - len(data)))
    data.extend(b'\x00' * 128)

    data.extend(b'\x00' * (0x400 - len(data)))
    data.extend(shstrtab_data)

    elff = Elf64(bytes(data))
    secs = elff.sections()
    assert len(secs) == 3

    text = elff.find_section('.text')
    assert text is not None
    assert text.offset == 0x300
    assert text.size == 128
    assert text.flags == 6

    print("  PASS test_sections")


if __name__ == '__main__':
    test_elf64_parse_header()
    test_not_elf()
    test_invalid_class()
    test_too_short()
    test_sections()
    print("\nAll ELF tests passed.")
