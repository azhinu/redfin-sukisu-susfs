#!/usr/bin/env python3
"""Replace only the kernel of a boot header v3 image, preserving its ramdisk."""

import argparse
import hashlib
import json
import pathlib
import struct

PAGE = 4096


def aligned(size):
    return (size + PAGE - 1) // PAGE * PAGE


def sections(image):
    if len(image) < PAGE or image[:8] != b"ANDROID!":
        raise ValueError("Input is not an Android boot image.")
    kernel_size, ramdisk_size = struct.unpack_from("<II", image, 8)
    header_size = struct.unpack_from("<I", image, 20)[0]
    version = struct.unpack_from("<I", image, 40)[0]
    if version != 3 or header_size != 1580:
        raise ValueError(
            f"Expected boot header v3 (1580 bytes), got {version}/{header_size}."
        )
    ramdisk_offset = PAGE + aligned(kernel_size)
    end = ramdisk_offset + aligned(ramdisk_size)
    if not kernel_size or not ramdisk_size or end > len(image):
        raise ValueError("Input has invalid or truncated kernel/ramdisk sections.")
    return (
        image[:PAGE],
        image[PAGE : PAGE + kernel_size],
        image[ramdisk_offset : ramdisk_offset + ramdisk_size],
        end,
    )


def repack(template, kernel):
    header, _, ramdisk, _ = sections(template)
    if not kernel or len(kernel) > 64 * 1024 * 1024:
        raise ValueError("Kernel is empty or exceeds the supported test image size.")
    header = bytearray(header)
    struct.pack_into("<I", header, 8, len(kernel))
    image = bytes(header) + kernel + bytes(aligned(len(kernel)) - len(kernel))
    image += ramdisk + bytes(aligned(len(ramdisk)) - len(ramdisk))
    check_header, check_kernel, check_ramdisk, _ = sections(image)
    assert check_kernel == kernel and check_ramdisk == ramdisk
    assert check_header[:8] == template[:8] and check_header[12:] == template[12:PAGE]
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=pathlib.Path, required=True)
    parser.add_argument(
        "--kernel",
        type=pathlib.Path,
        help="Omit for an unchanged-kernel packaging control.",
    )
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    inputs = [args.template.resolve()] + (
        [args.kernel.resolve()] if args.kernel else []
    )
    if args.output.resolve() in inputs or args.output.exists():
        parser.error("Output must be a new file distinct from the inputs.")
    template = args.template.read_bytes()
    _, original_kernel, ramdisk, original_end = sections(template)
    kernel = args.kernel.read_bytes() if args.kernel else original_kernel
    image = repack(template, kernel)
    if not args.kernel and image != template[:original_end]:
        raise ValueError("Control repack differs from the original boot payload.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    report = {
        "template": str(args.template),
        "template_sha256": hashlib.sha256(template).hexdigest(),
        "kernel_sha256": hashlib.sha256(kernel).hexdigest(),
        "ramdisk_sha256": hashlib.sha256(ramdisk).hexdigest(),
        "boot_sha256": hashlib.sha256(image).hexdigest(),
        "boot_bytes": len(image),
        "header_version": 3,
        "avb_footer": "Omitted; unsigned image for an unlocked bootloader",
        "control": args.kernel is None,
    }
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(f'Packaged {args.output}: {report["boot_sha256"]}.')


if __name__ == "__main__":
    main()
