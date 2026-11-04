"""Tests for the data pipeline.

They run on a small synthetic PTB-XL-like directory, so no download is needed.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ecg_anomaly import (
    ABNORMAL,
    LEAD_NAMES,
    NORMAL,
    SUPERCLASSES,
    DataConfig,
    build_datasets,
    load_datasets,
    load_metadata,
    load_record,
    save_datasets,
)
from ecg_anomaly.preprocessing import (
    ChannelStandardizer,
    detect_r_peaks,
    segment_beats,
    segment_windows,
    zscore_segments,
)


def synthetic_ecg(fs=100.0, seconds=10.0, hr=72.0, seed=0):
    """Gaussian 'QRS' spikes on a slow baseline, plus the true R-peak positions."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(fs * seconds)) / fs
    peaks = np.arange(0.5, seconds - 0.2, 60.0 / hr)
    x = 0.3 * np.sin(2 * np.pi * 0.3 * t) + 0.01 * rng.standard_normal(t.size)
    for p in peaks:
        x += np.exp(-((t - p) ** 2) / (2 * 0.012**2))
    return x, np.round(peaks * fs).astype(int)


# --------------------------------------------------------------------------- #
# Fake PTB-XL directory
# --------------------------------------------------------------------------- #
def write_wfdb(path: Path, x_mv: np.ndarray, fs: int, gain: float = 1000.0) -> None:
    """Write (samples, 12) mV as WFDB format 16 with leads in PTB-XL order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    digital = np.round(x_mv * gain).astype("<i2")
    digital.tofile(path.with_suffix(".dat"))
    lines = [f"{path.name} 12 {fs} {x_mv.shape[0]}"]
    for i, lead in enumerate(LEAD_NAMES):
        lines.append(f"{path.name}.dat 16 {gain}(0)/mV 16 0 {digital[0, i]} 0 0 {lead.upper()}")
    path.with_suffix(".hea").write_text("\n".join(lines) + "\n")


# (scp_codes, strat_fold, noisy) per record
RECORDS = [
    ("{'NORM': 100.0, 'SR': 0.0}", 1, False),
    ("{'NORM': 100.0, 'SR': 0.0}", 2, False),
    ("{'NORM': 100.0, 'SR': 0.0}", 3, True),     # noisy -> dropped from train
    ("{'IMI': 100.0, 'SR': 0.0}", 4, False),     # abnormal -> dropped from train
    ("{'NORM': 80.0}", 5, False),                # uncertain -> unused
    ("{'NORM': 100.0}", 9, False),
    ("{'ASMI': 50.0, 'NORM': 100.0}", 9, False),  # abnormal (MI)
    ("{'NORM': 100.0}", 10, False),
    ("{'LVH': 100.0, 'NDT': 100.0}", 10, False),  # abnormal (HYP + STTC)
]


@pytest.fixture
def ptbxl_dir(tmp_path):
    root = tmp_path / "ptb-xl"
    rows = []
    for ecg_id, (codes, fold, noisy) in enumerate(RECORDS, start=1):
        base, _ = synthetic_ecg(seed=ecg_id)
        x = np.stack([base * (1 + 0.05 * k) for k in range(12)], axis=1)
        rel = f"records100/00000/{ecg_id:05d}_lr"
        write_wfdb(root / rel, x, 100)
        rows.append({
            "ecg_id": ecg_id, "patient_id": ecg_id, "scp_codes": codes, "strat_fold": fold,
            "baseline_drift": "I" if noisy else np.nan, "static_noise": np.nan,
            "burst_noise": np.nan, "electrodes_problems": np.nan, "pacemaker": np.nan,
            "filename_lr": rel, "filename_hr": rel.replace("100", "500").replace("_lr", "_hr"),
        })
    pd.DataFrame(rows).to_csv(root / "ptbxl_database.csv", index=False)
    pd.DataFrame({
        "code": ["NORM", "IMI", "ASMI", "LVH", "NDT", "SR"],
        "diagnostic": [1, 1, 1, 1, 1, np.nan],
        "diagnostic_class": ["NORM", "MI", "MI", "HYP", "STTC", np.nan],
    }).to_csv(root / "scp_statements.csv", index=False)
    return root


# --------------------------------------------------------------------------- #
# Preprocessing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fs", [100.0, 500.0])
def test_r_peak_detection_on_synthetic_signal(fs):
    x, true = synthetic_ecg(fs=fs)
    found = detect_r_peaks(x, fs)
    assert len(found) == len(true)
    assert np.max(np.abs(found - true)) <= max(1, int(0.006 * fs))


def test_r_peak_detection_ignores_single_artefact():
    x, true = synthetic_ecg()
    x[300:330] += 20.0  # large burst
    found = detect_r_peaks(x, 100.0)
    assert len(found) >= len(true) - 2


def test_segment_shapes():
    x = np.random.randn(1000, 2)
    segs, centers = segment_beats(x, np.array([10, 500, 990]), pre=24, post=40)
    assert segs.shape == (1, 2, 64) and centers.tolist() == [500]
    segs, starts = segment_windows(x, 256, 128)
    assert segs.shape == (6, 2, 256) and starts[-1] == 640


def test_normalisation():
    segs = np.random.randn(10, 3, 100) * 5 + 2
    z = zscore_segments(segs)
    assert np.allclose(z.mean(-1), 0, atol=1e-6) and np.allclose(z.std(-1), 1, atol=1e-6)
    out = ChannelStandardizer().fit_transform(segs)
    assert np.allclose(out.mean(axis=(0, 2)), 0, atol=1e-6)


def test_default_lengths_scale_with_sampling_rate():
    assert DataConfig(sampling_rate=100).segment_length == 64
    assert DataConfig(sampling_rate=500).segment_length == 320
    assert DataConfig(sampling_rate=500, segmentation="window").segment_length == 1280


# --------------------------------------------------------------------------- #
# PTB-XL loading and the full pipeline
# --------------------------------------------------------------------------- #
def test_read_record_roundtrip(ptbxl_dir):
    x = load_record(ptbxl_dir, "records100/00000/00001_lr")
    base, _ = synthetic_ecg(seed=1)
    assert x.shape == (1000, 12)
    assert np.allclose(x[:, 0], base, atol=1e-3)
    assert np.allclose(x[:, 11], base * 1.55, atol=1e-3)


def test_labels(ptbxl_dir):
    db = load_metadata(DataConfig(data_dir=str(ptbxl_dir)))
    assert db["label"].tolist() == [NORMAL, NORMAL, NORMAL, ABNORMAL, -1,
                                    NORMAL, ABNORMAL, NORMAL, ABNORMAL]
    assert db.loc[9, "superclasses"] == {"HYP", "STTC"}
    assert db["noisy"].sum() == 1 and db["file_exists"].all()


@pytest.mark.parametrize("mode", ["beat", "window"])
def test_pipeline(ptbxl_dir, tmp_path, mode):
    cfg = DataConfig(data_dir=str(ptbxl_dir), segmentation=mode, leads=("ii", "v5"))
    sets, meta = build_datasets(cfg)

    assert meta["records"] == {"train": [1, 2], "val": [6, 7], "test": [8, 9]}
    assert set(sets["train"].labels) == {NORMAL}
    assert set(sets["test"].labels) == {NORMAL, ABNORMAL}
    for s in sets.values():
        assert s.x.shape[1:] == (2, cfg.segment_length)
        assert s.x.dtype == np.float32 and np.all(np.isfinite(s.x))
        assert len(s.labels) == len(s.record_ids) == len(s.superclasses) == len(s)
    test = sets["test"]
    rec9 = test.superclasses[test.record_ids == 9]
    assert (rec9 == [0, 0, 1, 0, 1]).all()  # STTC + HYP
    assert len(SUPERCLASSES) == rec9.shape[1]

    path = save_datasets(sets, meta, tmp_path / "d.npz")
    loaded, meta2 = load_datasets(path)
    assert meta2 == meta
    for name in sets:
        assert np.array_equal(loaded[name].x, sets[name].x)
        assert np.array_equal(loaded[name].labels, sets[name].labels)


def test_missing_records_are_skipped(ptbxl_dir):
    (ptbxl_dir / "records100/00000/00002_lr.dat").unlink()
    sets, meta = build_datasets(DataConfig(data_dir=str(ptbxl_dir)))
    assert meta["records"]["train"] == [1] and meta["missing_files"] == 1
