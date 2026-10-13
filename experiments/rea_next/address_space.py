"""Explicit file-offset/RVA/VA mapping for PE-like section layouts.

This utility intentionally refuses ambiguous, overlapping, or unbacked mappings.
It does not parse executables; callers must supply section metadata from a trusted parser.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class AddressMappingError(ValueError):
    """Raised when an address cannot be mapped without guessing."""


@dataclass(frozen=True)
class Section:
    name: str
    file_offset: int
    virtual_address: int  # RVA, relative to image base
    raw_size: int
    virtual_size: int


class AddressMap:
    def __init__(
        self,
        *,
        image_base: int,
        sections: Iterable[Section],
        file_size: int,
    ) -> None:
        if image_base < 0 or file_size <= 0:
            raise AddressMappingError("image_base must be non-negative and file_size positive")
        self.image_base = image_base
        self.file_size = file_size
        self.sections = tuple(sections)
        if not self.sections:
            raise AddressMappingError("at least one section is required")
        for s in self.sections:
            if not s.name or min(s.file_offset, s.virtual_address, s.raw_size, s.virtual_size) < 0:
                raise AddressMappingError("section fields must be non-negative and name non-empty")
            if s.raw_size == 0 and s.virtual_size == 0:
                raise AddressMappingError("empty sections are not mappable")
            if s.file_offset + s.raw_size > file_size:
                raise AddressMappingError(f"section {s.name} exceeds file size")
        self._check_nonoverlap(
            [(s.file_offset, s.file_offset + s.raw_size, s.name) for s in self.sections if s.raw_size],
            "file-backed section ranges overlap",
        )
        self._check_nonoverlap(
            [(s.virtual_address, s.virtual_address + max(s.raw_size, s.virtual_size), s.name)
             for s in self.sections if max(s.raw_size, s.virtual_size)],
            "virtual section ranges overlap",
        )

    @staticmethod
    def _check_nonoverlap(ranges: list[tuple[int, int, str]], message: str) -> None:
        ranges.sort()
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1]:
                raise AddressMappingError(f"{message}: {previous[2]} / {current[2]}")

    def file_offset_to_va(self, offset: int) -> int:
        if offset < 0 or offset >= self.file_size:
            raise AddressMappingError("file offset is outside the file")
        matches = [s for s in self.sections if s.file_offset <= offset < s.file_offset + s.raw_size]
        if len(matches) != 1:
            raise AddressMappingError("file offset is not uniquely mapped by supplied sections")
        section = matches[0]
        return self.image_base + section.virtual_address + (offset - section.file_offset)

    def va_to_file_offset(self, va: int) -> int:
        if va < self.image_base:
            raise AddressMappingError("VA is below image base")
        rva = va - self.image_base
        matches = [
            s for s in self.sections
            if s.virtual_address <= rva < s.virtual_address + max(s.raw_size, s.virtual_size)
        ]
        if len(matches) != 1:
            raise AddressMappingError("VA is not uniquely mapped by supplied sections")
        section = matches[0]
        delta = rva - section.virtual_address
        if delta >= section.raw_size:
            raise AddressMappingError("VA points to virtual-only bytes with no file backing")
        offset = section.file_offset + delta
        if offset >= self.file_size:
            raise AddressMappingError("mapped file offset is outside the file")
        return offset
