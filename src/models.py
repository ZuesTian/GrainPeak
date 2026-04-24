from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class FitResult:
    model_name: str
    x_fit: np.ndarray
    y_fit: np.ndarray
    components: list[np.ndarray]
    params: np.ndarray
    peak_table: list[dict[str, float | str]]
    r_squared: float
    rmse: float


@dataclass
class DataFile:
    path: Path
    raw_x: np.ndarray
    raw_y: np.ndarray
    color: str
    marker: str
    visible: bool = True
    fit_result: FitResult | None = None
    id: int = field(default=0)

    @property
    def name(self) -> str:
        return self.path.name
