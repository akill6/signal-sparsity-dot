# Unsupervised ECG Anomaly Detection via 1D-CNN Autoencoders

## Dataset: PTB-XL

The project uses **PTB-XL 1.0.3**, one of the most widely used public ECG databases:

| Property | Value |
|----------|-------|
| Recordings | 21,799 clinical 12-lead ECGs, 10 s each, from 18,869 patients |
| Sampling rate | 100 Hz and 500 Hz versions |
| Labels | SCP-ECG statements validated by cardiologists, grouped into 5 diagnostic superclasses: NORM, MI, STTC, CD, HYP |
| Splits | 10 stratified, patient-disjoint folds (folds 9 and 10 are the recommended validation and test sets) |
| Size | about 0.5 GB (100 Hz) / 2.6 GB (500 Hz) |
| License | CC BY 4.0 |

Source: <https://physionet.org/content/ptb-xl/1.0.3/>. Please cite:

> Wagner, P., Strodthoff, N., Bousseljot, R.-D., Kreiseler, D., Lunze, F. I., Samek, W., & Schaeffter, T. (2020).
> PTB-XL, a large publicly available electrocardiography dataset. *Scientific Data*, 7, 154.
> https://doi.org/10.1038/s41597-020-0495-6

> Wagner, P., Strodthoff, N., Bousseljot, R., Samek, W., & Schaeffter, T. (2022). PTB-XL, a large publicly available
> electrocardiography dataset (version 1.0.3). PhysioNet. https://doi.org/10.13026/kfzx-aw45

The LUDB signals in `matDBs/` remain the data of the MATLAB sparsity app and are not used here.

## Unsupervised setting

| Label | Definition | Used for |
|-------|------------|----------|
| normal (0) | the only diagnostic superclass is NORM and its likelihood is 100 % | training (folds 1–8), val, test |
| abnormal (1) | at least one of MI, STTC, CD, HYP | val and test only |
| unused | no diagnostic statement, or NORM with likelihood < 100 % | — |

The autoencoder **only sees normal ECGs** during training. By default, training records with noise, electrode or
pacemaker annotations are excluded as well. The labels and superclasses of val/test segments are stored only to
evaluate the anomaly score (the reconstruction error).

## Part 1: data pipeline

```
PTB-XL ─► labels from scp_codes ─► folds 1-8 / 9 / 10 → train (normal only) / val / test
       ─► band-pass 0.5–40 Hz (+ 50 Hz notch at 500 Hz), zero-phase
       ─► segmentation: beats around R peaks (lead II) | sliding windows
       ─► normalisation: per-segment z-score | global (fit on train)
       ─► data/ptbxl_segments.npz  (+ .json metadata)
```

| Module | Contents |
|--------|----------|
| `config.py` | `DataConfig`: all pipeline parameters, lead and superclass names |
| `preprocessing.py` | filters, R-peak detector (simplified Pan–Tompkins), segmentation, normalisation |
| `data.py` | WFDB reader, PTB-XL labels and splits, `build_datasets`, saving and loading `.npz` |
| `torch_dataset.py` | `ECGSegmentDataset`, `make_loaders` (train: `(input, target)`, val/test: `(input, target, label)`) |

Default segment lengths are divisible by 16 (100 Hz: beat 64, window 256; 500 Hz: beat 320, window 1280),
so the autoencoder can downsample four times by a factor of 2 and upsample back to exactly the same length.

### Usage

```bash
pip install -r requirements.txt
python scripts/download_ptbxl.py                  # 100 Hz, into data/ptb-xl (resumable)
python scripts/prepare_data.py                    # beats, 12 leads
python scripts/prepare_data.py --segmentation window --leads ii v1 v5 --out data/ptbxl_windows.npz
python -m pytest tests                            # uses a synthetic mini PTB-XL, no download needed
```

```python
from ecg_anomaly import load_datasets
from ecg_anomaly.torch_dataset import make_loaders

sets, meta = load_datasets("data/ptbxl_segments.npz")
loaders = make_loaders(sets, batch_size=256)
x, target = next(iter(loaders["train"]))          # (batch, 12, 64)
x, target, label = next(iter(loaders["test"]))
```
