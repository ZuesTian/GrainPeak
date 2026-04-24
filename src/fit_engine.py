from __future__ import annotations

import math

import numpy as np

from app_constants import FIXED_FOUR_PEAKS
from models import FitResult
from peaks import (
    find_peak_indices,
    gaussian,
    gaussian_mixture,
    peak_meaning,
    pseudo_voigt,
    pseudo_voigt_mixture,
    skew_normal_mixture,
    skew_normal_peak,
)

try:
    from scipy.optimize import curve_fit
except Exception as exc:  # pragma: no cover
    raise RuntimeError("缺少 scipy，请先安装：pip install scipy") from exc


class FitEngine:
    @staticmethod
    def initial_centers(
        x: np.ndarray,
        y: np.ndarray,
        peak_count: int,
        use_fixed_four: bool,
    ) -> np.ndarray:
        if use_fixed_four:
            return np.clip(FIXED_FOUR_PEAKS, float(np.min(x)), float(np.max(x)))
        prominence = max(float(np.ptp(y)) * 0.04, 1e-9)
        distance = max(1, len(x) // max(peak_count * 3, 1))
        peaks, prominences = find_peak_indices(y, prominence=prominence, distance=distance)
        centers = np.array([], dtype=float)
        if len(peaks):
            selected = peaks[np.argsort(prominences)[-peak_count:]]
            centers = np.sort(x[selected])
        if len(centers) < peak_count:
            fallback = np.quantile(x, np.linspace(0.15, 0.85, peak_count))
            centers = np.unique(np.concatenate([centers, fallback]))
        if len(centers) > peak_count:
            centers = centers[np.linspace(0, len(centers) - 1, peak_count).round().astype(int)]
        return np.sort(centers[:peak_count])

    @staticmethod
    def fit(x: np.ndarray, y: np.ndarray, model_key: str, peak_count: int, use_fixed_four: bool) -> FitResult:
        centers = FitEngine.initial_centers(x, y, peak_count, use_fixed_four)
        span = max(float(np.ptp(x)), 1e-6)
        default_width = span / max(len(centers) * 5.0, 8.0)
        baseline = max(float(np.nanmin(y)), 0.0)
        y_work = np.maximum(y - baseline, 0)
        max_y = max(float(np.nanmax(y_work)), 1e-6)

        if model_key == "gaussian":
            func = gaussian_mixture
            model_display = "标准高斯混合"
            param_width = 3
            p0, lower, upper = FitEngine.initial_bounds(x, y_work, centers, default_width, max_y, span)
            component_builder = FitEngine.gaussian_components
        elif model_key == "skew_normal":
            func = skew_normal_mixture
            model_display = "偏斜高斯混合"
            param_width = 4
            p0, lower, upper = FitEngine.initial_bounds(x, y_work, centers, default_width, max_y, span, (0.0, -20.0, 20.0))
            component_builder = FitEngine.skew_components
        else:
            func = pseudo_voigt_mixture
            model_display = "伪沃伊特函数"
            param_width = 4
            p0, lower, upper = FitEngine.initial_bounds(x, y_work, centers, default_width, max_y, span, (0.5, 0.0, 1.0))
            component_builder = FitEngine.pseudo_voigt_components

        params, _ = curve_fit(
            func,
            x,
            y_work,
            p0=np.array(p0, dtype=float),
            bounds=(np.array(lower, dtype=float), np.array(upper, dtype=float)),
            maxfev=50000,
        )
        x_fit = np.linspace(float(np.min(x)), float(np.max(x)), 1000)
        y_fit = func(x_fit, *params) + baseline
        components = component_builder(x_fit, params)
        y_pred = func(x, *params) + baseline
        residual = y - y_pred
        ss_res = float(np.sum(residual**2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
        rmse = math.sqrt(ss_res / len(y))
        peak_table = FitEngine.build_peak_table(x_fit, components, params, param_width)
        return FitResult(model_display, x_fit, y_fit, components, params, peak_table, r_squared, rmse)

    @staticmethod
    def initial_bounds(
        x: np.ndarray,
        y_work: np.ndarray,
        centers: np.ndarray,
        default_width: float,
        max_y: float,
        span: float,
        extra_bounds: tuple[float, float, float] | None = None,
    ) -> tuple[list[float], list[float], list[float]]:
        p0: list[float] = []
        lower: list[float] = []
        upper: list[float] = []
        for center in centers:
            amplitude = max(float(np.interp(center, x, y_work)), max_y / len(centers))
            p0.extend([amplitude, float(center), default_width])
            lower.extend([0.0, float(np.min(x)), span / 10000.0])
            upper.extend([max_y * 5.0, float(np.max(x)), span])
            if extra_bounds is not None:
                initial, low, high = extra_bounds
                p0.append(initial)
                lower.append(low)
                upper.append(high)
        return p0, lower, upper

    @staticmethod
    def gaussian_components(x: np.ndarray, params: np.ndarray) -> list[np.ndarray]:
        return [gaussian(x, params[i], params[i + 1], params[i + 2]) for i in range(0, len(params), 3)]

    @staticmethod
    def pseudo_voigt_components(x: np.ndarray, params: np.ndarray) -> list[np.ndarray]:
        return [pseudo_voigt(x, params[i], params[i + 1], params[i + 2], params[i + 3]) for i in range(0, len(params), 4)]

    @staticmethod
    def skew_components(x: np.ndarray, params: np.ndarray) -> list[np.ndarray]:
        return [skew_normal_peak(x, params[i], params[i + 1], params[i + 2], params[i + 3]) for i in range(0, len(params), 4)]

    @staticmethod
    def build_peak_table(
        x_fit: np.ndarray,
        components: list[np.ndarray],
        params: np.ndarray,
        param_width: int,
    ) -> list[dict[str, float | str]]:
        table: list[dict[str, float | str]] = []
        areas = [float(np.trapezoid(component, x_fit)) for component in components]
        total_area = sum(areas)
        for index, component in enumerate(components):
            peak_index = int(np.argmax(component))
            group = params[index * param_width : (index + 1) * param_width]
            center = float(x_fit[peak_index])
            extra = group[3] if len(group) > 3 else float("nan")
            area = areas[index]
            table.append(
                {
                    "index": float(index + 1),
                    "center": center,
                    "height": float(component[peak_index]),
                    "width": float(abs(group[2])),
                    "area": area,
                    "area_ratio": (area / total_area * 100) if total_area else 0.0,
                    "extra": float(extra),
                    "meaning": peak_meaning(center),
                }
            )
        return table
