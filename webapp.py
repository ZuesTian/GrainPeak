from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from flask import Flask, jsonify, request


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fit_engine import FitEngine  # noqa: E402


APP_VERSION = "1.0.0"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_POINTS = 20_000
ALLOWED_MODELS = {"pseudo_voigt", "skew_normal", "gaussian"}
ALLOWED_AXES = {"linear", "log10", "ln"}

app = Flask(__name__, static_folder="web", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


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


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/health")
def health():
    return jsonify(status="ok", service="grainpeak", version=APP_VERSION)


@app.get("/api/sample")
def sample():
    sample_path = ROOT / "data" / "examples" / "粒度分析1.txt"
    return jsonify(filename=sample_path.name, text=sample_path.read_text(encoding="utf-8-sig"))


@app.post("/api/fit")
def fit():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="请求必须是 JSON。"), 400

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return jsonify(error="请上传包含两列数值的文本文件。"), 400
    if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
        return jsonify(error="单个文件不能超过 2 MB。"), 413

    model = str(payload.get("model", "pseudo_voigt"))
    axis_mode = str(payload.get("axis_mode", "linear"))
    try:
        peak_count = int(payload.get("peak_count", 4))
    except (TypeError, ValueError):
        return jsonify(error="峰数量必须是整数。"), 400
    use_fixed_four = bool(payload.get("use_fixed_four", False))

    if model not in ALLOWED_MODELS:
        return jsonify(error="未知拟合模型。"), 400
    if axis_mode not in ALLOWED_AXES:
        return jsonify(error="未知横坐标模式。"), 400
    if not 1 <= peak_count <= 8:
        return jsonify(error="峰数量必须在 1–8 之间。"), 400
    if use_fixed_four:
        peak_count = 4

    try:
        raw_x, raw_y = parse_two_column_text(text)
        x, y = transform_x(raw_x, raw_y, axis_mode)
        result = FitEngine.fit(x, y, model, peak_count, use_fixed_four)
    except (RuntimeError, ValueError) as exc:
        return jsonify(error=str(exc)), 422
    except Exception:
        app.logger.exception("GrainPeak fitting failed")
        return jsonify(error="拟合未收敛，请调整峰数量、坐标模式或数据范围后重试。"), 422

    peaks = []
    for row in result.peak_table:
        peaks.append(
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
        )

    return jsonify(
        filename=str(payload.get("filename") or "未命名数据"),
        axis_mode=axis_mode,
        model=result.model_name,
        point_count=int(len(x)),
        r_squared=finite_or_none(result.r_squared),
        rmse=finite_or_none(result.rmse),
        raw=compact_curve(x, y),
        fit=compact_curve(result.x_fit, result.y_fit),
        components=[compact_curve(result.x_fit, component) for component in result.components],
        peaks=peaks,
    )


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="请求不能超过 2 MB。"), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8770)
