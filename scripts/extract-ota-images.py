#!/usr/bin/env python3
"""Extract selected full partitions from an Android OTA payload."""

import argparse
import bz2
import hashlib
import lzma
import pathlib
import struct
import zipfile

BLOCK_SIZE = 4096
MAX_UINT64 = (1 << 64) - 1
OP_REPLACE = 0
OP_REPLACE_BZ = 1
OP_ZERO = 6
OP_DISCARD = 7
OP_REPLACE_XZ = 8
OP_REPLACE_ZSTD = 14


class PayloadError(ValueError):
    """Raised when an OTA payload cannot be safely extracted."""


def read_varint(data, offset):
    value = 0
    shift = 0
    while True:
        if offset >= len(data) or shift >= 70:
            raise PayloadError("Invalid protobuf varint.")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7


def protobuf_fields(data):
    """Yield (field number, wire type, value) for a protobuf message."""
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        number, wire_type = tag >> 3, tag & 0x07
        if number == 0:
            raise PayloadError("Invalid protobuf field number.")
        if wire_type == 0:
            value, offset = read_varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            value = data[offset:end]
            offset = end
        elif wire_type == 2:
            length, offset = read_varint(data, offset)
            end = offset + length
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            end = offset + 4
            value = data[offset:end]
            offset = end
        else:
            raise PayloadError(f"Unsupported protobuf wire type: {wire_type}.")
        yield number, wire_type, value


def field_values(data, number):
    return [value for field, _, value in protobuf_fields(data) if field == number]


def required_varint(data, number, label):
    values = field_values(data, number)
    if not values or not isinstance(values[0], int):
        raise PayloadError(f"Payload field is missing: {label}.")
    return values[0]


def optional_varint(data, number, default=0):
    values = field_values(data, number)
    return values[0] if values else default


def extent_bytes(extent, block_size):
    return required_varint(extent, 2, "extent block count") * block_size


def partition_records(manifest):
    for partition in field_values(manifest, 13):
        names = field_values(partition, 1)
        info = field_values(partition, 7)
        if not names or not info:
            raise PayloadError("Partition record is missing its name or size.")
        name = names[0].decode("utf-8")
        size = required_varint(info[0], 1, f"{name} size")
        expected_hash = field_values(info[0], 2)
        operations = field_values(partition, 8)
        yield name, size, expected_hash[0] if expected_hash else None, operations


def operation_extents(operation, block_size):
    extents = field_values(operation, 6)
    if not extents:
        raise PayloadError("Install operation has no destination extents.")
    result = []
    for extent in extents:
        start = required_varint(extent, 1, "extent start block")
        count = required_varint(extent, 2, "extent block count")
        if start == MAX_UINT64:
            raise PayloadError("Sparse destination extents are not supported.")
        result.append((start * block_size, count * block_size))
    return result


def payload_header(payload):
    header = payload.read(24)
    if len(header) != 24 or header[:4] != b"CrAU":
        raise PayloadError("Input does not contain an Android OTA payload.")
    version, manifest_size, signature_size = struct.unpack(">QQI", header[4:])
    if version != 2:
        raise PayloadError(f"Unsupported OTA payload version: {version}.")
    manifest = payload.read(manifest_size)
    if len(manifest) != manifest_size:
        raise PayloadError("OTA payload manifest is truncated.")
    signature = payload.read(signature_size)
    if len(signature) != signature_size:
        raise PayloadError("OTA payload metadata signature is truncated.")
    return manifest, 24 + manifest_size + signature_size


def read_operation_data(payload, data_base, operation):
    data_offset = optional_varint(operation, 2)
    data_length = optional_varint(operation, 3)
    if not data_length:
        return b""
    payload.seek(data_base + data_offset)
    data = payload.read(data_length)
    if len(data) != data_length:
        raise PayloadError("OTA operation data is truncated.")
    return data


def decode_operation(payload, data_base, operation):
    operation_type = required_varint(operation, 1, "operation type")
    data = read_operation_data(payload, data_base, operation)
    if operation_type == OP_REPLACE:
        return data
    if operation_type == OP_REPLACE_BZ:
        return bz2.decompress(data)
    if operation_type == OP_REPLACE_XZ:
        return lzma.decompress(data)
    if operation_type in (OP_ZERO, OP_DISCARD):
        return b""
    if operation_type == OP_REPLACE_ZSTD:
        raise PayloadError(
            "REPLACE_ZSTD is not supported by the standard-library extractor."
        )
    raise PayloadError(f"Unsupported OTA operation type: {operation_type}.")


def write_operation(output, operation_data, extents):
    if not operation_data:
        return
    offset = 0
    for start, length in extents:
        chunk = operation_data[offset : offset + length]
        output.seek(start)
        output.write(chunk)
        offset += len(chunk)
        if len(chunk) < length:
            break
    if offset != len(operation_data):
        raise PayloadError(
            "Decoded OTA operation does not fit its destination extents."
        )


def extract_partition(payload, data_base, partition, output_path, block_size):
    name, size, expected_hash, operations = partition
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output:
        output.truncate(size)
        for operation in operations:
            decoded = decode_operation(payload, data_base, operation)
            write_operation(output, decoded, operation_extents(operation, block_size))

    digest = hashlib.sha256(output_path.read_bytes()).digest()
    if expected_hash is not None and digest != expected_hash:
        raise PayloadError(f"Partition hash mismatch for {name}: {digest.hex()}.")
    return digest.hex()


def parse_expected(values):
    expected = {}
    for value in values:
        name, separator, digest = value.partition("=")
        if not separator or not name or len(digest) != 64:
            raise argparse.ArgumentTypeError(
                "Expected partition hash must use NAME=64_HEX format."
            )
        try:
            int(digest, 16)
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                "Expected partition hash must be hexadecimal."
            ) from error
        expected[name] = digest.lower()
    return expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--partition", action="append")
    parser.add_argument(
        "--expected",
        action="append",
        default=[],
        help="Expected partition SHA256 as NAME=64_HEX.",
    )
    args = parser.parse_args(argv)
    if not args.archive.is_file():
        parser.error(f"OTA archive does not exist: {args.archive}.")
    expected = parse_expected(args.expected)
    partitions_to_extract = args.partition or ["boot", "vendor_boot"]
    requested = set(partitions_to_extract)

    try:
        with zipfile.ZipFile(args.archive) as archive:
            with archive.open("payload.bin") as payload:
                manifest, data_base = payload_header(payload)
                block_size = optional_varint(manifest, 3, BLOCK_SIZE)
                partitions = {
                    name: (name, size, digest, operations)
                    for name, size, digest, operations in partition_records(manifest)
                }
                missing = requested - partitions.keys()
                if missing:
                    raise PayloadError(
                        f"OTA payload is missing partitions: {', '.join(sorted(missing))}."
                    )
                for name in partitions_to_extract:
                    digest = extract_partition(
                        payload,
                        data_base,
                        partitions[name],
                        args.output / f"{name}.img",
                        block_size,
                    )
                    if name in expected and digest != expected[name]:
                        raise PayloadError(f"Extracted {name} hash differs: {digest}.")
                    print(f"Extracted {name}: {digest}.")
    except (
        OSError,
        KeyError,
        ValueError,
        zipfile.BadZipFile,
        lzma.LZMAError,
        EOFError,
    ) as error:
        print(f"OTA image extraction failed: {error}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
