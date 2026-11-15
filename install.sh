#!/usr/bin/env bash
# Copyright (C) 2026 Ian-1234-Mei
# SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
HERE=$(dirname -- "$(realpath -- "$0")")
gpu=0
for a in "$@"; do
  case "$a" in
    --gpu) gpu=1 ;;
    *) echo "不認得的選項：$a（只有 --gpu）" >&2; exit 1 ;;
  esac
done
py=${PYTHON:-python3}
"$py" -c 'import sys; sys.exit(not (3, 10) <= sys.version_info[:2] < (3, 15))' || { echo "需要 Python 3.10–3.14；可用 PYTHON=<python 路徑> ./install.sh 指定" >&2; exit 1; }
mkvenv() {
  echo "== 建立 engine/$1，安裝 engine/$2" >&2
  "$py" -m venv "$HERE/engine/$1" || { echo "建立虛擬環境失敗；Ubuntu 請先 sudo apt install python3-venv" >&2; exit 1; }
  "$HERE/engine/$1/bin/python" -m pip install -q pip==26.3
  "$HERE/engine/$1/bin/python" -m pip install -r "$HERE/engine/$2"
}
models() {
  echo "== 下載 MinerU 模型（$1）" >&2
  "$HERE/engine/$2/bin/mineru-models-download" --tier standard --small-backend "$1" --vlm-engine llama-cpp
}
mkvenv venv requirements.txt
mkvenv venv-mineru requirements-mineru.txt
models onnx venv-mineru
if [ "$gpu" = 1 ]; then
  mkvenv venv-mineru-gpu requirements-mineru-gpu.txt
  models torch venv-mineru-gpu
fi
echo "安裝完成。用法：$HERE/pdf2md <PDF> -paper-png -ref-wo -tab-wo -eq-wo"
