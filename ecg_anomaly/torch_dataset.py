"""PyTorch wrappers around the preprocessed segments (requires ``torch``)."""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from .data import SegmentSet


class ECGSegmentDataset(Dataset):
    """Returns ``(input, target)`` pairs: an autoencoder reconstructs its own input.

    With ``return_labels=True`` it returns ``(input, target, label)`` instead,
    where label is 0 (normal) or 1 (abnormal); use this only for evaluation.

    Optional light augmentation for the training split (amplitude scaling and
    additive Gaussian noise) makes the autoencoder less sensitive to recording
    conditions, so that reconstruction error reflects morphology instead.
    """

    def __init__(self, segments: SegmentSet, augment: bool = False, return_labels: bool = False,
                 noise_std: float = 0.02, scale_range: tuple[float, float] = (0.9, 1.1)):
        self.x = torch.from_numpy(np.ascontiguousarray(segments.x, dtype=np.float32))
        self.record_ids = torch.from_numpy(segments.record_ids.astype(np.int64))
        self.labels = torch.from_numpy(segments.labels.astype(np.int64))
        self.return_labels = return_labels
        self.augment = augment
        self.noise_std = noise_std
        self.scale_range = scale_range

    def __len__(self) -> int:
        return self.x.shape[0]

    def __getitem__(self, idx: int):
        target = self.x[idx]
        inp = target
        if self.augment:
            lo, hi = self.scale_range
            scale = torch.empty(1).uniform_(lo, hi)
            inp = target * scale + self.noise_std * torch.randn_like(target)
            target = target * scale
        if self.return_labels:
            return inp, target, self.labels[idx]
        return inp, target


def make_loaders(sets: dict[str, SegmentSet], batch_size: int = 128,
                 num_workers: int = 0, augment_train: bool = True) -> dict[str, DataLoader]:
    """Train loader yields ``(input, target)``; val/test loaders also yield labels."""
    return {
        name: DataLoader(
            ECGSegmentDataset(s, augment=augment_train and name == "train",
                              return_labels=name != "train"),
            batch_size=batch_size,
            shuffle=name == "train",
            num_workers=num_workers,
            drop_last=False,
        )
        for name, s in sets.items()
    }
