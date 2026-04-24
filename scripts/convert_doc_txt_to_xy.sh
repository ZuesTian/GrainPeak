#!/usr/bin/env bash
set -euo pipefail

input_dir="${1:-.}"
output_dir="${2:-converted}"
mkdir -p "$output_dir"

if [[ ! -d "$input_dir" ]]; then
  echo "Input directory not found: $input_dir" >&2
  exit 1
fi

shopt -s nullglob
files=("$input_dir"/*)

if (( ${#files[@]} == 0 )); then
  echo "No files found in $input_dir" >&2
  exit 1
fi

for input_file in "${files[@]}"; do
  if [[ ! -f "$input_file" ]]; then
    continue
  fi

  base_name="$(basename "$input_file")"
  output_file="$output_dir/${base_name%.*}_xy.txt"

  python - "$input_file" "$output_file" <<'PY'
import csv
import sys
from pathlib import Path

input_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])

text = None
for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030", "big5", "latin1"):
    try:
        text = input_path.read_text(encoding=encoding)
        break
    except UnicodeDecodeError:
        pass
if text is None:
    text = input_path.read_text(errors="ignore")

rows = list(csv.reader(text.splitlines(), delimiter="\t"))
if len(rows) < 2:
    raise SystemExit(f"{input_path}: not enough rows")

best_xy = []
for row_index in range(len(rows) - 1):
    header_values = rows[row_index]
    data_values = rows[row_index + 1]
    xy = []

    for index, value in enumerate(header_values):
        value = value.strip().strip('"')
        try:
            x = float(value)
        except ValueError:
            continue
        if index >= len(data_values):
            continue
        y_text = data_values[index].strip().strip('"')
        try:
            y = float(y_text)
        except ValueError:
            continue
        xy.append((x, y))

    if len(xy) > len(best_xy):
        best_xy = xy

if not best_xy:
    raise SystemExit(f"{input_path}: no numeric x/y data found")

with output_path.open("w", encoding="utf-8", newline="\n") as handle:
    handle.write("# x_um\ty\n")
    for x, y in best_xy:
        handle.write(f"{x:.10g}\t{y:.10g}\n")

print(f"Converted {input_path} -> {output_path} ({len(best_xy)} points)")
PY
done
