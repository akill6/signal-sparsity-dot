"""Download PTB-XL (v1.0.3) from the PhysioNet open-data mirror on AWS S3.

PTB-XL: 21,799 clinical 12-lead ECGs (10 s each) from 18,869 patients,
annotated by cardiologists. License: CC BY 4.0.
https://physionet.org/content/ptb-xl/1.0.3/

Examples:
    python scripts/download_ptbxl.py                      # 100 Hz records (~0.5 GB)
    python scripts/download_ptbxl.py --sampling-rate 500  # 500 Hz records (~2.6 GB)
    python scripts/download_ptbxl.py --limit 500          # small subset for a quick test

Files that already exist are skipped, so an interrupted download can be resumed.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MIRRORS = (
    "https://physionet-open.s3.amazonaws.com/ptb-xl/1.0.3",
    "https://physionet.org/files/ptb-xl/1.0.3",
)
METADATA_FILES = ("ptbxl_database.csv", "scp_statements.csv", "LICENSE.txt")


def fetch(url: str, dest: Path, retries: int = 4, timeout: float = 60.0) -> int:
    """Download url to dest atomically. Returns the number of bytes written."""
    if dest.exists() and dest.stat().st_size > 0:
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                data = r.read()
            tmp.write_bytes(data)
            tmp.replace(dest)
            return len(data)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    return 0


def pick_mirror() -> str:
    for base in MIRRORS:
        try:
            with urllib.request.urlopen(f"{base}/RECORDS", timeout=20) as r:
                r.read(16)
            return base
        except Exception as e:  # noqa: BLE001
            print(f"Mirror {base} unavailable: {e}", file=sys.stderr)
    raise SystemExit("No PTB-XL mirror is reachable")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default="data/ptb-xl")
    p.add_argument("--sampling-rate", type=int, choices=[100, 500], default=100)
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--limit", type=int, default=None, help="download only the first N records")
    a = p.parse_args()

    out = Path(a.out)
    base = pick_mirror()
    print(f"Mirror: {base}")
    for name in METADATA_FILES:
        fetch(f"{base}/{name}", out / name)

    column = "filename_lr" if a.sampling_rate == 100 else "filename_hr"
    with open(out / "ptbxl_database.csv", newline="") as f:
        records = [row[column] for row in csv.DictReader(f)]
    if a.limit:
        records = records[: a.limit]

    jobs = [rec + ext for rec in records for ext in (".hea", ".dat")]
    total, done, failed = 0, 0, []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = {pool.submit(fetch, f"{base}/{j}", out / j): j for j in jobs}
        for fut in as_completed(futures):
            try:
                total += fut.result()
            except Exception as e:  # noqa: BLE001
                failed.append((futures[fut], e))
            done += 1
            if done % 2000 == 0 or done == len(jobs):
                print(f"{done}/{len(jobs)} files, {total / 1e6:.0f} MB downloaded", flush=True)

    if failed:
        for name, e in failed[:10]:
            print(f"FAILED {name}: {e}", file=sys.stderr)
        raise SystemExit(f"{len(failed)} files failed; run the script again to retry them")
    print(f"PTB-XL ({a.sampling_rate} Hz, {len(records)} records) is in {out}")


if __name__ == "__main__":
    main()
