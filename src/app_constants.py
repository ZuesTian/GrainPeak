from __future__ import annotations

import numpy as np

APP_TITLE = "粒度分析分峰软件"
MAX_FILES = 6
FIXED_FOUR_PEAKS = np.array([-1.04, 0.15, 1.05, 1.90], dtype=float)
PEAK_MEANINGS = [
    (-1.04, "单管/极细管束相，主导高斯特征"),
    (0.15, "小尺寸亚微米软团聚"),
    (1.05, "中等尺寸管束网络，处于半分散状态的架凝结构"),
    (1.90, "大尺寸微米级硬团聚，主导洛伦兹地尾特征"),
]
