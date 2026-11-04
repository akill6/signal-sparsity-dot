from pathlib import Path

import numpy as np
import pytest

from ecg_anomaly import DataConfig, build_datasets, list_records, load_datasets, save_datasets, split_records
from ecg_anomaly.preprocessing import (
    ChannelStandardizer,
    detect_r_peaks,
    segment_beats,
    segment_windows,
    zscore_segments,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "matDBs"


def synthetic_ecg(fs=500.0, seconds=10.0, hr=72.0):
    """Gaussian 'QRS' spikes on a slow baseline, plus the true R-peak positions."""
    t = np.arange(int(fs * seconds)) / fs
    rr = 60.0 / hr
    peaks = np.arange(0.5, seconds - 0.2, rr)
    x = 0.3 * np.sin(2 * np.pi * 0.3 * t)
    for p in peaks:
        x += np.exp(-((t - p) ** 2) / (2 * 0.01**2))
    return x, np.round(peaks * fs).astype(int)


def test_r_peak_detection_on_synthetic_signal():
    x, true = synthetic_ecg()
    found = detect_r_peaks(x, 500.0)
    assert len(found) == len(true)
    assert np.max(np.abs(found - true)) <= 3


def test_segment_shapes():
    x = np.random.randn(5000, 2)
    segs, centers = segment_beats(x, np.array([50, 1000, 4900]), pre=128, post=192)
    assert segs.shape == (1, 2, 320) and centers.tolist() == [1000]
    segs, starts = segment_windows(x, 1024, 512)
    assert segs.shape == (8, 2, 1024) and starts[-1] == 3584


def test_normalisation():
    segs = np.random.randn(10, 3, 100) * 5 + 2
    z = zscore_segments(segs)
    assert np.allclose(z.mean(-1), 0, atol=1e-6) and np.allclose(z.std(-1), 1, atol=1e-6)
    sc = ChannelStandardizer().fit(segs)
    out = sc.transform(segs)
    assert np.allclose(out.mean(axis=(0, 2)), 0, atol=1e-6)


def test_split_is_disjoint_and_complete():
    ids = list(range(1, 201))
    s = split_records(ids, 0.15, 0.15, seed=0)
    all_ids = s["train"] + s["val"] + s["test"]
    assert sorted(all_ids) == ids and len(set(all_ids)) == 200
    assert len(s["test"]) == 30 and len(s["val"]) == 30
    assert s == split_records(ids, 0.15, 0.15, seed=0)


@pytest.mark.skipif(not DATA_DIR.exists(), reason="matDBs/ not available")
@pytest.mark.parametrize("mode", ["beat", "window"])
def test_pipeline_on_real_data(tmp_path, mode):
    cfg = DataConfig(data_dir=str(DATA_DIR), segmentation=mode, leads=("ii", "v5"))
    assert list_records(DATA_DIR)[:3] == [1, 2, 3]
    sets, meta = build_datasets(cfg)
    for name, s in sets.items():
        assert s.x.shape[1:] == (2, cfg.segment_length)
        assert s.x.dtype == np.float32 and np.all(np.isfinite(s.x))
        assert set(np.unique(s.record_ids)) <= set(meta["records"][name])
    assert not set(sets["train"].record_ids) & set(sets["test"].record_ids)

    path = save_datasets(sets, meta, tmp_path / "d.npz")
    loaded, meta2 = load_datasets(path)
    assert meta2 == meta
    assert np.array_equal(loaded["val"].x, sets["val"].x)
