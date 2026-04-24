from __future__ import annotations

from pathlib import Path

import numpy as np

from models import DataFile


class DataManager:
    @staticmethod
    def read_two_column_data(path: Path) -> np.ndarray:
        rows: list[list[float]] = []
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = path.read_text(errors="ignore")
        for line in text.splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            parts = clean.replace(",", " ").replace(";", " ").split()
            if len(parts) < 2:
                continue
            try:
                rows.append([float(parts[0]), float(parts[1])])
            except ValueError:
                continue
        if len(rows) < 4:
            raise ValueError("文件中有效数据少于 4 行。")
        data = np.array(rows, dtype=float)
        return data[np.argsort(data[:, 0])]

    @staticmethod
    def transform(item: DataFile, mode: str) -> tuple[np.ndarray, np.ndarray]:
        x = item.raw_x.astype(float)
        y = item.raw_y.astype(float)
        if mode == "linear":
            return x, y
        mask = x > 0
        x = x[mask]
        y = y[mask]
        if len(x) == 0:
            raise ValueError(f"{item.name}: Log/Ln 模式要求第一列数据大于 0。")
        if mode == "log10":
            return np.log10(x), y
        if mode == "ln":
            return np.log(x), y
        return x, y
