import struct
import unittest

from pe_parser import PEFormatError, parse_pe


def make_pe(*, pe32_plus=False, truncate_at=None, bad_raw_pointer=False):
    data = bytearray(0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    struct.pack_into("<H", data, coff, 0x8664 if pe32_plus else 0x14C)
    struct.pack_into("<H", data, coff + 2, 1)
    optional_size = 0xF0
    struct.pack_into("<H", data, coff + 16, optional_size)
    opt = coff + 20
    struct.pack_into("<H", data, opt, 0x20B if pe32_plus else 0x10B)
    if pe32_plus:
        struct.pack_into("<Q", data, opt + 24, 0x140000000)
    else:
        struct.pack_into("<I", data, opt + 28, 0x400000)
    struct.pack_into("<I", data, opt + 32, 0x1000)
    struct.pack_into("<I", data, opt + 36, 0x200)
    struct.pack_into("<I", data, opt + 56, 0x2000)
    struct.pack_into("<I", data, opt + 60, 0x200)
    sec = opt + optional_size
    data[sec:sec + 8] = b".text\0\0\0"
    struct.pack_into("<I", data, sec + 8, 0x180)
    struct.pack_into("<I", data, sec + 12, 0x1000)
    struct.pack_into("<I", data, sec + 16, 0x200)
    struct.pack_into("<I", data, sec + 20, 0 if bad_raw_pointer else 0x200)
    if truncate_at is not None:
        return bytes(data[:truncate_at])
    return bytes(data)


class PEParserTests(unittest.TestCase):
    def test_parses_pe32(self):
        parsed = parse_pe(make_pe())
        self.assertEqual(parsed.architecture, "PE32")
        self.assertEqual(parsed.image_base, 0x400000)
        self.assertEqual(parsed.address_map.file_offset_to_va(0x210), 0x401010)
        self.assertEqual(parsed.address_map.va_to_file_offset(0x401010), 0x210)

    def test_parses_pe32_plus(self):
        parsed = parse_pe(make_pe(pe32_plus=True))
        self.assertEqual(parsed.architecture, "PE32+")
        self.assertEqual(parsed.image_base, 0x140000000)
        self.assertEqual(parsed.address_map.file_offset_to_va(0x210), 0x140001010)

    def test_rejects_non_mz(self):
        data = bytearray(make_pe())
        data[0:2] = b"ZZ"
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_wrong_pe_signature(self):
        data = bytearray(make_pe())
        data[0x80:0x84] = b"NOPE"
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_truncated_dos_header(self):
        with self.assertRaises(PEFormatError):
            parse_pe(b"MZ" + b"\0" * 20)

    def test_rejects_truncated_section_data(self):
        with self.assertRaises(PEFormatError):
            parse_pe(make_pe(truncate_at=0x250))

    def test_rejects_invalid_raw_pointer(self):
        with self.assertRaises(PEFormatError):
            parse_pe(make_pe(bad_raw_pointer=True))

    def test_rejects_invalid_optional_magic(self):
        data = bytearray(make_pe())
        struct.pack_into("<H", data, 0x98, 0x999)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_size_of_image_too_small(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x98 + 56, 0x1000)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_non_power_of_two_file_alignment(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x98 + 36, 0x300)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_section_rva_misalignment(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x188 + 12, 0x1100)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_size_of_headers_larger_than_size_of_image(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x98 + 56, 0x100)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_section_overlapping_image_headers(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x188 + 12, 0)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_short_pe32_optional_header(self):
        data = bytearray(make_pe())
        struct.pack_into("<H", data, 0x84 + 16, 64)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_short_pe32_plus_optional_header(self):
        data = bytearray(make_pe(pe32_plus=True))
        struct.pack_into("<H", data, 0x84 + 16, 64)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_size_of_headers_before_section_table_end(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x98 + 60, 0x100)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_deterministic_header_mutation_never_leaks_internal_exceptions(self):
        import random

        rng = random.Random(0x524541)
        seed = make_pe()
        for _ in range(1500):
            data = bytearray(seed)
            for _ in range(rng.randint(1, 4)):
                index = rng.randrange(len(data))
                data[index] = rng.randrange(256)
            try:
                parse_pe(bytes(data))
            except PEFormatError:
                pass
            except Exception as exc:
                self.fail(f"parser leaked {type(exc).__name__}: {exc}")

    def test_rejects_pe_header_offset_outside_file(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x3C, 0xFFFFFFF0)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_overlapping_raw_sections(self):
        data = bytearray(make_pe())
        coff = 0x84
        struct.pack_into("<H", data, coff + 2, 2)
        sec2 = 0x188 + 40
        data[sec2:sec2 + 8] = b".data\0\0\0"
        struct.pack_into("<I", data, sec2 + 8, 0x100)
        struct.pack_into("<I", data, sec2 + 12, 0x2000)
        struct.pack_into("<I", data, sec2 + 16, 0x200)
        struct.pack_into("<I", data, sec2 + 20, 0x200)
        # Keep the second virtual range inside SizeOfImage so this test fails
        # specifically because the raw file ranges overlap, not due to bounds.
        struct.pack_into("<I", data, 0x98 + 56, 0x3000)
        with self.assertRaisesRegex(PEFormatError, "invalid section mapping"):
            parse_pe(bytes(data))

    def test_rejects_unknown_coff_machine(self):
        data = bytearray(make_pe())
        struct.pack_into("<H", data, 0x84, 0x9999)
        with self.assertRaisesRegex(PEFormatError, "unsupported COFF machine"):
            parse_pe(bytes(data))

    def test_rejects_i386_with_pe32_plus_optional_header(self):
        data = bytearray(make_pe(pe32_plus=True))
        struct.pack_into("<H", data, 0x84, 0x014C)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_amd64_with_pe32_optional_header(self):
        data = bytearray(make_pe())
        struct.pack_into("<H", data, 0x84, 0x8664)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_file_alignment_greater_than_section_alignment(self):
        data = bytearray(0x4000)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = bytes((0x50, 0x45, 0, 0))
        coff = 0x84
        struct.pack_into("<H", data, coff, 0x014C)
        struct.pack_into("<H", data, coff + 2, 1)
        struct.pack_into("<H", data, coff + 16, 0xF0)
        opt = coff + 20
        struct.pack_into("<H", data, opt, 0x10B)
        struct.pack_into("<I", data, opt + 28, 0x400000)
        struct.pack_into("<I", data, opt + 32, 0x1000)
        struct.pack_into("<I", data, opt + 36, 0x2000)
        struct.pack_into("<I", data, opt + 56, 0x4000)
        struct.pack_into("<I", data, opt + 60, 0x2000)
        sec = opt + 0xF0
        data[sec:sec + 8] = b".text\\0\\0\\0"
        struct.pack_into("<I", data, sec + 8, 0x2000)
        struct.pack_into("<I", data, sec + 12, 0x2000)
        struct.pack_into("<I", data, sec + 16, 0x2000)
        struct.pack_into("<I", data, sec + 20, 0x2000)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_misaligned_image_base(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x98 + 28, 0x401000)
        with self.assertRaisesRegex(PEFormatError, "ImageBase"):
            parse_pe(bytes(data))

    def test_rejects_pe32_image_past_32bit_address_space(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x98 + 28, 0xFFFFF000)
        struct.pack_into("<I", data, 0x98 + 56, 0x2000)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))

    def test_rejects_raw_data_with_zero_virtual_size(self):
        data = bytearray(make_pe())
        struct.pack_into("<I", data, 0x188 + 8, 0)
        with self.assertRaises(PEFormatError):
            parse_pe(bytes(data))


if __name__ == "__main__":
    unittest.main()
