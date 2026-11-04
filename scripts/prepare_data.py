"""Build train/val/test ECG segment datasets from matDBs/ and save them to .npz.

Examples:
    python scripts/prepare_data.py
    python scripts/prepare_data.py --segmentation window --leads i ii v1 v5
    python scripts/prepare_data.py --normalization global --out data/ludb_global.npz
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecg_anomaly import LEAD_NAMES, DataConfig, build_datasets, save_datasets  # noqa: E402


def parse_args() -> argparse.Namespace:
    d = DataConfig()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=d.data_dir)
    p.add_argument("--out", default="data/ludb_segments.npz")
    p.add_argument("--leads", nargs="+", default=list(d.leads), choices=LEAD_NAMES)
    p.add_argument("--segmentation", choices=["beat", "window"], default=d.segmentation)
    p.add_argument("--beat-pre", type=int, default=d.beat_pre)
    p.add_argument("--beat-post", type=int, default=d.beat_post)
    p.add_argument("--window-size", type=int, default=d.window_size)
    p.add_argument("--window-stride", type=int, default=d.window_stride)
    p.add_argument("--normalization", choices=["segment", "global", "none"], default=d.normalization)
    p.add_argument("--no-notch", action="store_true", help="disable the 50 Hz notch filter")
    p.add_argument("--val-fraction", type=float, default=d.val_fraction)
    p.add_argument("--test-fraction", type=float, default=d.test_fraction)
    p.add_argument("--seed", type=int, default=d.seed)
    p.add_argument("--exclude", type=int, nargs="*", default=[], help="record numbers to skip")
    return p.parse_args()


def main() -> None:
    a = parse_args()
    cfg = DataConfig(
        data_dir=a.data_dir,
        leads=tuple(a.leads),
        segmentation=a.segmentation,
        beat_pre=a.beat_pre,
        beat_post=a.beat_post,
        window_size=a.window_size,
        window_stride=a.window_stride,
        normalization=a.normalization,
        notch_freq=None if a.no_notch else DataConfig.notch_freq,
        val_fraction=a.val_fraction,
        test_fraction=a.test_fraction,
        seed=a.seed,
        exclude_records=tuple(a.exclude),
    )
    sets, meta = build_datasets(cfg)
    for name, s in sets.items():
        print(f"{name:>5}: {len(meta['records'][name]):3d} records -> {len(s):6d} segments, shape {s.x.shape}")
    path = save_datasets(sets, meta, a.out)
    print(f"Saved to {path} (metadata: {path.with_suffix('.json')})")


if __name__ == "__main__":
    main()
