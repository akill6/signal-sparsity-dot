"""Filtering, R-peak detection, segmentation and normalisation."""

from __future__ import annotations

import numpy as np
from scipy import signal

from .config import DataConfig


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #
def bandpass_filter(x: np.ndarray, fs: float, low: float, high: float, order: int = 4) -> np.ndarray:
    """Zero-phase Butterworth band-pass filter along the time axis (axis 0)."""
    sos = signal.butter(order, [low, high], btype="bandpass", fs=fs, output="sos")
    return signal.sosfiltfilt(sos, x, axis=0)


def notch_filter(x: np.ndarray, fs: float, freq: float, q: float = 30.0) -> np.ndarray:
    """Zero-phase IIR notch filter (power-line interference)."""
    b, a = signal.iirnotch(freq, q, fs=fs)
    return signal.filtfilt(b, a, x, axis=0)


def filter_ecg(x: np.ndarray, cfg: DataConfig) -> np.ndarray:
    """Apply the configured filter chain to an array of shape (samples, leads)."""
    y = bandpass_filter(x, cfg.fs, cfg.bandpass_low, cfg.bandpass_high, cfg.filter_order)
    if cfg.notch_freq is not None and cfg.notch_freq < cfg.fs / 2:
        y = notch_filter(y, cfg.fs, cfg.notch_freq, cfg.notch_q)
    return y


# --------------------------------------------------------------------------- #
# R-peak detection (simplified Pan-Tompkins)
# --------------------------------------------------------------------------- #
def detect_r_peaks(
    x: np.ndarray,
    fs: float,
    min_rr: float = 0.25,
    integration_window: float = 0.15,
    refine_window: float = 0.05,
) -> np.ndarray:
    """Detect R peaks in a single-lead ECG.

    Steps: 5-15 Hz band-pass -> derivative -> squaring -> moving-window
    integration -> peak picking with a refractory period -> refinement to the
    sample with the largest absolute amplitude of the original signal.
    The absolute value is used so that leads with negative QRS (e.g. aVR)
    are handled too.

    Returns sorted sample indices of the detected R peaks.
    """
    x = np.asarray(x, dtype=float).ravel()
    if x.size < int(fs):
        return np.empty(0, dtype=int)

    qrs = bandpass_filter(x, fs, 5.0, 15.0, order=2)
    energy = np.diff(qrs, prepend=qrs[0]) ** 2
    win = max(1, int(round(integration_window * fs)))
    integrated = np.convolve(energy, np.ones(win) / win, mode="same")

    # Adaptive threshold relative to the median height of the strongest
    # candidates (at least one beat per ~1.5 s is expected), so that a single
    # large artefact cannot push the threshold above all real QRS complexes.
    candidates, props = signal.find_peaks(integrated, height=0, distance=int(min_rr * fs))
    if candidates.size == 0:
        return np.empty(0, dtype=int)
    heights = np.sort(props["peak_heights"])[::-1]
    n_ref = max(3, int(x.size / fs / 1.5))
    threshold = 0.3 * np.median(heights[:n_ref])
    peaks = candidates[props["peak_heights"] >= threshold]

    half = int(round(refine_window * fs))
    abs_x = np.abs(x)
    refined = []
    for p in peaks:
        lo, hi = max(0, p - half), min(x.size, p + half + 1)
        refined.append(lo + int(np.argmax(abs_x[lo:hi])))
    refined = np.unique(np.asarray(refined, dtype=int))

    # Refinement can move two neighbouring peaks closer than min_rr; keep the
    # stronger one.
    if refined.size > 1:
        keep = [refined[0]]
        for p in refined[1:]:
            if p - keep[-1] < min_rr * fs:
                if abs_x[p] > abs_x[keep[-1]]:
                    keep[-1] = p
            else:
                keep.append(p)
        refined = np.asarray(keep, dtype=int)
    return refined


# --------------------------------------------------------------------------- #
# Segmentation
# --------------------------------------------------------------------------- #
def segment_beats(x: np.ndarray, r_peaks: np.ndarray, pre: int, post: int) -> tuple[np.ndarray, np.ndarray]:
    """Cut beat-centred segments from x of shape (samples, channels).

    Beats whose window would leave the recording are dropped.
    Returns ``(segments, centers)`` with segments of shape (n, channels, pre + post).
    """
    n = x.shape[0]
    centers = np.asarray([r for r in r_peaks if r - pre >= 0 and r + post <= n], dtype=int)
    if centers.size == 0:
        return np.empty((0, x.shape[1], pre + post)), centers
    segs = np.stack([x[r - pre : r + post].T for r in centers])
    return segs, centers


def segment_windows(x: np.ndarray, size: int, stride: int) -> tuple[np.ndarray, np.ndarray]:
    """Cut fixed-length sliding windows from x of shape (samples, channels).

    Returns ``(segments, starts)`` with segments of shape (n, channels, size).
    """
    n = x.shape[0]
    if n < size:
        return np.empty((0, x.shape[1], size)), np.empty(0, dtype=int)
    starts = np.arange(0, n - size + 1, stride, dtype=int)
    segs = np.stack([x[s : s + size].T for s in starts])
    return segs, starts


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def zscore_segments(segs: np.ndarray, eps: float = 1e-8) -> np.ndarray:
    """Z-score every segment and channel independently. segs: (n, channels, length)."""
    mean = segs.mean(axis=-1, keepdims=True)
    std = segs.std(axis=-1, keepdims=True)
    return (segs - mean) / (std + eps)


class ChannelStandardizer:
    """Per-channel standardisation fitted on the training data only."""

    def __init__(self, eps: float = 1e-8):
        self.eps = eps
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None

    def fit(self, segs: np.ndarray) -> "ChannelStandardizer":
        self.mean_ = segs.mean(axis=(0, 2), keepdims=True)[0]
        self.std_ = segs.std(axis=(0, 2), keepdims=True)[0]
        return self

    def transform(self, segs: np.ndarray) -> np.ndarray:
        if self.mean_ is None or self.std_ is None:
            raise RuntimeError("ChannelStandardizer must be fitted before transform()")
        return (segs - self.mean_) / (self.std_ + self.eps)

    def fit_transform(self, segs: np.ndarray) -> np.ndarray:
        return self.fit(segs).transform(segs)
