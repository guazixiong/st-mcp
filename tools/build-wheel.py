#!/usr/bin/env python3
"""Rebuild the st-mcp wheel from src/ without network or build backends.

The package is pure Python, so the existing wheel is used as the template for
``*.dist-info`` (name, version, entry points) and every ``st_mcp/`` file is
replaced with the working tree.  ``RECORD`` is regenerated, so ``pip`` and
``docker build`` accept the result exactly like a wheel from a build backend.

    python tools/build-wheel.py --template dist/st_mcp-0.1.0-py3-none-any.whl \
        --out dist/st_mcp-0.1.0-py3-none-any.whl
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "src", "st_mcp")


def digest(data: bytes) -> str:
    value = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + value.decode("ascii")


def package_files():
    for base, dirs, names in os.walk(PACKAGE):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            yield os.path.relpath(path, os.path.dirname(PACKAGE)).replace(os.sep, "/"), path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True, help="existing wheel providing *.dist-info")
    parser.add_argument("--out", required=True, help="wheel to write")
    args = parser.parse_args()

    with zipfile.ZipFile(args.template) as template:
        dist_info = [name for name in template.namelist() if ".dist-info/" in name]
        record_name = next(name for name in dist_info if name.endswith("RECORD"))
        preserved = {name: template.read(name) for name in dist_info if not name.endswith("RECORD")}

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    record = []
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as wheel:
        for name, data in preserved.items():
            wheel.writestr(name, data)
            record.append((name, digest(data), len(data)))
        for name, path in package_files():
            with open(path, "rb") as handle:
                data = handle.read()
            wheel.writestr(name, data)
            record.append((name, digest(data), len(data)))
        record_name = next(name for name in dist_info if name.endswith("RECORD"))
        lines = [f"{name},{hash},{size}" for name, hash, size in record]
        lines.append(f"{record_name},,")
        wheel.writestr(record_name, "\n".join(lines) + "\n")

    print(f"wrote {args.out} ({os.path.getsize(args.out)} bytes, {len(record)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
