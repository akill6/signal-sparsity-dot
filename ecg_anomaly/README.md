# Unsupervised ECG Anomaly Detection via 1D-CNN Autoencoders

## Part 1: data pipeline

This turns the LUDB recordings in `matDBs/` (200 × `ecgSignal`, 5000 × 12, 500 Hz) into segment datasets
that a 1D-CNN autoencoder can train on.

```
matDBs/*.mat ─► load ─► record-level split (train/val/test)
             ─► band-pass 0.5–40 Hz + 50 Hz notch (zero-phase)
             ─► segmentation: beats around R peaks  |  sliding windows
             ─► normalisation: per-segment z-score  |  global (fit on train)
             ─► data/ludb_segments.npz  (+ .json metadata)
```

| Module | Contents |
|--------|----------|
| `config.py` | `DataConfig`: all pipeline parameters, lead names |
| `preprocessing.py` | filters, R-peak detector (simplified Pan–Tompkins), segmentation, normalisation |
| `data.py` | loading `.mat` files, record-level split, `build_datasets`, saving and loading `.npz` |
| `torch_dataset.py` | `ECGSegmentDataset` returning `(input, target)` pairs, `make_loaders` |

The split is done **by recording**, so beats from one patient never appear in both the training and the test data.

### Usage

```bash
pip install -r requirements.txt
python scripts/prepare_data.py                                     # beats, lead II, 320 samples
python scripts/prepare_data.py --segmentation window --leads i ii v5
python -m pytest tests
```

```python
from ecg_anomaly import load_datasets
from ecg_anomaly.torch_dataset import make_loaders

sets, meta = load_datasets("data/ludb_segments.npz")
loaders = make_loaders(sets, batch_size=128)
x, target = next(iter(loaders["train"]))   # (batch, channels, length)
```

Segment lengths (320 for beats, 1024 for windows) are divisible by 16, so the autoencoder can downsample them
four times by a factor of 2 and upsample back to exactly the same length.
