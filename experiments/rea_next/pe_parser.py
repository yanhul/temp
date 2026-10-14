"""Strict, read-only PE32/PE32+ header parser for address mapping.

This parser extracts metadata only. It never loads or executes the input image.
Unsupported or malformed layouts fail closed rather than guessing mappings.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from address_space import AddressMap, AddressMappingError, Section


class PEFormatError(ValueError):
    """Raised when input is not a supported, internally consistent PE image."""


@dataclass(frozen=True)
class ParsedPE:
    architecture: str
    image_base: int
    size_of_image: int
    size_of_headers: int
    section_alignment: int
    file_alignment: int
    address_map: AddressMap


def _u16(data: bytes, off: int) -> int:
    if off < 0 or off + 2 > len(data):
        raise PEFormatError("truncated 16-bit field")
    return struct.unpack_from("<H", data, off)[0]


def _u32(data: bytes, off: int) -> int:
    if off < 0 or off + 4 > len(data):
        raise PEFormatError("truncated 32-bit field")
    return struct.unpack_from("<I", data, off)[0]


def _u64(data: bytes, off: int) -> int:
    if off < 0 or off + 8 > len(data):
        raise PEFormatError("truncated 64-bit field")
    return struct.unpack_from("<Q", data, off)[0]


def _power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def parse_pe(data: bytes) -> ParsedPE:
    """Parse PE32/PE32+ section metadata from bytes, rejecting malformed bounds."""
    if not isinstance(data, bytes) or len(data) < 0x40:
        raise PEFormatError("input must be bytes containing a complete DOS header")
    if data[:2] != b"MZ":
        raise PEFormatError("missing DOS MZ signature")
    pe_off = _u32(data, 0x3C)
    if pe_off < 0x40 or pe_off + 24 > len(data):
        raise PEFormatError("PE header offset is outside the file")
    if data[pe_off:pe_off + 4] != b"PE\0\0":
        raise PEFormatError("missing PE signature")

    coff = pe_off + 4
    machine = _u16(data, coff)
    section_count = _u16(data, coff + 2)
    optional_size = _u16(data, coff + 16)
    if section_count < 1 or section_count > 96:
        raise PEFormatError("unsupported section count")
    opt = coff + 20
    opt_end = opt + optional_size
    if opt_end > len(data):
        raise PEFormatError("optional header is truncated")
    magic = _u16(data, opt)
    if magic == 0x10B:
        architecture = "PE32"
        if optional_size < 96:
            raise PEFormatError("PE32 optional header is shorter than the required structure")
        image_base = _u32(data, opt + 28)
    elif magic == 0x20B:
        architecture = "PE32+"
        if optional_size < 112:
            raise PEFormatError("PE32+ optional header is shorter than the required structure")
        image_base = _u64(data, opt + 24)
    else:
        raise PEFormatError("unsupported optional-header magic")
    # This prototype only claims verified layout support for x86 and x64.
    # Reject unknown machine types instead of treating them as generic layouts.
    if machine not in (0x014C, 0x8664):
        raise PEFormatError("unsupported COFF machine type")
    if (machine == 0x014C and architecture != "PE32") or (
        machine == 0x8664 and architecture != "PE32+"
    ):
        raise PEFormatError("COFF machine contradicts optional-header magic")
    # Fields used below must be inside the declared optional header, not merely the file.
    if optional_size < 64:
        raise PEFormatError("optional header is too small for required fields")
    section_alignment = _u32(data, opt + 32)
    file_alignment = _u32(data, opt + 36)
    size_of_image = _u32(data, opt + 56)
    size_of_headers = _u32(data, opt + 60)
    if not _power_of_two(file_alignment) or not _power_of_two(section_alignment):
        raise PEFormatError("section/file alignment must be nonzero powers of two")
    if file_alignment > 0x10000 or section_alignment > 0x10000000:
        raise PEFormatError("alignment exceeds supported bounds")
    if section_alignment < 0x1000 and section_alignment != file_alignment:
        raise PEFormatError("low section alignment must equal file alignment")
    if section_alignment >= 0x1000:
        if file_alignment < 0x200:
            raise PEFormatError("file alignment is below the standard minimum")
        if file_alignment > section_alignment:
            raise PEFormatError("file alignment exceeds section alignment")
    if (size_of_image <= 0 or size_of_headers <= 0 or size_of_headers > len(data)
            or size_of_headers > size_of_image):
        raise PEFormatError("invalid SizeOfImage or SizeOfHeaders")
    if image_base % 0x10000:
        raise PEFormatError("ImageBase is not aligned to 64 KiB")
    address_limit = 1 << (32 if architecture == "PE32" else 64)
    if image_base + size_of_image > address_limit:
        raise PEFormatError("image extends beyond the architecture address space")

    table = opt_end
    table_end = table + section_count * 40
    if table_end > len(data) or table_end > size_of_headers:
        raise PEFormatError("section table is truncated or exceeds SizeOfHeaders")
    if size_of_headers % file_alignment:
        raise PEFormatError("SizeOfHeaders is not file-aligned")

    sections = []
    max_virtual_end = 0
    for i in range(section_count):
        off = table + i * 40
        raw_name = data[off:off + 8].split(b"\0", 1)[0]
        try:
            name = raw_name.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PEFormatError("section name is not ASCII") from exc
        if not name:
            name = f"section_{i}"
        virtual_size = _u32(data, off + 8)
        virtual_address = _u32(data, off + 12)
        raw_size = _u32(data, off + 16)
        raw_pointer = _u32(data, off + 20)
        if virtual_address % section_alignment:
            raise PEFormatError(f"section {name} RVA is not section-aligned")
        if virtual_address < size_of_headers:
            raise PEFormatError(f"section {name} virtual range overlaps image headers")
        if raw_size:
            if raw_pointer < size_of_headers or raw_pointer % file_alignment or raw_size % file_alignment:
                raise PEFormatError(f"section {name} raw range violates header/alignment constraints")
            if raw_pointer + raw_size > len(data):
                raise PEFormatError(f"section {name} raw range exceeds file")
        if virtual_size == 0 and raw_size == 0:
            raise PEFormatError(f"section {name} has no contents")
        if virtual_size == 0 and raw_size > 0:
            raise PEFormatError(f"section {name} has raw data but zero virtual size")
        extent = max(virtual_size, raw_size)
        max_virtual_end = max(max_virtual_end, virtual_address + extent)
        sections.append(Section(name, raw_pointer, virtual_address, raw_size, virtual_size))

    if size_of_image % section_alignment:
        raise PEFormatError("SizeOfImage is not section-aligned")
    if max_virtual_end > size_of_image:
        raise PEFormatError("section virtual range exceeds SizeOfImage")
    try:
        address_map = AddressMap(image_base=image_base, sections=sections, file_size=len(data))
    except AddressMappingError as exc:
        raise PEFormatError(f"invalid section mapping: {exc}") from exc
    return ParsedPE(architecture, image_base, size_of_image, size_of_headers,
                    section_alignment, file_alignment, address_map)
