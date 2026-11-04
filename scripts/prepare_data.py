"""Build train/val/test ECG segment datasets from PTB-XL and save them to .npz.

Run ``python scripts/download_ptbxl.py`` first.

Examples:
    python scripts/prepare_data.py                                   # beats, 12 leads, 100 Hz
    python scripts/prepare_data.py --segmentation window --leads ii v1 v5
    python scripts/prepare_data.py --sampling-rate 500 --out data/ptbxl_500.npz
    python scripts/prepare_data.py --max-records 300                 # quick experiment
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ecg_anomaly import LEAD_NAMES, DataConfig, build_datasets, save_datasets  # noqa: E402


def parse_args() -> argparse.Namespace:
    d = DataConfig()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", default=d.data_dir)
    p.add_argument("--out", default="data/ptbxl_segments.npz")
    p.add_argument("--sampling-rate", type=int, choices=[100, 500], default=d.sampling_rate)
    p.add_argument("--leads", nargs="+", default=list(d.leads), choices=LEAD_NAMES)
    p.add_argument("--segmentation", choices=["beat", "window"], default=d.segmentation)
    p.add_argument("--beat-pre", type=int, default=None, help="samples before R (default: 0.24 s)")
    p.add_argument("--beat-post", type=int, default=None, help="samples after R (default: 0.40 s)")
    p.add_argument("--window-size", type=int, default=None, help="samples (default: 2.56 s)")
    p.add_argument("--window-stride", type=int, default=None, help="samples (default: 1.28 s)")
    p.add_argument("--normalization", choices=["segment", "global", "none"], default=d.normalization)
    p.add_argument("--normal-min-likelihood", type=float, default=d.normal_min_likelihood)
    p.add_argument("--keep-noisy-train", action="store_true",
                   help="keep records with noise/electrode/pacemaker annotations in training")
    p.add_argument("--train-all", action="store_true",
                   help="also train on abnormal ECGs (not unsupervised anomaly detection)")
    p.add_argument("--max-records", type=int, default=None, help="cap on records per split")
    p.add_argument("--seed", type=int, default=d.seed)
    return p.parse_args()


def main() -> None:
    a = parse_args()
    cfg = DataConfig(
        data_dir=a.data_dir,
        sampling_rate=a.sampling_rate,
        leads=tuple(a.leads),
        segmentation=a.segmentation,
        beat_pre=a.beat_pre,
        beat_post=a.beat_post,
        window_size=a.window_size,
        window_stride=a.window_stride,
        normalization=a.normalization,
        normal_min_likelihood=a.normal_min_likelihood,
        clean_train=not a.keep_noisy_train,
        train_normal_only=not a.train_all,
        max_records_per_split=a.max_records,
        seed=a.seed,
    )
    sets, meta = build_datasets(cfg, verbose=True)
    if meta["missing_files"]:
        print(f"Note: {meta['missing_files']} records are not downloaded and were skipped")
    for name, s in sets.items():
        n_rec = len(meta["records"][name])
        n_abn = int(np.sum(s.labels == 1))
        print(f"{name:>5}: {n_rec:5d} records -> {len(s):7d} segments "
              f"({len(s) - n_abn} normal, {n_abn} abnormal), shape {s.x.shape}")
    path = save_datasets(sets, meta, a.out)
    print(f"Saved to {path} (metadata: {path.with_suffix('.json')})")


if __name__ == "__main__":
    main()
