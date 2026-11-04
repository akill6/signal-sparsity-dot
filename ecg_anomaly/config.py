"""Configuration of the data pipeline (PTB-XL)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

# Standard 12-lead order (the order used by PTB-XL).
LEAD_NAMES: tuple[str, ...] = (
    "i", "ii", "iii", "avr", "avl", "avf",
    "v1", "v2", "v3", "v4", "v5", "v6",
)

# PTB-XL diagnostic superclasses.
SUPERCLASSES: tuple[str, ...] = ("NORM", "MI", "STTC", "CD", "HYP")

# Noise / device annotations of PTB-XL; records with any of them are left out
# of the training set when ``clean_train`` is enabled.
QUALITY_COLUMNS: tuple[str, ...] = (
    "baseline_drift", "static_noise", "burst_noise", "electrodes_problems", "pacemaker",
)


@dataclass
class DataConfig:
    """All parameters that define how PTB-XL recordings become model inputs."""

    data_dir: str = "data/ptb-xl"
    sampling_rate: Literal[100, 500] = 100

    # Leads used as input channels of the 1D-CNN (names from LEAD_NAMES).
    leads: tuple[str, ...] = LEAD_NAMES

    # --- Labels -----------------------------------------------------------
    # A record is "normal" when its only diagnostic superclass is NORM and the
    # cardiologist's likelihood for NORM is at least this value (0-100).
    # A record is "abnormal" when it has any of MI / STTC / CD / HYP.
    # Records that are neither (no diagnostic statement, or an uncertain NORM)
    # are not used.
    normal_min_likelihood: float = 100.0
    # Unsupervised setting: the autoencoder only ever sees normal ECGs.
    train_normal_only: bool = True
    # Drop records with noise / electrode / pacemaker annotations from training.
    clean_train: bool = True

    # --- Split (recommended PTB-XL stratified folds, patient-disjoint) -----
    train_folds: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8)
    val_folds: tuple[int, ...] = (9,)
    test_folds: tuple[int, ...] = (10,)
    # Optional cap on the number of records per split (quick experiments).
    max_records_per_split: int | None = None
    seed: int = 42

    # --- Filtering ----------------------------------------------------------
    bandpass_low: float = 0.5
    bandpass_high: float = 40.0
    filter_order: int = 4
    # Power-line notch; skipped automatically when >= Nyquist (100 Hz data).
    notch_freq: float | None = 50.0
    notch_q: float = 30.0

    # --- Segmentation -------------------------------------------------------
    #   "beat"   - one segment per heartbeat, centred on the detected R peak
    #   "window" - fixed-length sliding windows
    segmentation: Literal["beat", "window"] = "beat"
    # Lengths in samples. ``None`` = default scaled to the sampling rate:
    #   beat:   0.24 s before + 0.40 s after R  (64 samples @100 Hz, 320 @500 Hz)
    #   window: 2.56 s, stride 1.28 s           (256 samples @100 Hz, 1280 @500 Hz)
    beat_pre: int | None = None
    beat_post: int | None = None
    window_size: int | None = None
    window_stride: int | None = None

    # --- Normalisation ------------------------------------------------------
    #   "segment" - z-score of every segment and channel on its own
    #   "global"  - per-channel mean/std fitted on the training split only
    #   "none"    - keep the filtered amplitudes (mV)
    normalization: Literal["segment", "global", "none"] = "segment"

    def __post_init__(self) -> None:
        if self.sampling_rate not in (100, 500):
            raise ValueError("sampling_rate must be 100 or 500")
        self.leads = tuple(self.leads)
        scale = self.sampling_rate // 100
        if self.beat_pre is None:
            self.beat_pre = 24 * scale
        if self.beat_post is None:
            self.beat_post = 40 * scale
        if self.window_size is None:
            self.window_size = 256 * scale
        if self.window_stride is None:
            self.window_stride = 128 * scale

    @property
    def fs(self) -> float:
        return float(self.sampling_rate)

    @property
    def lead_indices(self) -> list[int]:
        unknown = [lead for lead in self.leads if lead not in LEAD_NAMES]
        if unknown:
            raise ValueError(f"Unknown lead(s) {unknown}; expected some of {LEAD_NAMES}")
        return [LEAD_NAMES.index(lead) for lead in self.leads]

    @property
    def segment_length(self) -> int:
        if self.segmentation == "beat":
            return self.beat_pre + self.beat_post
        return self.window_size

    def to_dict(self) -> dict:
        return asdict(self)
