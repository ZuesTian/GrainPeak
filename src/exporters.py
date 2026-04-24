from __future__ import annotations

import csv
from pathlib import Path

from models import DataFile


def export_comparison_csv(path: Path, files: list[DataFile], axis_mode: str) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["axis_mode", axis_mode])
        writer.writerow(["file_count", len(files)])
        writer.writerow([])
        writer.writerow(["RAW_DATA"])
        writer.writerow(["file", "visible", "x_raw", "y_raw"])
        for item in files:
            for x_value, y_value in zip(item.raw_x, item.raw_y, strict=False):
                writer.writerow([item.name, item.visible, x_value, y_value])
        writer.writerow([])
        writer.writerow(["FIT_SUMMARY"])
        writer.writerow(["file", "model", "r_squared", "rmse"])
        for item in files:
            if item.fit_result:
                writer.writerow([item.name, item.fit_result.model_name, item.fit_result.r_squared, item.fit_result.rmse])
        writer.writerow([])
        writer.writerow(["PEAK_PARAMS"])
        writer.writerow(["file", "peak", "center", "height", "width", "area", "area_ratio", "extra", "meaning"])
        for item in files:
            if not item.fit_result:
                continue
            for row in item.fit_result.peak_table:
                writer.writerow(
                    [
                        item.name,
                        int(float(row["index"])),
                        row["center"],
                        row["height"],
                        row["width"],
                        row["area"],
                        row["area_ratio"],
                        row["extra"],
                        row["meaning"],
                    ]
                )
        writer.writerow([])
        writer.writerow(["FIT_CURVES"])
        writer.writerow(["file", "x_fit", "y_fit", "component_index", "component_y"])
        for item in files:
            if not item.fit_result:
                continue
            fit = item.fit_result
            for point_index, x_value in enumerate(fit.x_fit):
                writer.writerow([item.name, x_value, fit.y_fit[point_index], "total", ""])
                for component_index, component in enumerate(fit.components, start=1):
                    writer.writerow([item.name, x_value, "", component_index, component[point_index]])
