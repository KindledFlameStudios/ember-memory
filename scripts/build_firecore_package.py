#!/usr/bin/env python3
"""Build a dependency-free, pure-Python Ember FireCore wheel."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
from pathlib import Path
import tempfile
import zipfile


VERSION = "1.1.0"


def _record(data: bytes) -> tuple[str, int]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
    return f"sha256={digest}", len(data)


def build(source: Path, output: Path) -> Path:
    source = source.resolve()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "ember_memory/__init__.py": (source / "ember_memory" / "__init__.py").read_bytes(),
        "ember_memory/core/__init__.py": (source / "ember_memory" / "core" / "__init__.py").read_bytes(),
        "ember_memory/firecore.py": (source / "ember_memory" / "firecore.py").read_bytes(),
        "ember_memory/core/bm25.py": (source / "ember_memory" / "core" / "bm25.py").read_bytes(),
    }
    dist_info = f"ember_firecore_headless-{VERSION}.dist-info"
    metadata = (
        "Metadata-Version: 2.1\n"
        "Name: ember-firecore-headless\n"
        f"Version: {VERSION}\n"
        "Summary: Ember-owned local FireCore lexical service\n"
        "Requires-Python: >=3.10\n"
    ).encode()
    wheel = b"Wheel-Version: 1.0\nGenerator: ember-firecore-package-builder\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    entry_points = b"[console_scripts]\nember-firecore = ember_memory.firecore:main\n"
    files[f"{dist_info}/METADATA"] = metadata
    files[f"{dist_info}/WHEEL"] = wheel
    files[f"{dist_info}/entry_points.txt"] = entry_points
    record_buffer = io.StringIO(newline="")
    writer = csv.writer(record_buffer, lineterminator="\n")
    records = {name: _record(data) for name, data in files.items()}
    for name, (digest, size) in sorted(records.items()):
        writer.writerow((name, digest, size))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    files[f"{dist_info}/RECORD"] = record_buffer.getvalue().encode()
    artifact = output / f"ember_firecore_headless-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
