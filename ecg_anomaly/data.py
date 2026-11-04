"""Loading LUDB recordings and building train/val/test segment datasets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.io import loadmat

from .config import DataConfig
from .preprocessing import (
    ChannelStandardizer,
    detect_r_peaks,
    filter_ecg,
    segment_beats,
    segment_windows,
    zscore_segments,
)

SPLITS = ("train", "val", "test")


# --------------------------------------------------------------------------- #
# Raw records
# --------------------------------------------------------------------------- #
def list_records(data_dir: str | Path) -> list[int]:
    """Return the record numbers found in ``data_dir`` (``1.mat`` -> 1), sorted numerically."""
    ids = []
    for path in Path(data_dir).glob("*.mat"):
        if re.fullmatch(r"\d+", path.stem):
            ids.append(int(path.stem))
    return sorted(ids)


def load_record(data_dir: str | Path, record_id: int, variable: str = "ecgSignal") -> np.ndarray:
    """Load one recording as a float array of shape (samples, leads)."""
    path = Path(data_dir) / f"{record_id}.mat"
    mat = loadmat(path)
    if variable not in mat:
        raise KeyError(f"{path} does not contain variable '{variable}'")
    x = np.asarray(mat[variable], dtype=np.float64)
    if x.ndim != 2:
        raise ValueError(f"{path}: expected a 2-D array, got shape {x.shape}")
    # Make sure time runs along axis 0 (LUDB: 5000 x 12).
    if x.shape[0] < x.shape[1]:
        x = x.T
    if not np.all(np.isfinite(x)):
        raise ValueError(f"{path} contains NaN or Inf values")
    return x


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #
def split_records(
    record_ids: list[int], val_fraction: float, test_fraction: float, seed: int
) -> dict[str, list[int]]:
    """Shuffle records and split them into disjoint train/val/test lists."""
    if val_fraction < 0 or test_fraction < 0 or val_fraction + test_fraction >= 1:
        raise ValueError("val_fraction and test_fraction must be >= 0 and sum to < 1")
    rng = np.random.default_rng(seed)
    ids = np.array(sorted(record_ids))
    rng.shuffle(ids)
    n = len(ids)
    n_test = int(round(n * test_fraction))
    n_val = int(round(n * val_fraction))
    return {
        "test": sorted(ids[:n_test].tolist()),
        "val": sorted(ids[n_test : n_test + n_val].tolist()),
        "train": sorted(ids[n_test + n_val :].tolist()),
    }


# --------------------------------------------------------------------------- #
# Record -> segments
# --------------------------------------------------------------------------- #
def record_to_segments(x: np.ndarray, cfg: DataConfig) -> tuple[np.ndarray, np.ndarray]:
    """Filter one recording and cut it into segments.

    Returns ``(segments, positions)``: segments of shape (n, channels, length)
    and the R-peak sample (beat mode) or window start (window mode) of each.
    """
    filtered = filter_ecg(x, cfg)
    channels = filtered[:, cfg.lead_indices]

    if cfg.segmentation == "beat":
        # R peaks are detected on lead II when available (usually the clearest
        # QRS), otherwise on the first selected lead.
        ref = filtered[:, 1] if filtered.shape[1] > 1 else channels[:, 0]
        r_peaks = detect_r_peaks(ref, cfg.fs)
        return segment_beats(channels, r_peaks, cfg.beat_pre, cfg.beat_post)
    if cfg.segmentation == "window":
        return segment_windows(channels, cfg.window_size, cfg.window_stride)
    raise ValueError(f"Unknown segmentation mode: {cfg.segmentation!r}")


@dataclass
class SegmentSet:
    """Segments of one split plus bookkeeping to trace them back to the source."""

    x: np.ndarray           # (n, channels, length), float32
    record_ids: np.ndarray  # (n,) record number of every segment
    positions: np.ndarray   # (n,) R-peak / window-start sample in the recording

    def __len__(self) -> int:
        return len(self.x)


def build_split(record_ids: list[int], cfg: DataConfig) -> SegmentSet:
    segs, recs, pos = [], [], []
    for rid in record_ids:
        x = load_record(cfg.data_dir, rid, cfg.variable)
        s, p = record_to_segments(x, cfg)
        if len(s) == 0:
            continue
        segs.append(s)
        recs.append(np.full(len(s), rid, dtype=np.int32))
        pos.append(p.astype(np.int32))
    n_ch, length = len(cfg.leads), cfg.segment_length
    if not segs:
        return SegmentSet(
            np.empty((0, n_ch, length), np.float32), np.empty(0, np.int32), np.empty(0, np.int32)
        )
    return SegmentSet(
        np.concatenate(segs).astype(np.float32), np.concatenate(recs), np.concatenate(pos)
    )


def build_datasets(cfg: DataConfig) -> tuple[dict[str, SegmentSet], dict]:
    """Run the full pipeline: list -> split -> filter -> segment -> normalise.

    Returns the segment sets per split and a metadata dict (config, record
    split, normalisation statistics) needed to reproduce preprocessing later.
    """
    ids = [r for r in list_records(cfg.data_dir) if r not in set(cfg.exclude_records)]
    if not ids:
        raise FileNotFoundError(f"No numbered .mat files found in {cfg.data_dir!r}")
    split_ids = split_records(ids, cfg.val_fraction, cfg.test_fraction, cfg.seed)
    sets = {name: build_split(split_ids[name], cfg) for name in SPLITS}

    # JSON round-trip so that the in-memory metadata equals what is saved
    # (tuples become lists).
    meta: dict = json.loads(json.dumps({"config": cfg.to_dict(), "records": split_ids}))
    if cfg.normalization == "segment":
        for s in sets.values():
            s.x = zscore_segments(s.x).astype(np.float32)
    elif cfg.normalization == "global":
        scaler = ChannelStandardizer().fit(sets["train"].x)
        for s in sets.values():
            s.x = scaler.transform(s.x).astype(np.float32)
        meta["channel_mean"] = scaler.mean_.ravel().tolist()
        meta["channel_std"] = scaler.std_.ravel().tolist()
    elif cfg.normalization != "none":
        raise ValueError(f"Unknown normalization: {cfg.normalization!r}")
    return sets, meta


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def save_datasets(sets: dict[str, SegmentSet], meta: dict, out_path: str | Path) -> Path:
    """Save all splits into one compressed ``.npz`` file (+ a ``.json`` with metadata)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {}
    for name, s in sets.items():
        arrays[f"{name}_x"] = s.x
        arrays[f"{name}_record_ids"] = s.record_ids
        arrays[f"{name}_positions"] = s.positions
    np.savez_compressed(out_path, meta=json.dumps(meta), **arrays)
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return out_path


def load_datasets(path: str | Path) -> tuple[dict[str, SegmentSet], dict]:
    with np.load(path, allow_pickle=False) as f:
        meta = json.loads(str(f["meta"]))
        sets = {
            name: SegmentSet(f[f"{name}_x"], f[f"{name}_record_ids"], f[f"{name}_positions"])
            for name in SPLITS
        }
    return sets, meta
