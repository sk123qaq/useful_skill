#!/usr/bin/env python3
from __future__ import annotations

import argparse
import bz2
import csv
import gzip
import io
import json
import lzma
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

# Add the scripts directory to sys.path so we can import common
sys.path.append(str(Path(__file__).parent))
import common

SMALL_FILE_BYTES = 150 * 1024 * 1024
LARGE_FILE_BYTES = 1500 * 1024 * 1024
AUTOSAMPLE_THRESHOLD_BYTES = 500 * 1024 * 1024
DEFAULT_SAMPLE_ROWS = 100_000

SUPPORTED_FORMATS = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".xlsb", ".parquet", ".feather", ".json", ".jsonl"}
COMPRESSION_SUFFIXES = {".gz", ".gzip", ".bz2", ".xz"}
ARCHIVE_SUFFIXES = {".zip"}
NEGATIVE_NAME_TOKENS = {"readme", "schema", "dictionary", "metadata", "notes", "license"}
POSITIVE_NAME_TOKENS = {"data", "export", "fact", "table", "dataset", "records"}

def _backend_for_suffix(suffix: str, size_bytes: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if suffix in {".csv", ".tsv"}:
        if size_bytes <= SMALL_FILE_BYTES: return "pandas", warnings
        return "polars_or_duckdb", warnings
    if suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        warnings.append("Excel is fragile for large datasets.")
        return "pandas_excel", warnings
    if suffix in {".parquet", ".feather"}:
        return "pandas_or_polars", warnings
    return "unknown", warnings

def _suffix_profile(path_like: str | Path) -> dict[str, Any]:
    suffixes = [suffix.lower() for suffix in Path(path_like).suffixes]
    compression_suffix = suffixes[-1] if suffixes and suffixes[-1] in COMPRESSION_SUFFIXES else None
    archive_suffix = suffixes[-1] if suffixes and suffixes[-1] in ARCHIVE_SUFFIXES else None
    if archive_suffix or compression_suffix:
        logical_suffix = suffixes[-2] if len(suffixes) >= 2 else ""
    else:
        logical_suffix = suffixes[-1] if suffixes else ""
    return {
        "suffixes": suffixes,
        "archive_suffix": archive_suffix,
        "compression_suffix": compression_suffix,
        "logical_suffix": logical_suffix,
        "supported": logical_suffix in SUPPORTED_FORMATS,
    }

def resolve_input_source(input_path: str) -> dict[str, Any]:
    path = Path(input_path).expanduser().resolve()
    if not path.exists():
        return {"path": str(path), "exists": False, "supported": False, "warnings": ["Input path does not exist."]}

    if path.is_dir():
        candidates: list[dict[str, Any]] = []
        for child in path.rglob("*"):
            if child.is_file():
                profile = _suffix_profile(child.name)
                if profile["archive_suffix"] or profile["supported"]:
                    candidates.append({"name": str(child.relative_to(path)), "path": child, "size_bytes": child.stat().st_size})
        if not candidates:
            return {"path": str(path), "exists": True, "supported": False, "warnings": ["No supported files found in directory."]}
        # Pick the largest/most likely data file
        candidates.sort(key=lambda x: x["size_bytes"], reverse=True)
        selected = candidates[0]
        resolved = resolve_input_source(str(selected["path"]))
        resolved["warnings"] = resolved.get("warnings", []) + [f"Directory input auto-selected `{selected['name']}`."]
        return resolved

    profile = _suffix_profile(path.name)
    size_bytes = path.stat().st_size

    if profile["archive_suffix"] == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [m for m in archive.infolist() if not m.is_dir() and _suffix_profile(m.filename)["supported"]]
            if not members:
                return {"path": str(path), "exists": True, "supported": False, "warnings": ["No supported files in ZIP."]}
            members.sort(key=lambda x: x.file_size, reverse=True)
            selected = members[0]
            return {
                "path": str(path), "exists": True, "supported": True, "kind": "archive_member",
                "format": _suffix_profile(selected.filename)["logical_suffix"],
                "member_name": selected.filename, "member_size_bytes": selected.file_size,
                "size_bytes": size_bytes, "size_mb": round(size_bytes / (1024*1024), 2)
            }

    return {
        "path": str(path), "exists": True, "supported": profile["supported"], "kind": "file",
        "format": profile["logical_suffix"] or "unknown", "compression": profile["compression_suffix"],
        "size_bytes": size_bytes, "size_mb": round(size_bytes / (1024*1024), 2)
    }

def build_file_read_plan(input_path: str) -> dict[str, Any]:
    resolved = resolve_input_source(input_path)
    if not resolved.get("supported"): return resolved
    logical_suffix = str(resolved.get("format", "")).lower()
    logical_size = int(resolved.get("member_size_bytes") or resolved.get("size_bytes") or 0)
    backend, warnings = _backend_for_suffix(logical_suffix, logical_size)
    requires = ["pandas"]
    if logical_suffix in {".xlsx", ".xlsm", ".xls"}: requires.append("openpyxl")
    if logical_suffix in {".parquet", ".feather"}: requires.append("pyarrow")
    
    plan = {
        **resolved, "recommended_backend": backend, "requires": sorted(set(requires)),
        "preview_available": logical_suffix in {".csv", ".tsv"}
    }
    
    if logical_size > AUTOSAMPLE_THRESHOLD_BYTES:
        plan["sampling_recommended"] = True
        plan["sampling_strategy"] = "head_chunk"
        plan["suggested_sample_rows"] = DEFAULT_SAMPLE_ROWS
        plan["warnings"] = plan.get("warnings", []) + [
            f"Large file detected ({resolved.get('size_mb')} MB). Automatic sampling ({DEFAULT_SAMPLE_ROWS} rows) is recommended."
        ]
    
    return plan

def load_dataframe(input_path: str, sample_rows: int | None = None, auto_sample: bool = True):
    resolved = resolve_input_source(input_path)
    if not resolved.get("supported"):
        raise ValueError(f"Unsupported format: {resolved.get('format')}")

    import pandas as pd
    logical_suffix = str(resolved.get("format", "")).lower()
    path = Path(str(resolved["path"]))
    logical_size = int(resolved.get("member_size_bytes") or resolved.get("size_bytes") or 0)

    # Automatic sampling strategy for large files
    if sample_rows is None and auto_sample and logical_size > AUTOSAMPLE_THRESHOLD_BYTES:
        sample_rows = DEFAULT_SAMPLE_ROWS
        print(f"Note: Automatically sampling first {sample_rows} rows due to large file size ({resolved.get('size_mb')} MB).", file=sys.stderr)

    if resolved.get("kind") == "archive_member":
        with zipfile.ZipFile(path) as archive:
            with archive.open(str(resolved["member_name"])) as f:
                if logical_suffix in {".csv", ".tsv"}:
                    return pd.read_csv(f, sep="\t" if logical_suffix == ".tsv" else ",", nrows=sample_rows)
                if logical_suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
                    return pd.read_excel(f, nrows=sample_rows)
                if logical_suffix in {".parquet", ".feather"}:
                    return pd.read_parquet(f).head(sample_rows) if sample_rows else pd.read_parquet(f)

    if logical_suffix in {".csv", ".tsv"}:
        return pd.read_csv(path, sep="\t" if logical_suffix == ".tsv" else ",", nrows=sample_rows, compression="infer")
    if logical_suffix in {".xlsx", ".xlsm", ".xls", ".xlsb"}:
        return pd.read_excel(path, nrows=sample_rows)
    if logical_suffix in {".parquet", ".feather"}:
        return pd.read_parquet(path).head(sample_rows) if sample_rows else pd.read_parquet(path)
    if logical_suffix in {".json", ".jsonl"}:
        return pd.read_json(path, lines=(logical_suffix==".jsonl"), nrows=sample_rows if logical_suffix==".jsonl" else None)

    raise ValueError(f"Could not load {logical_suffix}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    args = parser.parse_args()
    print(json.dumps(build_file_read_plan(args.input_path), indent=2, ensure_ascii=False))
