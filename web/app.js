"use strict";

const state = { filename: "", text: "", result: null };
const colors = ["#9a8cff", "#f2b86b", "#ef7e73", "#71b7ff", "#b8dc72", "#e78fe1", "#5bd0a0", "#f38e5d"];
const $ = (selector) => document.querySelector(selector);
const fileInput = $("#fileInput");
const dropzone = $("#dropzone");
const fitButton = $("#fitButton");
const message = $("#message");

function setMessage(text = "") {
  message.textContent = text;
  message.hidden = !text;
}

function loadText(filename, text) {
  state.filename = filename;
  state.text = text;
  $("#fileLabel").textContent = filename;
  fitButton.disabled = false;
  setMessage();
}

async function readFile(file) {
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) return setMessage("单个文件不能超过 2 MB。");
  loadText(file.name, await file.text());
}

fileInput.addEventListener("change", () => readFile(fileInput.files[0]));
["dragenter", "dragover"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.add("dragging"); }));
["dragleave", "drop"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => { event.preventDefault(); dropzone.classList.remove("dragging"); }));
dropzone.addEventListener("drop", (event) => readFile(event.dataTransfer.files[0]));

$("#sampleButton").addEventListener("click", async () => {
  setMessage();
  try {
    const response = await fetch("api/sample", { cache: "no-store" });
    if (!response.ok) throw new Error("示例数据暂不可用。");
    const sample = await response.json();
    loadText(sample.filename, sample.text);
  } catch (error) { setMessage(error.message); }
});

$("#fixedFour").addEventListener("change", (event) => {
  $("#peakCount").value = event.target.checked ? "4" : $("#peakCount").value;
  $("#peakCount").disabled = event.target.checked;
});

fitButton.addEventListener("click", async () => {
  fitButton.disabled = true;
  fitButton.querySelector("span").textContent = "拟合计算中…";
  setMessage();
  try {
    const response = await fetch("api/fit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: state.filename, text: state.text, axis_mode: $("#axisMode").value, model: $("#model").value, peak_count: Number($("#peakCount").value), use_fixed_four: $("#fixedFour").checked }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "拟合失败。");
    state.result = body;
    renderResult(body);
  } catch (error) { setMessage(error.message); }
  finally { fitButton.disabled = false; fitButton.querySelector("span").textContent = "开始拟合"; }
});

function nice(value, digits = 5) {
  if (value === null || !Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  return magnitude !== 0 && (magnitude >= 10000 || magnitude < 0.001) ? value.toExponential(3) : value.toFixed(digits).replace(/\.?0+$/, "");
}

function renderResult(result) {
  $("#emptyState").hidden = true;
  $("#resultContent").hidden = false;
  $("#exportButton").disabled = false;
  $("#rSquared").textContent = nice(result.r_squared, 6);
  $("#rmse").textContent = nice(result.rmse, 6);
  $("#pointCount").textContent = result.point_count.toLocaleString();
  $("#modelName").textContent = result.model;
  $("#peakRows").innerHTML = result.peaks.map((peak) => `<tr><td>${peak.index}</td><td>${nice(peak.center)}</td><td>${nice(peak.height)}</td><td>${nice(peak.width)}</td><td>${nice(peak.area_ratio, 2)}%</td><td>${escapeHtml(peak.meaning || "—")}</td></tr>`).join("");
  drawChart(result);
}

function escapeHtml(text) { const element = document.createElement("span"); element.textContent = text; return element.innerHTML; }

function drawChart(result) {
  const svg = $("#chart");
  const width = 960, height = 440, left = 68, right = 20, top = 22, bottom = 52;
  const allCurves = [result.raw, result.fit, ...result.components];
  const xs = allCurves.flatMap((curve) => curve.x);
  const ys = allCurves.flatMap((curve) => curve.y).filter(Number.isFinite);
  const xMin = Math.min(...xs), xMax = Math.max(...xs), yMinRaw = Math.min(...ys), yMaxRaw = Math.max(...ys);
  const yPad = Math.max((yMaxRaw - yMinRaw) * 0.08, 1e-9), yMin = yMinRaw - yPad, yMax = yMaxRaw + yPad;
  const sx = (x) => left + (x - xMin) / (xMax - xMin || 1) * (width - left - right);
  const sy = (y) => top + (yMax - y) / (yMax - yMin || 1) * (height - top - bottom);
  const path = (curve) => curve.x.map((x, i) => `${i ? "L" : "M"}${sx(x).toFixed(2)},${sy(curve.y[i]).toFixed(2)}`).join(" ");
  let html = "";
  for (let i = 0; i <= 5; i += 1) {
    const x = left + i / 5 * (width - left - right), xv = xMin + i / 5 * (xMax - xMin);
    const y = top + i / 5 * (height - top - bottom), yv = yMax - i / 5 * (yMax - yMin);
    html += `<line class="chart-grid" x1="${x}" y1="${top}" x2="${x}" y2="${height-bottom}"/><text class="chart-axis" x="${x}" y="${height-24}" text-anchor="middle">${nice(xv,2)}</text>`;
    html += `<line class="chart-grid" x1="${left}" y1="${y}" x2="${width-right}" y2="${y}"/><text class="chart-axis" x="${left-10}" y="${y+4}" text-anchor="end">${nice(yv,2)}</text>`;
  }
  result.components.forEach((curve, index) => { html += `<path class="chart-part" style="stroke:${colors[index % colors.length]}" d="${path(curve)}"/>`; });
  html += `<path class="chart-raw" d="${path(result.raw)}"/><path class="chart-fit" d="${path(result.fit)}"/>`;
  svg.innerHTML = html;
}

$("#exportButton").addEventListener("click", () => {
  if (!state.result) return;
  const rows = [["file", "model", "axis_mode", "r_squared", "rmse"], [state.result.filename, state.result.model, state.result.axis_mode, state.result.r_squared, state.result.rmse], [], ["peak", "center", "height", "width", "area", "area_ratio_pct", "extra", "meaning"]];
  state.result.peaks.forEach((peak) => rows.push([peak.index, peak.center, peak.height, peak.width, peak.area, peak.area_ratio, peak.extra ?? "", peak.meaning]));
  const csv = rows.map((row) => row.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\r\n");
  const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob(["\ufeff", csv], { type: "text/csv" })); link.download = `${state.result.filename.replace(/\.[^.]+$/, "")}-grainpeak.csv`; link.click(); URL.revokeObjectURL(link.href);
});
