"""Loading PTB-XL and building train/val/test segment datasets.

PTB-XL layout (as downloaded by ``scripts/download_ptbxl.py``)::

    data/ptb-xl/
        ptbxl_database.csv      one row per ECG: labels (scp_codes), strat_fold, ...
        scp_statements.csv      SCP code -> diagnostic superclass
        records100/00000/00001_lr.hea + .dat     (100 Hz)
        records500/00000/00001_hr.hea + .dat     (500 Hz)
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import LEAD_NAMES, QUALITY_COLUMNS, SUPERCLASSES, DataConfig
from .preprocessing import (
    ChannelStandardizer,
    detect_r_peaks,
    filter_ecg,
    segment_beats,
    segment_windows,
    zscore_segments,
)

SPLITS = ("train", "val", "test")
NORMAL, ABNORMAL = 0, 1


# --------------------------------------------------------------------------- #
# WFDB reader (format 16, as used by PTB-XL) - no extra dependency needed
# --------------------------------------------------------------------------- #
_GAIN_RE = re.compile(r"^([-+0-9.eE]+)(?:\(([-+0-9]+)\))?")


def read_wfdb(record_path: str | Path) -> tuple[np.ndarray, list[str], float]:
    """Read a WFDB record (``record_path`` without extension).

    Returns ``(signal, lead_names, fs)`` with signal in physical units (mV) of
    shape (samples, leads) and lead names in lower case.
    """
    record_path = Path(record_path)
    lines = [
        ln for ln in record_path.with_suffix(".hea").read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    head = lines[0].split()
    n_sig, fs, n_samp = int(head[1]), float(head[2].split("/")[0]), int(head[3])

    gains, baselines, names, dat_file = [], [], [], None
    for ln in lines[1 : 1 + n_sig]:
        parts = ln.split()
        dat_file = parts[0]
        if parts[1] != "16":
            raise ValueError(f"{record_path}: only WFDB format 16 is supported, got {parts[1]}")
        m = _GAIN_RE.match(parts[2])
        gain = float(m.group(1)) if m else 200.0
        adc_zero = int(parts[4]) if len(parts) > 4 else 0
        baseline = int(m.group(2)) if m and m.group(2) is not None else adc_zero
        gains.append(gain if gain != 0 else 200.0)
        baselines.append(baseline)
        names.append(parts[-1].lower())

    raw = np.fromfile(record_path.parent / dat_file, dtype="<i2")
    if raw.size != n_sig * n_samp:
        raise ValueError(f"{record_path}: expected {n_sig * n_samp} samples, found {raw.size}")
    raw = raw.reshape(n_samp, n_sig).astype(np.float64)
    x = (raw - np.asarray(baselines)) / np.asarray(gains)
    return x, names, fs


def load_record(data_dir: str | Path, filename: str) -> np.ndarray:
    """Load one PTB-XL ECG as (samples, 12) in mV, leads in LEAD_NAMES order."""
    x, names, _ = read_wfdb(Path(data_dir) / filename)
    try:
        order = [names.index(lead) for lead in LEAD_NAMES]
    except ValueError as e:
        raise ValueError(f"{filename}: unexpected leads {names}") from e
    x = x[:, order]
    if not np.all(np.isfinite(x)):
        raise ValueError(f"{filename} contains NaN or Inf values")
    return x


# --------------------------------------------------------------------------- #
# Metadata and labels
# --------------------------------------------------------------------------- #
def load_metadata(cfg: DataConfig) -> pd.DataFrame:
    """Read ``ptbxl_database.csv`` and derive the labels used here.

    Added columns:
      ``filename``      record path for the configured sampling rate
      ``superclasses``  set of diagnostic superclasses (any likelihood)
      ``label``         0 = normal, 1 = abnormal, -1 = unused (ambiguous)
      ``noisy``         any noise / electrode / pacemaker annotation
      ``file_exists``   the record's files are present on disk
    """
    root = Path(cfg.data_dir)
    db_path, scp_path = root / "ptbxl_database.csv", root / "scp_statements.csv"
    if not db_path.exists() or not scp_path.exists():
        raise FileNotFoundError(
            f"PTB-XL metadata not found in {root}. Run: python scripts/download_ptbxl.py --out {root}"
        )
    db = pd.read_csv(db_path, index_col="ecg_id")
    scp = pd.read_csv(scp_path, index_col=0)
    diag_class = scp.loc[scp["diagnostic"] == 1, "diagnostic_class"].to_dict()

    codes = db["scp_codes"].apply(ast.literal_eval)
    db["superclasses"] = codes.apply(lambda c: {diag_class[k] for k in c if k in diag_class})

    def label(row_codes: dict, sup: set) -> int:
        if sup - {"NORM"}:
            return ABNORMAL
        if sup == {"NORM"} and row_codes.get("NORM", 0.0) >= cfg.normal_min_likelihood:
            return NORMAL
        return -1

    db["label"] = [label(c, s) for c, s in zip(codes, db["superclasses"])]
    quality = [c for c in QUALITY_COLUMNS if c in db.columns]
    db["noisy"] = db[quality].notna().any(axis=1) if quality else False
    db["filename"] = db["filename_lr" if cfg.sampling_rate == 100 else "filename_hr"]
    db["file_exists"] = [
        (root / f).with_suffix(".hea").exists() and (root / f).with_suffix(".dat").exists()
        for f in db["filename"]
    ]
    return db


def superclass_matrix(sets: pd.Series) -> np.ndarray:
    """Multi-hot (n, len(SUPERCLASSES)) matrix from a Series of superclass sets."""
    out = np.zeros((len(sets), len(SUPERCLASSES)), dtype=np.uint8)
    for i, s in enumerate(sets):
        for c in s:
            if c in SUPERCLASSES:
                out[i, SUPERCLASSES.index(c)] = 1
    return out


def select_split_records(db: pd.DataFrame, cfg: DataConfig) -> dict[str, pd.DataFrame]:
    """Choose the records of every split from the metadata table."""
    usable = db[(db["label"] >= 0) & db["file_exists"]]
    folds = {"train": cfg.train_folds, "val": cfg.val_folds, "test": cfg.test_folds}
    out = {}
    for name in SPLITS:
        part = usable[usable["strat_fold"].isin(folds[name])]
        if name == "train":
            if cfg.train_normal_only:
                part = part[part["label"] == NORMAL]
            if cfg.clean_train:
                part = part[~part["noisy"]]
        if cfg.max_records_per_split is not None and len(part) > cfg.max_records_per_split:
            part = part.sample(n=cfg.max_records_per_split, random_state=cfg.seed)
        out[name] = part.sort_index()
    return out


# --------------------------------------------------------------------------- #
# Record -> segments
# --------------------------------------------------------------------------- #
def record_to_segments(x: np.ndarray, cfg: DataConfig) -> tuple[np.ndarray, np.ndarray]:
    """Filter one 12-lead recording and cut it into segments.

    Returns ``(segments, positions)``: segments of shape (n, channels, length)
    and the R-peak sample (beat mode) or window start (window mode) of each.
    """
    filtered = filter_ecg(x, cfg)
    channels = filtered[:, cfg.lead_indices]

    if cfg.segmentation == "beat":
        # R peaks are always detected on lead II (usually the clearest QRS),
        # so that all leads of a beat share the same time reference.
        r_peaks = detect_r_peaks(filtered[:, LEAD_NAMES.index("ii")], cfg.fs)
        return segment_beats(channels, r_peaks, cfg.beat_pre, cfg.beat_post)
    if cfg.segmentation == "window":
        return segment_windows(channels, cfg.window_size, cfg.window_stride)
    raise ValueError(f"Unknown segmentation mode: {cfg.segmentation!r}")


@dataclass
class SegmentSet:
    """Segments of one split plus bookkeeping to trace them back to the source.

    ``labels`` and ``superclasses`` are record-level labels copied to every
    segment of the record. They are never used for training the autoencoder,
    only for evaluating the anomaly scores.
    """

    x: np.ndarray             # (n, channels, length), float32
    record_ids: np.ndarray    # (n,) PTB-XL ecg_id of every segment
    positions: np.ndarray     # (n,) R-peak / window-start sample in the recording
    labels: np.ndarray        # (n,) 0 = normal, 1 = abnormal
    superclasses: np.ndarray  # (n, 5) multi-hot over SUPERCLASSES

    def __len__(self) -> int:
        return len(self.x)


def build_split(records: pd.DataFrame, cfg: DataConfig, name: str = "", verbose: bool = False) -> SegmentSet:
    sup = superclass_matrix(records["superclasses"])
    segs, recs, pos, labs, sups = [], [], [], [], []
    for i, (ecg_id, row) in enumerate(records.iterrows()):
        x = load_record(cfg.data_dir, row["filename"])
        s, p = record_to_segments(x, cfg)
        if len(s):
            segs.append(s.astype(np.float32))
            recs.append(np.full(len(s), ecg_id, dtype=np.int32))
            pos.append(p.astype(np.int32))
            labs.append(np.full(len(s), row["label"], dtype=np.int8))
            sups.append(np.repeat(sup[i : i + 1], len(s), axis=0))
        if verbose and (i + 1) % 2000 == 0:
            print(f"  {name}: {i + 1}/{len(records)} records", flush=True)

    if not segs:
        n_ch, length = len(cfg.leads), cfg.segment_length
        return SegmentSet(
            np.empty((0, n_ch, length), np.float32), np.empty(0, np.int32), np.empty(0, np.int32),
            np.empty(0, np.int8), np.empty((0, len(SUPERCLASSES)), np.uint8),
        )
    return SegmentSet(
        np.concatenate(segs), np.concatenate(recs), np.concatenate(pos),
        np.concatenate(labs), np.concatenate(sups),
    )


def build_datasets(cfg: DataConfig, verbose: bool = False) -> tuple[dict[str, SegmentSet], dict]:
    """Run the full pipeline: metadata -> split -> filter -> segment -> normalise.

    Returns the segment sets per split and a metadata dict (config, record
    ids per split, normalisation statistics) needed to reproduce it later.
    """
    db = load_metadata(cfg)
    if not db["file_exists"].any():
        raise FileNotFoundError(
            f"No {cfg.sampling_rate} Hz PTB-XL records found in {cfg.data_dir}. "
            f"Run: python scripts/download_ptbxl.py --sampling-rate {cfg.sampling_rate}"
        )
    split_records = select_split_records(db, cfg)
    sets = {
        name: build_split(split_records[name], cfg, name, verbose) for name in SPLITS
    }

    meta: dict = json.loads(json.dumps({
        "dataset": "PTB-XL 1.0.3",
        "config": cfg.to_dict(),
        "superclasses": list(SUPERCLASSES),
        "records": {name: split_records[name].index.tolist() for name in SPLITS},
        "missing_files": int((~db["file_exists"]).sum()),
    }))
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
_FIELDS = ("x", "record_ids", "positions", "labels", "superclasses")


def save_datasets(sets: dict[str, SegmentSet], meta: dict, out_path: str | Path) -> Path:
    """Save all splits into one ``.npz`` file (+ a ``.json`` with metadata)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"{name}_{field}": getattr(s, field) for name, s in sets.items() for field in _FIELDS}
    np.savez(out_path, meta=json.dumps(meta), **arrays)
    out_path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return out_path


def load_datasets(path: str | Path) -> tuple[dict[str, SegmentSet], dict]:
    with np.load(path, allow_pickle=False) as f:
        meta = json.loads(str(f["meta"]))
        sets = {name: SegmentSet(*(f[f"{name}_{field}"] for field in _FIELDS)) for name in SPLITS}
    return sets, meta
