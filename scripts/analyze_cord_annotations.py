"""Fetch only CORD ground-truth columns and write a deterministic JSON profile."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import duckdb

from receipt_intelligence.analysis import profile_cord_annotations


DATASET = "naver-clova-ix/cord-v2"
MANIFEST_URL = f"https://datasets-server.huggingface.co/parquet?dataset={quote(DATASET)}"


def fetch_manifest() -> list[dict[str, Any]]:
    request = Request(MANIFEST_URL, headers={"User-Agent": "receipt-intelligence-data-audit/0.1"})
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)

    files = payload.get("parquet_files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("CORD parquet manifest contains no files")
    return files


def load_ground_truth(parquet_files: list[dict[str, Any]]) -> Iterator[str]:
    connection = duckdb.connect()
    try:
        for parquet_file in parquet_files:
            url = parquet_file.get("url")
            if not isinstance(url, str):
                raise RuntimeError("parquet manifest entry has no URL")
            rows = connection.execute(
                "SELECT ground_truth FROM read_parquet(?)",
                [url],
            ).fetchall()
            for (ground_truth,) in rows:
                yield ground_truth
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/cord_data_profile.json"),
    )
    args = parser.parse_args()

    manifest = fetch_manifest()
    profile = profile_cord_annotations(load_ground_truth(manifest))
    profile["source"] = {
        "dataset": DATASET,
        "parquet_files": len(manifest),
        "advertised_parquet_bytes": sum(int(item.get("size", 0)) for item in manifest),
        "retrieved_columns": ["ground_truth"],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Analyzed {profile['documents']['total']} documents")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()

