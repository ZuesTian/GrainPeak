from __future__ import annotations

import math
import hashlib
import sys
from collections import OrderedDict
from pathlib import Path
from threading import Lock

import numpy as np
from flask import Flask, jsonify, request


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fit_engine import FitEngine  # noqa: E402


APP_VERSION = "1.1.0"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 14 * 1024 * 1024
MAX_POINTS = 20_000
MAX_BATCH_POINTS = 60_000
MAX_FILES = 6
ALLOWED_MODELS = {"pseudo_voigt", "skew_normal", "gaussian"}
ALLOWED_AXES = {"linear", "log10", "ln"}

app = Flask(__name__, static_folder="web", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

_FIT_CACHE: OrderedDict[str, dict] = OrderedDict()
_FIT_CACHE_LOCK = Lock()
_FIT_CACHE_SIZE = 18


class ApiError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def parse_two_column_text(text: str) -> tuple[np.ndarray, np.ndarray]:
    rows: list[tuple[float, float]] = []
    for line in text.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        parts = clean.replace(",", " ").replace(";", " ").replace("\t", " ").split()
        if len(parts) < 2:
            continue
        try:
            x_value, y_value = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if math.isfinite(x_value) and math.isfinite(y_value):
            rows.append((x_value, y_value))
    if len(rows) < 4:
        raise ValueError("文件中有效的两列数值数据少于 4 行。")
    if len(rows) > MAX_POINTS:
        raise ValueError(f"数据点不能超过 {MAX_POINTS:,} 个。")
    data = np.asarray(rows, dtype=float)
    data = data[np.argsort(data[:, 0])]
    unique_x, unique_indices = np.unique(data[:, 0], return_index=True)
    if unique_x.size < 4:
        raise ValueError("第一列至少需要 4 个不同的数值。")
    return unique_x, data[unique_indices, 1]


def transform_x(x: np.ndarray, y: np.ndarray, axis_mode: str) -> tuple[np.ndarray, np.ndarray]:
    if axis_mode == "linear":
        return x, y
    mask = x > 0
    if np.count_nonzero(mask) < 4:
        raise ValueError("Log10/Ln 模式至少需要 4 个大于 0 的横坐标。")
    x, y = x[mask], y[mask]
    return (np.log10(x), y) if axis_mode == "log10" else (np.log(x), y)


def finite_or_none(value: float) -> float | None:
    number = float(value)
    return number if math.isfinite(number) else None


def compact_curve(x: np.ndarray, y: np.ndarray, maximum: int = 1600) -> dict[str, list[float]]:
    if len(x) > maximum:
        indices = np.linspace(0, len(x) - 1, maximum).round().astype(int)
        x, y = x[indices], y[indices]
    return {"x": x.astype(float).tolist(), "y": y.astype(float).tolist()}


def parse_options(payload: dict) -> tuple[str, str, int, bool]:
    model = str(payload.get("model", "pseudo_voigt"))
    axis_mode = str(payload.get("axis_mode", "linear"))
    try:
        peak_count = int(payload.get("peak_count", 4))
    except (TypeError, ValueError) as exc:
        raise ApiError("峰数量必须是整数。") from exc
    use_fixed_four = bool(payload.get("use_fixed_four", False))
    if model not in ALLOWED_MODELS:
        raise ApiError("未知拟合模型。")
    if axis_mode not in ALLOWED_AXES:
        raise ApiError("未知横坐标模式。")
    if not 1 <= peak_count <= 12:
        raise ApiError("峰数量必须在 1–12 之间。")
    return model, axis_mode, 4 if use_fixed_four else peak_count, use_fixed_four


def parse_item(payload: dict) -> tuple[str, str, np.ndarray, np.ndarray]:
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError("请上传包含两列数值的文本文件。")
    if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise ApiError("单个文件不能超过 2 MB。", 413)
    raw_x, raw_y = parse_two_column_text(text)
    return str(payload.get("filename") or "未命名数据"), text, raw_x, raw_y


def fit_item(
    payload: dict,
    options: tuple[str, str, int, bool],
    parsed: tuple[str, str, np.ndarray, np.ndarray] | None = None,
) -> dict:
    model, axis_mode, peak_count, use_fixed_four = options
    filename, text, raw_x, raw_y = parsed or parse_item(payload)
    cache_key = hashlib.sha256(
        (f"{model}|{axis_mode}|{peak_count}|{int(use_fixed_four)}|" + text).encode("utf-8")
    ).hexdigest()
    with _FIT_CACHE_LOCK:
        cached = _FIT_CACHE.get(cache_key)
        if cached is not None:
            _FIT_CACHE.move_to_end(cache_key)
            return {
                **cached,
                "filename": filename,
                "client_id": str(payload.get("client_id") or ""),
                "cache_hit": True,
            }

    x, y = transform_x(raw_x, raw_y, axis_mode)
    result = FitEngine.fit(x, y, model, peak_count, use_fixed_four)
    peaks = [
        {
            "index": int(float(row["index"])),
            "center": finite_or_none(row["center"]),
            "height": finite_or_none(row["height"]),
            "width": finite_or_none(row["width"]),
            "area": finite_or_none(row["area"]),
            "area_ratio": finite_or_none(row["area_ratio"]),
            "extra": finite_or_none(row["extra"]),
            "meaning": str(row["meaning"]),
        }
        for row in result.peak_table
    ]
    core = {
        "axis_mode": axis_mode,
        "model": result.model_name,
        "point_count": int(len(x)),
        "r_squared": finite_or_none(result.r_squared),
        "rmse": finite_or_none(result.rmse),
        "raw": compact_curve(x, y),
        "fit": compact_curve(result.x_fit, result.y_fit),
        "components": [compact_curve(result.x_fit, component) for component in result.components],
        "peaks": peaks,
    }
    with _FIT_CACHE_LOCK:
        _FIT_CACHE[cache_key] = core
        _FIT_CACHE.move_to_end(cache_key)
        while len(_FIT_CACHE) > _FIT_CACHE_SIZE:
            _FIT_CACHE.popitem(last=False)
    return {
        **core,
        "filename": filename,
        "client_id": str(payload.get("client_id") or ""),
        "cache_hit": False,
    }


def error_response(exc: Exception):
    if isinstance(exc, ApiError):
        return jsonify(error=str(exc)), exc.status
    if isinstance(exc, (RuntimeError, ValueError)):
        return jsonify(error=str(exc)), 422
    app.logger.exception("GrainPeak fitting failed")
    return jsonify(error="拟合未收敛，请调整峰数量、坐标模式或数据范围后重试。"), 422


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/health")
def health():
    return jsonify(status="ok", service="grainpeak", version=APP_VERSION)


@app.get("/api/samples")
def samples():
    sample_paths = sorted((ROOT / "data" / "examples").glob("*.txt"))
    return jsonify(
        files=[
            {"filename": path.name, "text": path.read_text(encoding="utf-8-sig")}
            for path in sample_paths[:MAX_FILES]
        ]
    )


@app.post("/api/fit")
def fit():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="请求必须是 JSON。"), 400
    try:
        return jsonify(fit_item(payload, parse_options(payload)))
    except Exception as exc:
        return error_response(exc)


@app.post("/api/batch-fit")
def batch_fit():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="请求必须是 JSON。"), 400
    files = payload.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        return jsonify(error=f"批量拟合需要 1–{MAX_FILES} 个文件。"), 400
    if not all(isinstance(item, dict) for item in files):
        return jsonify(error="文件列表格式不正确。"), 400
    try:
        options = parse_options(payload)
    except Exception as exc:
        return error_response(exc)

    prepared: list[tuple[dict, tuple[str, str, np.ndarray, np.ndarray]]] = []
    errors: list[dict[str, str]] = []
    total_points = 0
    for item in files:
        try:
            parsed = parse_item(item)
            total_points += len(parsed[2])
            if total_points > MAX_BATCH_POINTS:
                raise ApiError(f"批量数据总点数不能超过 {MAX_BATCH_POINTS:,}。")
            prepared.append((item, parsed))
        except Exception as exc:
            errors.append(
                {
                    "client_id": str(item.get("client_id") or ""),
                    "filename": str(item.get("filename") or "未命名数据"),
                    "error": str(exc),
                }
            )

    results = []
    for item, parsed in prepared:
        try:
            results.append(fit_item(item, options, parsed))
        except Exception as exc:
            errors.append(
                {
                    "client_id": str(item.get("client_id") or ""),
                    "filename": str(item.get("filename") or "未命名数据"),
                    "error": str(exc),
                }
            )
    return jsonify(
        requested=len(files),
        succeeded=len(results),
        total_points=total_points,
        results=results,
        errors=errors,
    )


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="请求总大小不能超过 8 MB；单个文件不能超过 2 MB。"), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8770)
