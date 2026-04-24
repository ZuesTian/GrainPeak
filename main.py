from __future__ import annotations

import csv
import math
import sys
import traceback
from dataclasses import dataclass, field
from itertools import cycle
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
import numpy as np

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
except Exception as exc:  # pragma: no cover
    raise RuntimeError("缺少 matplotlib，请先安装：pip install matplotlib") from exc

try:
    from scipy.optimize import curve_fit
except Exception as exc:  # pragma: no cover
    raise RuntimeError("缺少 scipy，请先安装：pip install scipy") from exc


APP_TITLE = "粒度分析分峰软件"
MAX_FILES = 6
FIXED_FOUR_PEAKS = np.array([-1.04, 0.15, 1.05, 1.90], dtype=float)
PEAK_MEANINGS = [
    (-1.04, "单管/极细管束相，主导高斯特征"),
    (0.15, "小尺寸亚微米软团聚"),
    (1.05, "中等尺寸管束网络，处于半分散状态的架凝结构"),
    (1.90, "大尺寸微米级硬团聚，主导洛伦兹地尾特征"),
]


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


class GrainPeakApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1360x860")
        self.minsize(1120, 720)

        self.files: list[DataFile] = []
        self.next_file_id = 1
        self.color_cycle = cycle(["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"])
        self.marker_cycle = cycle(["o", "s", "^", "D", "v", "P"])

        self.axis_mode = tk.StringVar(value="linear")
        self.model_name = tk.StringVar(value="pseudo_voigt")
        self.peak_count = tk.IntVar(value=4)
        self.use_fixed_four = tk.BooleanVar(value=False)
        self.show_peak_labels = tk.BooleanVar(value=True)
        self.status_text = tk.StringVar(value="请选择数据文件。")

        self._build_ui()
        self._try_load_default_files()
        self.after(200, self.show_main_window)

    def show_main_window(self) -> None:
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        self.after(1200, lambda: self.attributes("-topmost", False))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(root, width=360)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)
        right = ttk.Frame(root)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        self._build_controls(left)
        self._build_plot(right)
        self._build_table(right)
        ttk.Label(self, textvariable=self.status_text, anchor=tk.W).pack(fill=tk.X, padx=8, pady=(0, 6))

    def _build_controls(self, parent: ttk.Frame) -> None:
        file_box = ttk.LabelFrame(parent, text="多文件管理", padding=8)
        file_box.pack(fill=tk.X, pady=(0, 8))
        self.file_list = tk.Listbox(file_box, height=8, exportselection=False)
        self.file_list.pack(fill=tk.X)
        self.file_list.bind("<<ListboxSelect>>", lambda _event: self._refresh_table())
        ttk.Button(file_box, text="添加数据文件（最多6个）", command=self.open_files).pack(fill=tk.X, pady=(8, 0))
        ttk.Button(file_box, text="移除选中文件", command=self.remove_selected_file).pack(fill=tk.X, pady=(6, 0))
        ttk.Button(file_box, text="显示/隐藏选中文件", command=self.toggle_selected_file).pack(fill=tk.X, pady=(6, 0))
        ttk.Button(file_box, text="导出对比结果 CSV", command=self.export_result).pack(fill=tk.X, pady=(6, 0))

        axis_box = ttk.LabelFrame(parent, text="横坐标模式", padding=8)
        axis_box.pack(fill=tk.X, pady=(0, 8))
        for text, value in (("正常", "linear"), ("Log10", "log10"), ("Ln", "ln")):
            ttk.Radiobutton(axis_box, text=text, value=value, variable=self.axis_mode, command=self.redraw).pack(anchor=tk.W)

        fit_box = ttk.LabelFrame(parent, text="分峰参数", padding=8)
        fit_box.pack(fill=tk.X, pady=(0, 8))
        model_items = (
            ("伪沃伊特函数", "pseudo_voigt"),
            ("偏斜高斯混合", "skew_normal"),
            ("标准高斯混合", "gaussian"),
        )
        for text, value in model_items:
            ttk.Radiobutton(fit_box, text=text, value=value, variable=self.model_name).pack(anchor=tk.W)
        ttk.Label(fit_box, text="峰数量").pack(anchor=tk.W, pady=(8, 0))
        ttk.Spinbox(fit_box, from_=1, to=12, textvariable=self.peak_count, width=8).pack(anchor=tk.W)
        ttk.Checkbutton(fit_box, text="四峰固定初值（-1.04, 0.15, 1.05, 1.90）", variable=self.use_fixed_four).pack(
            anchor=tk.W, pady=(8, 0)
        )
        ttk.Checkbutton(fit_box, text="显示峰物理意义标注", variable=self.show_peak_labels, command=self.redraw).pack(
            anchor=tk.W, pady=(6, 0)
        )
        ttk.Button(fit_box, text="拟合选中文件", command=self.fit_selected_file).pack(fill=tk.X, pady=(10, 0))
        ttk.Button(fit_box, text="拟合所有可见文件", command=self.fit_visible_files).pack(fill=tk.X, pady=(6, 0))
        ttk.Button(fit_box, text="清除选中文件拟合", command=self.clear_selected_fit).pack(fill=tk.X, pady=(6, 0))

        help_box = ttk.LabelFrame(parent, text="说明", padding=8)
        help_box.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            help_box,
            text=(
                "支持同时加载 2-6 个文件并在同一图表对比。\n\n"
                "拟合按文件独立保存；峰表显示当前选中文件。\n\n"
                "物理意义基于四个特征峰位置自动匹配，建议在 log 坐标数据或 Log10 模式下使用。"
            ),
            justify=tk.LEFT,
            wraplength=320,
        ).pack(anchor=tk.NW)

    def _build_plot(self, parent: ttk.Frame) -> None:
        self.figure = Figure(figsize=(8, 5), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, parent)
        toolbar.update()

    def _build_table(self, parent: ttk.Frame) -> None:
        table_box = ttk.LabelFrame(parent, text="峰参数（当前选中文件）", padding=4)
        table_box.pack(fill=tk.X, pady=(8, 0))
        columns = ("file", "index", "center", "height", "width", "area", "extra", "meaning")
        self.table = ttk.Treeview(table_box, columns=columns, show="headings", height=7)
        headings = {
            "file": "文件",
            "index": "峰",
            "center": "峰位置",
            "height": "峰高",
            "width": "峰宽",
            "area": "面积",
            "extra": "模型参数",
            "meaning": "物理意义",
        }
        widths = {"file": 150, "index": 45, "center": 95, "height": 95, "width": 95, "area": 95, "extra": 95, "meaning": 360}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor=tk.CENTER)
        self.table.pack(fill=tk.X)

    def _try_load_default_files(self) -> None:
        defaults = [Path("粒度分析1.txt"), Path("粒度分析2.txt")]
        existing = [path for path in defaults if path.exists()]
        for path in existing[:MAX_FILES]:
            self.load_file(path, show_errors=False)
        if existing:
            self.status_text.set(f"已默认加载 {len(existing)} 个样例文件。")
        self.redraw()

    def open_files(self) -> None:
        filenames = filedialog.askopenfilenames(
            title="选择粒度分析数据",
            filetypes=(("Text files", "*.txt *.csv *.dat"), ("All files", "*.*")),
        )
        for filename in filenames:
            if len(self.files) >= MAX_FILES:
                messagebox.showwarning("文件数量限制", f"最多只能加载 {MAX_FILES} 个文件。")
                break
            self.load_file(Path(filename))
        self.redraw()

    def load_file(self, path: Path, show_errors: bool = True) -> None:
        if any(item.path.resolve() == path.resolve() for item in self.files):
            return
        try:
            data = self._read_two_column_data(path)
        except Exception as exc:
            if show_errors:
                messagebox.showerror("读取失败", f"{path.name}: {exc}")
            return
        item = DataFile(
            path=path,
            raw_x=data[:, 0],
            raw_y=data[:, 1],
            color=next(self.color_cycle),
            marker=next(self.marker_cycle),
            id=self.next_file_id,
        )
        self.next_file_id += 1
        self.files.append(item)
        self._refresh_file_list()
        self.file_list.selection_clear(0, tk.END)
        self.file_list.selection_set(len(self.files) - 1)
        self.status_text.set(f"已加载：{path.name}，{len(data)} 个数据点。")

    @staticmethod
    def _read_two_column_data(path: Path) -> np.ndarray:
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

    def _refresh_file_list(self) -> None:
        selection = self.file_list.curselection()
        selected_index = selection[0] if selection else None
        self.file_list.delete(0, tk.END)
        for item in self.files:
            status = "显示" if item.visible else "隐藏"
            fit = "已拟合" if item.fit_result else "未拟合"
            self.file_list.insert(tk.END, f"[{status}] [{fit}] {item.name}")
        if selected_index is not None and self.files:
            self.file_list.selection_set(min(selected_index, len(self.files) - 1))

    def selected_file(self) -> DataFile | None:
        selection = self.file_list.curselection()
        if not selection:
            return self.files[0] if self.files else None
        return self.files[selection[0]]

    def remove_selected_file(self) -> None:
        selection = self.file_list.curselection()
        if not selection:
            return
        del self.files[selection[0]]
        self._refresh_file_list()
        if self.files:
            self.file_list.selection_set(min(selection[0], len(self.files) - 1))
        self._refresh_table()
        self.redraw()

    def toggle_selected_file(self) -> None:
        item = self.selected_file()
        if item is None:
            return
        item.visible = not item.visible
        self._refresh_file_list()
        self.redraw()

    def transformed_data(self, item: DataFile) -> tuple[np.ndarray, np.ndarray]:
        x = item.raw_x.astype(float)
        y = item.raw_y.astype(float)
        mode = self.axis_mode.get()
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

    def redraw(self) -> None:
        self.ax.clear()
        visible_files = [item for item in self.files if item.visible]
        if not visible_files:
            self.ax.set_title(APP_TITLE)
            self.ax.set_xlabel(self._axis_label())
            self.ax.set_ylabel("强度 / 体积分数")
            self.ax.grid(True, alpha=0.25)
            self.canvas.draw_idle()
            return
        for item in visible_files:
            try:
                x, y = self.transformed_data(item)
            except Exception as exc:
                self.status_text.set(str(exc))
                continue
            self.ax.plot(x, y, item.marker, color=item.color, markersize=4, alpha=0.72, label=f"{item.name} 数据")
            if item.fit_result is not None:
                fit = item.fit_result
                self.ax.plot(fit.x_fit, fit.y_fit, "-", color=item.color, linewidth=2, label=f"{item.name} 拟合")
                for index, component in enumerate(fit.components, start=1):
                    self.ax.plot(fit.x_fit, component, "--", color=item.color, linewidth=1, alpha=0.55)
                if self.show_peak_labels.get():
                    self._draw_peak_labels(item, fit)
        self.ax.set_title("粒度分析多文件对比")
        self.ax.set_xlabel(self._axis_label())
        self.ax.set_ylabel("强度 / 体积分数")
        self.ax.grid(True, alpha=0.25)
        self.ax.legend(loc="best", fontsize=8)
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _draw_peak_labels(self, item: DataFile, fit: FitResult) -> None:
        for row in fit.peak_table:
            meaning = str(row["meaning"])
            if not meaning:
                continue
            center = float(row["center"])
            height = float(row["height"])
            self.ax.annotate(
                f"峰{int(row['index'])}\n{meaning}",
                xy=(center, height),
                xytext=(4, 14),
                textcoords="offset points",
                fontsize=8,
                color=item.color,
                arrowprops={"arrowstyle": "->", "color": item.color, "lw": 0.8},
                bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": item.color},
            )

    def _axis_label(self) -> str:
        if self.axis_mode.get() == "log10":
            return "log10(粒径)"
        if self.axis_mode.get() == "ln":
            return "ln(粒径)"
        return "粒径 / 坐标"

    def fit_selected_file(self) -> None:
        item = self.selected_file()
        if item is None:
            messagebox.showwarning("无法拟合", "请先加载数据文件。")
            return
        self._fit_file(item)
        self._refresh_file_list()
        self._refresh_table()
        self.redraw()

    def fit_visible_files(self) -> None:
        visible_files = [item for item in self.files if item.visible]
        if not visible_files:
            messagebox.showwarning("无法拟合", "没有可见文件。")
            return
        failures: list[str] = []
        for item in visible_files:
            try:
                self._fit_file(item, show_message=False)
            except Exception as exc:
                failures.append(f"{item.name}: {exc}")
        self._refresh_file_list()
        self._refresh_table()
        self.redraw()
        if failures:
            messagebox.showwarning("部分拟合失败", "\n".join(failures))
        else:
            self.status_text.set(f"已完成 {len(visible_files)} 个可见文件的独立拟合。")

    def _fit_file(self, item: DataFile, show_message: bool = True) -> None:
        try:
            x, y = self.transformed_data(item)
            if len(x) < 8:
                raise ValueError("数据点过少，无法拟合。")
            item.fit_result = self._fit(x, y)
            self.status_text.set(
                f"{item.name} 拟合完成：{item.fit_result.model_name}，R²={item.fit_result.r_squared:.5f}，RMSE={item.fit_result.rmse:.5g}。"
            )
        except Exception as exc:
            traceback.print_exc()
            if show_message:
                messagebox.showerror("拟合失败", f"{item.name}: {exc}")
            else:
                raise

    def _fit(self, x: np.ndarray, y: np.ndarray) -> FitResult:
        model_key = self.model_name.get()
        peak_count = max(1, int(self.peak_count.get()))
        centers = self._initial_centers(x, y, peak_count)
        span = max(float(np.ptp(x)), 1e-6)
        default_width = span / max(len(centers) * 5.0, 8.0)
        baseline = max(float(np.nanmin(y)), 0.0)
        y_work = np.maximum(y - baseline, 0)
        max_y = max(float(np.nanmax(y_work)), 1e-6)

        if model_key == "gaussian":
            func = gaussian_mixture
            model_display = "标准高斯混合"
            param_width = 3
            p0, lower, upper = self._initial_bounds(x, y_work, centers, default_width, max_y, span)
            component_builder = self._gaussian_components
        elif model_key == "skew_normal":
            func = skew_normal_mixture
            model_display = "偏斜高斯混合"
            param_width = 4
            p0, lower, upper = self._initial_bounds(x, y_work, centers, default_width, max_y, span, (0.0, -20.0, 20.0))
            component_builder = self._skew_components
        else:
            func = pseudo_voigt_mixture
            model_display = "伪沃伊特函数"
            param_width = 4
            p0, lower, upper = self._initial_bounds(x, y_work, centers, default_width, max_y, span, (0.5, 0.0, 1.0))
            component_builder = self._pseudo_voigt_components

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
        peak_table = self._build_peak_table(x_fit, components, params, param_width)
        return FitResult(model_display, x_fit, y_fit, components, params, peak_table, r_squared, rmse)

    @staticmethod
    def _initial_bounds(
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

    def _initial_centers(self, x: np.ndarray, y: np.ndarray, peak_count: int) -> np.ndarray:
        if self.use_fixed_four.get():
            self.peak_count.set(4)
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
    def _gaussian_components(x: np.ndarray, params: np.ndarray) -> list[np.ndarray]:
        return [gaussian(x, params[i], params[i + 1], params[i + 2]) for i in range(0, len(params), 3)]

    @staticmethod
    def _pseudo_voigt_components(x: np.ndarray, params: np.ndarray) -> list[np.ndarray]:
        return [pseudo_voigt(x, params[i], params[i + 1], params[i + 2], params[i + 3]) for i in range(0, len(params), 4)]

    @staticmethod
    def _skew_components(x: np.ndarray, params: np.ndarray) -> list[np.ndarray]:
        return [skew_normal_peak(x, params[i], params[i + 1], params[i + 2], params[i + 3]) for i in range(0, len(params), 4)]

    @staticmethod
    def _build_peak_table(
        x_fit: np.ndarray,
        components: list[np.ndarray],
        params: np.ndarray,
        param_width: int,
    ) -> list[dict[str, float | str]]:
        table: list[dict[str, float | str]] = []
        for index, component in enumerate(components):
            peak_index = int(np.argmax(component))
            group = params[index * param_width : (index + 1) * param_width]
            center = float(x_fit[peak_index])
            extra = group[3] if len(group) > 3 else float("nan")
            table.append(
                {
                    "index": float(index + 1),
                    "center": center,
                    "height": float(component[peak_index]),
                    "width": float(abs(group[2])),
                    "area": float(np.trapezoid(component, x_fit)),
                    "extra": float(extra),
                    "meaning": peak_meaning(center),
                }
            )
        return table

    def _refresh_table(self) -> None:
        for row_id in self.table.get_children():
            self.table.delete(row_id)
        item = self.selected_file()
        if item is None or item.fit_result is None:
            return
        for row in item.fit_result.peak_table:
            extra = "" if math.isnan(float(row["extra"])) else f"{float(row['extra']):.6g}"
            self.table.insert(
                "",
                tk.END,
                values=(
                    item.name,
                    int(float(row["index"])),
                    f"{float(row['center']):.8g}",
                    f"{float(row['height']):.8g}",
                    f"{float(row['width']):.8g}",
                    f"{float(row['area']):.8g}",
                    extra,
                    str(row["meaning"]),
                ),
            )

    def clear_selected_fit(self) -> None:
        item = self.selected_file()
        if item is None:
            return
        item.fit_result = None
        self._refresh_file_list()
        self._refresh_table()
        self.status_text.set(f"已清除 {item.name} 的拟合结果。")
        self.redraw()

    def export_result(self) -> None:
        if not self.files:
            messagebox.showwarning("无法导出", "请先加载数据。")
            return
        filename = filedialog.asksaveasfilename(
            title="导出对比结果",
            defaultextension=".csv",
            initialfile="grain_comparison_result.csv",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not filename:
            return
        path = Path(filename)
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["axis_mode", self.axis_mode.get()])
            writer.writerow(["file_count", len(self.files)])
            writer.writerow([])
            writer.writerow(["RAW_DATA"])
            writer.writerow(["file", "visible", "x_raw", "y_raw"])
            for item in self.files:
                for x_value, y_value in zip(item.raw_x, item.raw_y, strict=False):
                    writer.writerow([item.name, item.visible, x_value, y_value])
            writer.writerow([])
            writer.writerow(["FIT_SUMMARY"])
            writer.writerow(["file", "model", "r_squared", "rmse"])
            for item in self.files:
                if item.fit_result:
                    writer.writerow([item.name, item.fit_result.model_name, item.fit_result.r_squared, item.fit_result.rmse])
            writer.writerow([])
            writer.writerow(["PEAK_PARAMS"])
            writer.writerow(["file", "peak", "center", "height", "width", "area", "extra", "meaning"])
            for item in self.files:
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
                            row["extra"],
                            row["meaning"],
                        ]
                    )
            writer.writerow([])
            writer.writerow(["FIT_CURVES"])
            writer.writerow(["file", "x_fit", "y_fit", "component_index", "component_y"])
            for item in self.files:
                if not item.fit_result:
                    continue
                fit = item.fit_result
                for point_index, x_value in enumerate(fit.x_fit):
                    writer.writerow([item.name, x_value, fit.y_fit[point_index], "total", ""])
                    for component_index, component in enumerate(fit.components, start=1):
                        writer.writerow([item.name, x_value, "", component_index, component[point_index]])
        self.status_text.set(f"已导出：{path}")


def install_exception_hook() -> None:
    def show_exception(exc_type, exc_value, exc_traceback) -> None:
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(message, file=sys.stderr)
        try:
            messagebox.showerror("程序错误", str(exc_value))
        except Exception:
            pass

    sys.excepthook = show_exception


if __name__ == "__main__":
    install_exception_hook()
    app = GrainPeakApp()
    app.mainloop()
