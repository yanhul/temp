import unittest

from address_space import AddressMap, AddressMappingError, Section


class AddressMapTests(unittest.TestCase):
    def setUp(self):
        self.mapping = AddressMap(
            image_base=0x140000000,
            file_size=0x900,
            sections=[
                Section(".text", 0x200, 0x1000, 0x300, 0x400),
                Section(".data", 0x600, 0x2000, 0x100, 0x100),
            ],
        )

    def test_file_offset_to_va(self):
        self.assertEqual(self.mapping.file_offset_to_va(0x210), 0x140001010)

    def test_va_to_file_offset(self):
        self.assertEqual(self.mapping.va_to_file_offset(0x140001010), 0x210)

    def test_round_trip(self):
        for offset in (0x200, 0x210, 0x4ff, 0x600, 0x6ff):
            self.assertEqual(self.mapping.va_to_file_offset(
                self.mapping.file_offset_to_va(offset)), offset)

    def test_rejects_unmapped_file_gap(self):
        with self.assertRaises(AddressMappingError):
            self.mapping.file_offset_to_va(0x550)

    def test_rejects_virtual_only_bytes(self):
        with self.assertRaises(AddressMappingError):
            self.mapping.va_to_file_offset(0x140001350)

    def test_rejects_overlapping_sections(self):
        with self.assertRaises(AddressMappingError):
            AddressMap(image_base=0x400000, file_size=0x1000, sections=[
                Section(".a", 0x100, 0x1000, 0x300, 0x300),
                Section(".b", 0x300, 0x2000, 0x200, 0x200),
            ])

    def test_rejects_non_section_record_without_leaking_attribute_error(self):
        with self.assertRaisesRegex(AddressMappingError, "Section record"):
            AddressMap(image_base=0, file_size=0x100, sections=[None])

    def test_rejects_overlapping_virtual_ranges_even_when_file_ranges_do_not_overlap(self):
        with self.assertRaisesRegex(AddressMappingError, "virtual section ranges overlap"):
            AddressMap(image_base=0x400000, file_size=0x1000, sections=[
                Section(".a", 0x100, 0x1000, 0x100, 0x300),
                Section(".b", 0x400, 0x1200, 0x100, 0x100),
            ])

    def test_rejects_section_outside_file(self):
        with self.assertRaises(AddressMappingError):
            AddressMap(image_base=0, file_size=0x100, sections=[
                Section(".bad", 0x80, 0x1000, 0x100, 0x100),
            ])

    def test_rejects_raw_padding_beyond_virtual_size(self):
        mapping = AddressMap(image_base=0x400000, file_size=0x500, sections=[
            Section(".odd", 0x100, 0x1000, 0x200, 0x100),
        ])
        with self.assertRaises(AddressMappingError):
            mapping.file_offset_to_va(0x280)
        with self.assertRaises(AddressMappingError):
            mapping.va_to_file_offset(0x401180)

    def test_rejects_boolean_offset(self):
        with self.assertRaises(AddressMappingError):
            self.mapping.file_offset_to_va(True)

    def test_rejects_boolean_image_base(self):
        with self.assertRaises(AddressMappingError):
            AddressMap(image_base=True, file_size=0x100, sections=[
                Section(".text", 0, 0, 0x100, 0x100),
            ])

    def test_rejects_raw_data_with_zero_virtual_size(self):
        with self.assertRaises(AddressMappingError):
            AddressMap(image_base=0x400000, file_size=0x500, sections=[
                Section(".odd", 0x100, 0x1000, 0x200, 0),
            ])


if __name__ == "__main__":
    unittest.main()
