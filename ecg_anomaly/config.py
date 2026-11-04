"""Configuration of the data pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

# Lead order of the LUDB recordings (columns of ``ecgSignal``).
LEAD_NAMES: tuple[str, ...] = (
    "i", "ii", "iii", "avr", "avl", "avf",
    "v1", "v2", "v3", "v4", "v5", "v6",
)


@dataclass
class DataConfig:
    """All parameters that define how raw recordings become model inputs."""

    data_dir: str = "matDBs"
    variable: str = "ecgSignal"
    fs: float = 500.0

    # Leads used as input channels of the 1D-CNN (names from LEAD_NAMES).
    leads: tuple[str, ...] = ("ii",)

    # Butterworth band-pass filter (baseline wander + high-frequency noise).
    bandpass_low: float = 0.5
    bandpass_high: float = 40.0
    filter_order: int = 4
    # Power-line notch filter; ``None`` disables it.
    notch_freq: float | None = 50.0
    notch_q: float = 30.0

    # Segmentation:
    #   "beat"   - one segment per heartbeat, centred on the detected R peak
    #   "window" - fixed-length sliding windows
    segmentation: Literal["beat", "window"] = "beat"
    beat_pre: int = 128    # samples before the R peak (256 ms at 500 Hz)
    beat_post: int = 192   # samples after the R peak (384 ms at 500 Hz)
    window_size: int = 1024
    window_stride: int = 512

    # Normalisation:
    #   "segment" - z-score of every segment on its own
    #   "global"  - per-channel mean/std fitted on the training split only
    #   "none"    - keep the filtered amplitudes (mV)
    normalization: Literal["segment", "global", "none"] = "segment"

    # Record-level split (no recording appears in two splits -> no leakage).
    val_fraction: float = 0.15
    test_fraction: float = 0.15
    seed: int = 42

    # Records excluded entirely (e.g. known noisy files); 1-based file numbers.
    exclude_records: tuple[int, ...] = field(default_factory=tuple)

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
