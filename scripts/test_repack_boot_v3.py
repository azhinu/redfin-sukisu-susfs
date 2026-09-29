import importlib.util
import pathlib
import struct
import unittest

spec = importlib.util.spec_from_file_location(
    "repack", pathlib.Path(__file__).with_name("repack-boot-v3.py")
)
repack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repack)


def template():
    header = bytearray(4096)
    header[:8] = b"ANDROID!"
    struct.pack_into("<II", header, 8, 17, 31)
    struct.pack_into("<I", header, 16, 0x1C00016B)
    struct.pack_into("<I", header, 20, 1580)
    struct.pack_into("<I", header, 40, 3)
    header[44:48] = b"test"
    return bytes(header) + b"K" * 17 + bytes(4079) + b"R" * 31 + bytes(4065)


class RepackTest(unittest.TestCase):
    def test_page_boundary_changes_preserve_header_and_ramdisk(self):
        source = template()
        for size in (1, 4095, 4096, 4097, 8192):
            with self.subTest(size=size):
                kernel = b"N" * size
                image = repack.repack(source + b"Old AVB footer", kernel)
                header, payload, ramdisk, end = repack.sections(image)
                self.assertEqual(header[12:], source[12:4096])
                self.assertEqual(payload, kernel)
                self.assertEqual(ramdisk, b"R" * 31)
                self.assertEqual(end, len(image))
                self.assertNotIn(b"Old AVB footer", image)

    def test_control_is_byte_identical(self):
        source = template()
        self.assertEqual(repack.repack(source, b"K" * 17), source)

    def test_unsupported_header_rejected(self):
        source = bytearray(template())
        struct.pack_into("<I", source, 40, 4)
        with self.assertRaises(ValueError):
            repack.sections(source)

    def test_truncated_ramdisk_rejected(self):
        with self.assertRaises(ValueError):
            repack.sections(template()[:-4096])


if __name__ == "__main__":
    unittest.main()
