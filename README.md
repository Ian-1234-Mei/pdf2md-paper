# pdf2md-paper

把英文學術論文的 PDF 轉成給 LLM（Claude、Gemini）讀的 Markdown：內文轉成文字，圖、表、公式另外切成 PNG。

## 適用範圍
- 適用：英文學術論文。
- 不支援：投影片。
- 沒測過：掃描檔、中文論文、Mac。
- 測過的環境：Ubuntu 22.04（WSL2）、Python 3.10。

## 安裝
需要 git 和 Python 3.10 以上。

```bash
git clone https://github.com/Ian-1234-Mei/pdf2md-paper.git
cd pdf2md-paper
./install.sh
```

- install.sh 會在 engine/ 底下建 Python 虛擬環境，再把 MinerU 的模型下載到 ~/.mineru/models。
- 有 NVIDIA GPU 就改跑 `./install.sh --gpu`：多裝一份 GPU 版 MinerU，公式辨識比較快；GPU 版失敗時會自動改用 CPU 版。
- Ubuntu 上建立虛擬環境失敗時，先跑 `sudo apt install python3-venv`。
- 想在任何資料夾都能打 `pdf2md`，自己建連結：`ln -s "$PWD/pdf2md" ~/.local/bin/pdf2md`。

## 使用
```bash
./pdf2md 論文.pdf -paper-png -ref-wo -tab-wo -eq-wo
```

- 輸出放在 PDF 旁邊：`論文.md` 和 `論文-graph/`（PNG）。
- 預設是 `-ref-wo -tab-wo -eq-wo`：刪參考文獻；表格、公式和 Algorithm 只用 .md 的文字呈現，不附 PNG 連結。
- 要保留就改成 `-ref-w`、`-tab-w`、`-eq-w`。
- 旗標沒給齊時會在終端機詢問，按 Enter 就用預設；旗標給齊就不會問。
- 範例 PDF：任一篇 arXiv 論文，例如 https://arxiv.org/abs/1706.03762 （這篇沒有驗證過）。

## token 用量
token 是 Claude 計算輸入量的單位，愈少愈省。

用預設旗標轉 7 份英文論文（共 89 頁），.md＋PNG 合計 148,276 tokens，是直接給整份 PDF（232,013 tokens）的 64%。這是用 2026-11-14 的引擎量的。

## 授權
- 本專案的程式以 GNU AGPL-3.0-or-later 授權，全文見 [LICENSE](LICENSE)。Copyright (C) 2026 Ian-1234-Mei
- 這個 repo 只有本專案自己的程式；下表的第三方元件都不在 repo 裡，由 install.sh 從 PyPI 和 Hugging Face 下載，各自適用自己的授權。

| 元件 | 用途 | 授權 |
|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) 1.28.2 | 讀 PDF、切 PNG | AGPL-3.0 或 Artifex 商用授權 |
| [MinerU](https://github.com/opendatalab/MinerU) 4.0.12 | 辨識公式 | MinerU Open Source License（Apache-2.0 加附加條款） |
| MinerU 的相依套件 | MinerU 的執行環境 | 各套件自己的授權；版本見 engine/requirements-mineru.txt |
| [MinerU-4_models_onnx](https://huggingface.co/opendatalab/MinerU-4_models_onnx) | CPU 版的版面、OCR、公式、表格模型 | 模型卡寫 "Original model licenses and attribution remain applicable."；它的 manifest.json 列的上游 repo 都標 apache-2.0 |
| [MinerU-4_models_torch](https://huggingface.co/opendatalab/MinerU-4_models_torch) | GPU 版的同類模型（--gpu） | apache-2.0 |
| [MinerU2.5-Pro-2605-1.2B](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B) 的 [GGUF 版](https://huggingface.co/jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF) | 重新辨識沒過檢查的公式 | 原模型 apache-2.0；GGUF 版的頁面沒寫授權 |
| torch、NVIDIA CUDA 函式庫（--gpu） | GPU 加速 | torch 是 Apache-2.0、BSD 等寬鬆授權；NVIDIA 函式庫是 NVIDIA 專有授權 |

- 本工具使用 MinerU。
- 要把它改成網路服務給別人用，先讀 AGPL-3.0 第 13 條、[Artifex 的授權說明](https://artifex.com/licensing/) 和 MinerU 的 LICENSE.md 第 2 條。
