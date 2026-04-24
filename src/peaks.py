from __future__ import annotations

import math

import numpy as np

from app_constants import PEAK_MEANINGS

try:
    from scipy.signal import find_peaks as scipy_find_peaks
except Exception as exc:  # pragma: no cover
    raise RuntimeError("缺少 scipy，请先安装：pip install scipy") from exc


def gaussian(x: np.ndarray, amplitude: float, center: float, sigma: float) -> np.ndarray:
    sigma = max(abs(float(sigma)), 1e-9)
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def pseudo_voigt(x: np.ndarray, amplitude: float, center: float, width: float, eta: float) -> np.ndarray:
    width = max(abs(float(width)), 1e-9)
    eta = min(max(float(eta), 0.0), 1.0)
    gaussian_part = np.exp(-4.0 * math.log(2.0) * ((x - center) / width) ** 2)
    lorentz_part = 1.0 / (1.0 + 4.0 * ((x - center) / width) ** 2)
    return amplitude * (eta * lorentz_part + (1.0 - eta) * gaussian_part)


def skew_normal_peak(x: np.ndarray, amplitude: float, center: float, sigma: float, alpha: float) -> np.ndarray:
    sigma = max(abs(float(sigma)), 1e-9)
    z = (x - center) / sigma
    normal = np.exp(-0.5 * z**2)
    erf_values = np.array([math.erf(value) for value in alpha * z / math.sqrt(2.0)], dtype=float)
    cdf = 0.5 * (1.0 + erf_values)
    return amplitude * 2.0 * normal * cdf


def find_peak_indices(y: np.ndarray, prominence: float, distance: int) -> tuple[np.ndarray, np.ndarray]:
    peaks, properties = scipy_find_peaks(y, prominence=prominence, distance=distance)
    if len(peaks):
        return peaks.astype(int), np.asarray(properties.get("prominences", np.ones(len(peaks))), dtype=float)

    if len(y) < 3:
        return np.array([], dtype=int), np.array([], dtype=float)
    candidates: list[tuple[int, float]] = []
    for index in range(1, len(y) - 1):
        if y[index] <= y[index - 1] or y[index] <= y[index + 1]:
            continue
        left_min = float(np.min(y[: index + 1]))
        right_min = float(np.min(y[index:]))
        score = float(y[index] - max(left_min, right_min))
        if score >= prominence:
            candidates.append((index, score))
    selected: list[tuple[int, float]] = []
    for index, score in sorted(candidates, key=lambda item: item[1], reverse=True):
        if all(abs(index - existing_index) >= distance for existing_index, _ in selected):
            selected.append((index, score))
    selected.sort(key=lambda item: item[0])
    return (
        np.array([index for index, _score in selected], dtype=int),
        np.array([score for _index, score in selected], dtype=float),
    )


def gaussian_mixture(x: np.ndarray, *params: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for index in range(0, len(params), 3):
        y += gaussian(x, params[index], params[index + 1], params[index + 2])
    return y


def pseudo_voigt_mixture(x: np.ndarray, *params: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for index in range(0, len(params), 4):
        y += pseudo_voigt(x, params[index], params[index + 1], params[index + 2], params[index + 3])
    return y


def skew_normal_mixture(x: np.ndarray, *params: float) -> np.ndarray:
    y = np.zeros_like(x, dtype=float)
    for index in range(0, len(params), 4):
        y += skew_normal_peak(x, params[index], params[index + 1], params[index + 2], params[index + 3])
    return y


def peak_meaning(center: float) -> str:
    reference, meaning = min(PEAK_MEANINGS, key=lambda item: abs(center - item[0]))
    return meaning if abs(center - reference) <= 0.45 else ""
