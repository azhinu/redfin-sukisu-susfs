import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).with_name("extract-ota-images.py")
SPEC = importlib.util.spec_from_file_location("extract_ota_images", SCRIPT)
extractor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extractor)


def varint(value):
    result = bytearray()
    while value >= 0x80:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def field(number, wire_type, value):
    tag = varint((number << 3) | wire_type)
    if wire_type == 0:
        return tag + varint(value)
    return tag + varint(len(value)) + value


def extent(start, count):
    return field(1, 0, start) + field(2, 0, count)


class ExtractOtaImagesTest(unittest.TestCase):
    def test_partition_records_use_current_payload_schema(self):
        partition = field(1, 2, b"boot")
        partition += field(7, 2, field(1, 0, 8192))
        partition += field(8, 2, field(1, 0, extractor.OP_REPLACE))
        records = list(extractor.partition_records(field(13, 2, partition)))
        self.assertEqual(records[0][:3], ("boot", 8192, None))
        self.assertEqual(len(records[0][3]), 1)

    def test_write_operation_spans_multiple_extents(self):
        output = bytearray(16)

        class Output:
            def seek(self, offset):
                self.offset = offset

            def write(self, chunk):
                output[self.offset : self.offset + len(chunk)] = chunk
                self.offset += len(chunk)

        extractor.write_operation(Output(), b"abcdefgh", [(0, 4), (8, 4)])
        self.assertEqual(bytes(output), b"abcd\x00\x00\x00\x00efgh\x00\x00\x00\x00")

    def test_operation_extents_are_block_scaled(self):
        operation = field(6, 2, extent(3, 2))
        self.assertEqual(extractor.operation_extents(operation, 4096), [(12288, 8192)])


if __name__ == "__main__":
    unittest.main()
