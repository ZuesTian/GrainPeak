"use strict";

const MAX_FILES = 6;
const MAX_BYTES = 2 * 1024 * 1024;
const palette = ["#0b7a70", "#7367c4", "#d47a32", "#b54f79", "#3376b8", "#70933d"];
const state = { docs: [], activeId: null, busy: false, drawFrame: 0 };
const $ = (selector) => document.querySelector(selector);
const fileInput = $("#fileInput");
const dropzone = $("#dropzone");

function uid() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function activeDoc() {
  return state.docs.find((doc) => doc.id === state.activeId) || null;
}

function visibleDocs() {
  return state.docs.filter((doc) => doc.visible);
}

function setMessage(text = "", kind = "error") {
  const element = $("#message");
  element.textContent = text;
  element.dataset.kind = kind;
  element.hidden = !text;
}

function nice(value, digits = 5) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const magnitude = Math.abs(number);
  return magnitude !== 0 && (magnitude >= 10000 || magnitude < 0.001)
    ? number.toExponential(3)
    : number.toFixed(digits).replace(/\.?0+$/, "");
}

function escapeHtml(text) {
  const element = document.createElement("span");
  element.textContent = String(text ?? "");
  return element.innerHTML;
}

function parseText(text) {
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const clean = line.trim();
    if (!clean || clean.startsWith("#")) continue;
    const parts = clean.replaceAll(",", " ").replaceAll(";", " ").split(/\s+/);
    if (parts.length < 2) continue;
    const x = Number(parts[0]);
    const y = Number(parts[1]);
    if (Number.isFinite(x) && Number.isFinite(y)) rows.push([x, y]);
  }
  rows.sort((a, b) => a[0] - b[0]);
  const unique = [];
  let lastX;
  for (const row of rows) {
    if (row[0] !== lastX) unique.push(row);
    lastX = row[0];
  }
  if (unique.length < 4) throw new Error("有效的两列数值数据少于 4 行。");
  if (unique.length > 20000) throw new Error("单个文件不能超过 20,000 个数据点。");
  return { x: unique.map((row) => row[0]), y: unique.map((row) => row[1]) };
}

function downsample(curve, maximum = 1500) {
  if (curve.x.length <= maximum) return curve;
  const x = [], y = [];
  const step = (curve.x.length - 1) / (maximum - 1);
  for (let index = 0; index < maximum; index += 1) {
    const source = Math.round(index * step);
    x.push(curve.x[source]);
    y.push(curve.y[source]);
  }
  return { x, y };
}

function transformedPreview(doc) {
  const mode = $("#axisMode").value;
  const x = [], y = [];
  doc.raw.x.forEach((value, index) => {
    if (mode === "linear") {
      x.push(value); y.push(doc.raw.y[index]);
    } else if (value > 0) {
      x.push(mode === "log10" ? Math.log10(value) : Math.log(value));
      y.push(doc.raw.y[index]);
    }
  });
  if (x.length < 4) throw new Error(`${doc.name} 在对数坐标下没有足够的正横坐标。`);
  return downsample({ x, y });
}

function optionsSignature() {
  return [$("#axisMode").value, $("#model").value, $("#fixedFour").checked ? 4 : Number($("#peakCount").value), $("#fixedFour").checked].join("|");
}

function statusFor(doc) {
  if (doc.error) return "错误";
  if (!doc.result) return "待拟合";
  return doc.fitSignature === optionsSignature() ? "已拟合" : "参数已变";
}

function addDocument(filename, text) {
  if (state.docs.length >= MAX_FILES) throw new Error(`最多同时管理 ${MAX_FILES} 个文件。`);
  const raw = parseText(text);
  const doc = { id: uid(), name: filename, text, raw, visible: true, result: null, fitSignature: "", error: "", color: palette[state.docs.length % palette.length] };
  state.docs.push(doc);
  state.activeId = doc.id;
}

async function readFiles(fileList) {
  setMessage();
  const files = [...fileList];
  if (!files.length) return;
  const remaining = MAX_FILES - state.docs.length;
  if (files.length > remaining) setMessage(`只添加前 ${remaining} 个文件；工作台最多同时管理 ${MAX_FILES} 个。`, "warning");
  for (const file of files.slice(0, remaining)) {
    try {
      if (file.size > MAX_BYTES) throw new Error(`${file.name} 超过 2 MB。`);
      addDocument(file.name, await file.text());
    } catch (error) {
      setMessage(error.message);
    }
  }
  fileInput.value = "";
  renderAll();
}

fileInput.addEventListener("change", () => readFiles(fileInput.files));
["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("dragging"); }));
["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.remove("dragging"); }));
dropzone.addEventListener("drop", (event) => readFiles(event.dataTransfer.files));

$("#sampleButton").addEventListener("click", async () => {
  if (state.busy) return;
  setMessage();
  try {
    const response = await fetch("api/samples", { cache: "no-store" });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "示例数据暂不可用。");
    state.docs = [];
    for (const sample of body.files.slice(0, MAX_FILES)) addDocument(sample.filename, sample.text);
    state.activeId = state.docs[0]?.id || null;
    renderAll();
  } catch (error) { setMessage(error.message); }
});

$("#fileList").addEventListener("click", (event) => {
  const row = event.target.closest("[data-id]");
  if (!row) return;
  const id = row.dataset.id;
  if (event.target.closest("[data-remove]")) {
    state.docs = state.docs.filter((doc) => doc.id !== id);
    if (state.activeId === id) state.activeId = state.docs[0]?.id || null;
  } else if (!event.target.matches("input[type=checkbox]")) {
    state.activeId = id;
  }
  renderAll();
});

$("#fileList").addEventListener("change", (event) => {
  if (!event.target.matches("input[type=checkbox]")) return;
  const doc = state.docs.find((item) => item.id === event.target.closest("[data-id]")?.dataset.id);
  if (doc) doc.visible = event.target.checked;
  renderAll();
});

$("#fixedFour").addEventListener("change", () => {
  $("#peakCount").value = $("#fixedFour").checked ? "4" : $("#peakCount").value;
  $("#peakCount").disabled = $("#fixedFour").checked;
  renderAll();
});

$("#axisMode").addEventListener("change", () => {
  for (const doc of state.docs) { doc.error = ""; }
  renderAll();
});
["#model", "#peakCount"].forEach((selector) => $(selector).addEventListener("change", renderAll));
$("#showLabels").addEventListener("change", scheduleDraw);

function requestOptions() {
  return { axis_mode: $("#axisMode").value, model: $("#model").value, peak_count: Number($("#peakCount").value), use_fixed_four: $("#fixedFour").checked };
}

async function fitOne(doc) {
  const response = await fetch("api/fit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...requestOptions(), client_id: doc.id, filename: doc.name, text: doc.text }),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "拟合失败。");
  doc.result = body;
  doc.fitSignature = optionsSignature();
  doc.error = "";
}

function setBusy(busy, text = "") {
  state.busy = busy;
  $("#progressLine").hidden = !busy;
  $("#progressText").textContent = text || "计算中";
  updateButtons();
}

$("#fitActiveButton").addEventListener("click", async () => {
  const doc = activeDoc();
  if (!doc || state.busy) return;
  setMessage(); setBusy(true, `正在拟合 ${doc.name}`);
  try {
    await fitOne(doc);
    setMessage(`${doc.name} 拟合完成。`, "success");
  } catch (error) { doc.error = error.message; setMessage(error.message); }
  finally { setBusy(false); renderAll(); }
});

$("#fitVisibleButton").addEventListener("click", async () => {
  const docs = visibleDocs();
  if (!docs.length || state.busy) return;
  setMessage(); setBusy(true, `正在独立拟合 ${docs.length} 个可见文件`);
  try {
    const response = await fetch("api/batch-fit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...requestOptions(), files: docs.map((doc) => ({ client_id: doc.id, filename: doc.name, text: doc.text })) }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "批量拟合失败。");
    for (const result of body.results) {
      const doc = state.docs.find((item) => item.id === result.client_id);
      if (doc) { doc.result = result; doc.fitSignature = optionsSignature(); doc.error = ""; }
    }
    for (const failure of body.errors) {
      const doc = state.docs.find((item) => item.id === failure.client_id);
      if (doc) doc.error = failure.error;
    }
    const cacheHits = body.results.filter((item) => item.cache_hit).length;
    const note = body.errors.length ? `；${body.errors.length} 个失败` : "";
    setMessage(`完成 ${body.succeeded}/${body.requested} 个文件${note}${cacheHits ? `；${cacheHits} 个命中缓存` : ""}。`, body.errors.length ? "warning" : "success");
  } catch (error) { setMessage(error.message); }
  finally { setBusy(false); renderAll(); }
});

$("#clearFitButton").addEventListener("click", () => {
  const doc = activeDoc();
  if (!doc) return;
  doc.result = null; doc.fitSignature = ""; doc.error = "";
  setMessage(`已清除 ${doc.name} 的拟合结果。`, "success");
  renderAll();
});

function renderFileList() {
  $("#fileCount").textContent = `${state.docs.length} / ${MAX_FILES} FILES`;
  if (!state.docs.length) {
    $("#fileList").innerHTML = '<p class="list-empty">尚未添加数据文件</p>';
    return;
  }
  $("#fileList").innerHTML = state.docs.map((doc) => `
    <div class="file-row ${doc.id === state.activeId ? "active" : ""}" data-id="${doc.id}">
      <label class="visibility" title="显示 / 隐藏"><input type="checkbox" ${doc.visible ? "checked" : ""}/><i style="--file-color:${doc.color}"></i></label>
      <button class="file-select" type="button"><b>${escapeHtml(doc.name)}</b><small class="status-${statusFor(doc)}">${statusFor(doc)} · ${doc.raw.x.length.toLocaleString()} 点</small></button>
      <button class="remove" data-remove type="button" title="移除文件">×</button>
    </div>`).join("");
}

function updateButtons() {
  const doc = activeDoc();
  $("#fitActiveButton").disabled = state.busy || !doc;
  $("#fitVisibleButton").disabled = state.busy || !visibleDocs().length;
  $("#clearFitButton").disabled = state.busy || !doc?.result;
  $("#exportButton").disabled = !state.docs.length || state.busy;
}

function renderResult() {
  const doc = activeDoc();
  $("#emptyState").hidden = Boolean(state.docs.length);
  $("#resultContent").hidden = !state.docs.length;
  $("#activeFileLabel").textContent = doc ? doc.name.toUpperCase() : "NO ACTIVE FILE";
  if (!doc) return;
  const result = doc.result;
  $("#rSquared").textContent = result ? nice(result.r_squared, 6) : "—";
  $("#rmse").textContent = result ? nice(result.rmse, 6) : "—";
  $("#pointCount").textContent = (result?.point_count || doc.raw.x.length).toLocaleString();
  $("#modelName").textContent = result?.model || "RAW PREVIEW";
  $("#axisLabel").textContent = { linear: "粒径 / 坐标", log10: "log10(粒径)", ln: "ln(粒径)" }[$("#axisMode").value];
  $("#tableHint").textContent = result ? `${doc.name} · ${result.peaks.length} PEAKS` : "拟合后显示";
  $("#peakRows").innerHTML = result?.peaks.length
    ? result.peaks.map((peak) => `<tr><td><b>${peak.index}</b></td><td>${nice(peak.center)}</td><td>${nice(peak.height)}</td><td>${nice(peak.width)}</td><td>${nice(peak.area)}</td><td>${nice(peak.area_ratio, 2)}%</td><td>${nice(peak.extra)}</td><td>${escapeHtml(peak.meaning || "—")}</td></tr>`).join("")
    : '<tr><td colspan="8">尚无拟合参数；可先查看原始曲线，再运行拟合。</td></tr>';
  scheduleDraw();
}

function scheduleDraw() {
  cancelAnimationFrame(state.drawFrame);
  state.drawFrame = requestAnimationFrame(drawChart);
}

function drawChart() {
  const svg = $("#chart");
  const docs = visibleDocs();
  const plotted = [];
  for (const doc of docs) {
    try {
      const currentResult = doc.result && doc.result.axis_mode === $("#axisMode").value ? doc.result : null;
      plotted.push({ doc, raw: currentResult?.raw || transformedPreview(doc), result: currentResult });
      doc.error = "";
    } catch (error) { doc.error = error.message; }
  }
  if (!plotted.length) {
    svg.innerHTML = '<text class="chart-empty" x="550" y="245" text-anchor="middle">没有可见曲线</text>';
    $("#chartLegend").innerHTML = "";
    return;
  }
  const W = 1100, H = 500, L = 72, R = 24, T = 25, B = 54;
  let xMin = Infinity, xMax = -Infinity, yMinRaw = Infinity, yMaxRaw = -Infinity;
  for (const item of plotted) {
    const curves = [item.raw, ...(item.result ? [item.result.fit, ...item.result.components] : [])];
    for (const curve of curves) {
      for (const value of curve.x) { if (value < xMin) xMin = value; if (value > xMax) xMax = value; }
      for (const value of curve.y) { if (Number.isFinite(value)) { if (value < yMinRaw) yMinRaw = value; if (value > yMaxRaw) yMaxRaw = value; } }
    }
  }
  const pad = Math.max((yMaxRaw - yMinRaw) * 0.08, 1e-9);
  const yMin = yMinRaw - pad, yMax = yMaxRaw + pad;
  const sx = (x) => L + (x - xMin) / (xMax - xMin || 1) * (W - L - R);
  const sy = (y) => T + (yMax - y) / (yMax - yMin || 1) * (H - T - B);
  const path = (curve) => curve.x.map((x, index) => `${index ? "L" : "M"}${sx(x).toFixed(2)},${sy(curve.y[index]).toFixed(2)}`).join(" ");
  let html = "";
  for (let index = 0; index <= 5; index += 1) {
    const px = L + index / 5 * (W - L - R), xv = xMin + index / 5 * (xMax - xMin);
    const py = T + index / 5 * (H - T - B), yv = yMax - index / 5 * (yMax - yMin);
    html += `<line class="chart-grid" x1="${px}" y1="${T}" x2="${px}" y2="${H-B}"/><text class="chart-axis" x="${px}" y="${H-23}" text-anchor="middle">${nice(xv, 2)}</text>`;
    html += `<line class="chart-grid" x1="${L}" y1="${py}" x2="${W-R}" y2="${py}"/><text class="chart-axis" x="${L-9}" y="${py+4}" text-anchor="end">${nice(yv, 2)}</text>`;
  }
  for (const { doc, raw, result } of plotted) {
    html += `<path class="chart-raw" style="stroke:${doc.color}" d="${path(raw)}"/>`;
    if (!result) continue;
    result.components.forEach((curve) => { html += `<path class="chart-part" style="stroke:${doc.color}" d="${path(curve)}"/>`; });
    html += `<path class="chart-fit" style="stroke:${doc.color}" d="${path(result.fit)}"/>`;
    if ($("#showLabels").checked) {
      result.peaks.forEach((peak, index) => {
        if (!peak.meaning || !Number.isFinite(peak.center) || !Number.isFinite(peak.height)) return;
        const x = sx(peak.center), y = sy(peak.height);
        const offset = 18 + index % 3 * 14;
        html += `<line class="peak-link" style="stroke:${doc.color}" x1="${x}" y1="${y}" x2="${x+5}" y2="${Math.max(T+12, y-offset)}"/><text class="peak-label" style="fill:${doc.color}" x="${x+8}" y="${Math.max(T+10, y-offset)}">${escapeHtml(peak.meaning)}</text>`;
      });
    }
  }
  svg.innerHTML = html;
  $("#chartLegend").innerHTML = plotted.map(({ doc, result }) => `<span style="--file-color:${doc.color}"><i></i>${escapeHtml(doc.name)}${result ? " · 拟合" : " · 原始"}</span>`).join("");
}

function csvCell(value) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

$("#exportButton").addEventListener("click", () => {
  if (!state.docs.length) return;
  const rows = [["axis_mode", $("#axisMode").value], ["file_count", state.docs.length], [], ["RAW_DATA"], ["file", "visible", "x_raw", "y_raw"]];
  for (const doc of state.docs) doc.raw.x.forEach((x, index) => rows.push([doc.name, doc.visible, x, doc.raw.y[index]]));
  rows.push([], ["FIT_SUMMARY"], ["file", "model", "r_squared", "rmse"]);
  for (const doc of state.docs) if (doc.result) rows.push([doc.name, doc.result.model, doc.result.r_squared, doc.result.rmse]);
  rows.push([], ["PEAK_PARAMS"], ["file", "peak", "center", "height", "width", "area", "area_ratio", "extra", "meaning"]);
  for (const doc of state.docs) for (const peak of doc.result?.peaks || []) rows.push([doc.name, peak.index, peak.center, peak.height, peak.width, peak.area, peak.area_ratio, peak.extra, peak.meaning]);
  rows.push([], ["FIT_CURVES"], ["file", "x_fit", "y_fit", "component_index", "component_y"]);
  for (const doc of state.docs) {
    const result = doc.result;
    if (!result) continue;
    result.fit.x.forEach((x, index) => {
      rows.push([doc.name, x, result.fit.y[index], "total", ""]);
      result.components.forEach((component, componentIndex) => rows.push([doc.name, x, "", componentIndex + 1, component.y[index]]));
    });
  }
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" }));
  link.download = "grain_comparison_result.csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 0);
});

function renderAll() {
  renderFileList();
  updateButtons();
  renderResult();
}

renderAll();
