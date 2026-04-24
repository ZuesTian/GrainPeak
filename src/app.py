from __future__ import annotations

import math
import sys
import traceback
from itertools import cycle
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
import numpy as np

from app_constants import APP_TITLE, MAX_FILES
from data_manager import DataManager
from exporters import export_comparison_csv
from fit_engine import FitEngine
from models import DataFile, FitResult

matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
except Exception as exc:  # pragma: no cover
    raise RuntimeError("缺少 matplotlib，请先安装：pip install matplotlib") from exc


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
        self.fit_progress = tk.DoubleVar(value=0.0)
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
        self.progress_bar = ttk.Progressbar(fit_box, variable=self.fit_progress, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(8, 0))

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
        columns = ("file", "index", "center", "height", "width", "area", "area_ratio", "extra", "meaning")
        self.table = ttk.Treeview(table_box, columns=columns, show="headings", height=7)
        headings = {
            "file": "文件",
            "index": "峰",
            "center": "峰位置",
            "height": "峰高",
            "width": "峰宽",
            "area": "面积",
            "area_ratio": "面积比例(%)",
            "extra": "模型参数",
            "meaning": "物理意义",
        }
        widths = {
            "file": 140,
            "index": 45,
            "center": 85,
            "height": 85,
            "width": 85,
            "area": 85,
            "area_ratio": 100,
            "extra": 85,
            "meaning": 320,
        }
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor=tk.CENTER)
        self.table.pack(fill=tk.X)

    def _try_load_default_files(self) -> None:
        defaults = [Path("data/examples/粒度分析1.txt"), Path("data/examples/粒度分析2.txt")]
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
        return DataManager.read_two_column_data(path)

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
        return DataManager.transform(item, self.axis_mode.get())

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
        self.fit_progress.set(0.0)
        self.update_idletasks()
        self._fit_file(item)
        self.fit_progress.set(100.0)
        self._refresh_file_list()
        self._refresh_table()
        self.redraw()

    def fit_visible_files(self) -> None:
        visible_files = [item for item in self.files if item.visible]
        if not visible_files:
            messagebox.showwarning("无法拟合", "没有可见文件。")
            return
        failures: list[str] = []
        self.fit_progress.set(0.0)
        self.update_idletasks()
        total_files = len(visible_files)
        for index, item in enumerate(visible_files, start=1):
            try:
                self.status_text.set(f"正在拟合 {index}/{total_files}：{item.name}")
                self.fit_progress.set((index - 1) / total_files * 100)
                self.update_idletasks()
                self._fit_file(item, show_message=False)
            except Exception as exc:
                failures.append(f"{item.name}: {exc}")
            finally:
                self.fit_progress.set(index / total_files * 100)
                self.update_idletasks()
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
            if self.use_fixed_four.get():
                self.peak_count.set(4)
            peak_count = max(1, int(self.peak_count.get()))
            item.fit_result = FitEngine.fit(x, y, self.model_name.get(), peak_count, self.use_fixed_four.get())
            self.status_text.set(
                f"{item.name} 拟合完成：{item.fit_result.model_name}，R²={item.fit_result.r_squared:.5f}，RMSE={item.fit_result.rmse:.5g}。"
            )
        except Exception as exc:
            traceback.print_exc()
            if show_message:
                messagebox.showerror("拟合失败", f"{item.name}: {exc}")
            else:
                raise

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
                    f"{float(row['area_ratio']):.2f}",
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
        export_comparison_csv(path, self.files, self.axis_mode.get())
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
