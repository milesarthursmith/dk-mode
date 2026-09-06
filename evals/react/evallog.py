"""Read an inspect .eval log (zip, zstd-compressed) without inspect_ai.

Returns the sample's full message list, tool calls included.
"""
import json
import struct
import zipfile

import zstandard


def read_member(path, name):
    z = zipfile.ZipFile(path)
    info = z.getinfo(name)
    if info.compress_type != 93:            # 93 = zstd
        return z.read(name)
    with open(path, "rb") as f:
        f.seek(info.header_offset)
        hdr = f.read(30)
        n, m = struct.unpack("<HH", hdr[26:30])
        f.seek(info.header_offset + 30 + n + m)
        raw = f.read(info.compress_size)
    return zstandard.ZstdDecompressor().decompress(raw, max_output_size=info.file_size)


def samples(path):
    z = zipfile.ZipFile(path)
    for name in z.namelist():
        if name.startswith("samples/") and name.endswith(".json"):
            yield name, json.loads(read_member(path, name))
