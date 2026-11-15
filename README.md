# pdf2md-paper

專門把英文學術論文的 PDF 轉成 Markdown 的引擎，讓 LLM（Claude、Gemini）用比較少的 token 讀論文：內文轉成文字，圖另外切成 PNG。

- 在本機執行：轉檔不用上網，PDF 和輸出都只留在你的電腦裡。
- 只有安裝時要上網，下載 Python 套件和 MinerU 模型。

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

## 動機：省 token
token 是 Claude 計算輸入量的單位，愈少愈省；整份 PDF 直接給 Claude，平均每頁約 2,607 tokens。

下表是 7 份 PDF（論文和自己的報告，共 89 頁）一步步加上每項處理後，.md＋PNG 合計的 tokens：

| 做法 | .md | PNG | 合計 | 佔整份 PDF |
|---|---:|---:|---:|---:|
| 整份 PDF 直接給 | — | — | 232,013 | 100% |
| 轉成 .md＋PNG，全部保留 | 103,836 | 158,002 | 261,838 | 113% |
| ＋刪參考文獻（-ref-wo） | 89,302 | 158,002 | 247,304 | 107% |
| ＋表格只留 Markdown，不附 PNG（-tab-wo） | 88,210 | 115,975 | 204,185 | 88% |
| ＋圖依字級選 dpi（引擎內建，沒有旗標） | 88,210 | 68,255 | 156,465 | 67% |
| ＋公式只留 LaTeX，不附 PNG（-eq-wo），＝現在的預設 | 86,828 | 61,448 | 148,276 | 64% |

- 全部保留時，光 PNG 就有 158,002 tokens，所以比整份 PDF 還多。
- 用現在的預設，7 份各自是原 PDF 的 40%～90%；只讀 .md、不開 PNG 是 37%。
- 圖依字級選 dpi 後，Haiku 抄出圖裡文字的正確率：200 dpi 是 97.6%、300 dpi 是 97.8%；只測過一篇論文的 8 張圖。
- 量法：Anthropic 的 count_tokens API，模型 claude-opus-5-5，用 2026-11-14 的引擎量；之後引擎還有修改，沒有重量。
- 「＋刪參考文獻」那列是分開量的 .md 和 PNG 相加，其餘各列直接量。
- 這些數字只適用 Claude；Gemini 的算法不同，沒有量。

## 技術細節
流程：`pdf2md` → `engine/pdf2md_paper.py` → `engine/mineru_eq.py`（在 MinerU 的虛擬環境裡跑）→ `論文.md`＋`論文-graph/`

### 本 repo 的程式
| 檔案 | 功能 |
|---|---|
| pdf2md | 指令入口：解析旗標，旗標沒給齊時在終端機詢問，再逐檔呼叫主引擎 |
| install.sh | 建 engine/venv（PyMuPDF）和 engine/venv-mineru（MinerU CPU 版），加 --gpu 再建 engine/venv-mineru-gpu；安裝鎖定版本並下載模型 |
| engine/pdf2md_paper.py | 主引擎，做的事見下方 |
| engine/mineru_eq.py | 在 MinerU 的虛擬環境裡跑 MinerU，抽出獨立公式和行內公式的頁碼、位置與 LaTeX，存成 json 交給主引擎 |
| engine/requirements*.txt | 三個虛擬環境的鎖定版本 |

主引擎依序做：
1. 用 PyMuPDF 讀出每一行文字的位置、字級與字型。
2. 依字級與粗體判斷標題層級。
3. 每頁標頁碼、剝掉頁尾，接回跨頁的段落。
4. 表格依直框線切格，轉成 Markdown 表格；Algorithm 框轉成巢狀清單。
5. 圖、表切成 PNG，依圖裡最小的字選 dpi：讓那個字約 14 像素高，限制在 200～300 dpi。
6. 公式交給 MinerU 辨識成 LaTeX：先用 basic tier，有 GPU 版就先用 GPU、失敗改 CPU；LaTeX 沒過檢查就先修補，修不好再用 standard tier 重新辨識。
7. 依旗標刪參考文獻、拿掉表格與公式的 PNG 連結，寫出 .md 和 -graph/。

### 第三方元件
這個 repo 只有本專案自己的程式；下表的第三方元件都不在 repo 裡，由 install.sh 從 PyPI 和 Hugging Face 下載，各自適用自己的授權。

| 元件 | 用途 | 授權 |
|---|---|---|
| [PyMuPDF](https://pymupdf.readthedocs.io/) 1.28.2 | 讀 PDF、切 PNG | AGPL-3.0 或 Artifex 商用授權 |
| [MinerU](https://github.com/opendatalab/MinerU) 4.0.12 | 辨識公式 | MinerU Open Source License（Apache-2.0 加附加條款） |
| MinerU 的相依套件 | MinerU 的執行環境 | 各套件自己的授權；版本見 engine/requirements-mineru.txt |
| [MinerU-4_models_onnx](https://huggingface.co/opendatalab/MinerU-4_models_onnx) | CPU 版的版面、OCR、公式、表格模型 | 模型卡寫 "Original model licenses and attribution remain applicable."；它的 manifest.json 列的上游 repo 都標 apache-2.0 |
| [MinerU-4_models_torch](https://huggingface.co/opendatalab/MinerU-4_models_torch) | GPU 版的同類模型（--gpu） | apache-2.0 |
| [MinerU2.5-Pro-2605-1.2B](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B) 的 [GGUF 版](https://huggingface.co/jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF) | standard tier 重新辨識沒過檢查的公式 | 原模型 apache-2.0；GGUF 版的頁面沒寫授權 |
| torch、NVIDIA CUDA 函式庫（--gpu） | GPU 加速 | torch 是 Apache-2.0、BSD 等寬鬆授權；NVIDIA 函式庫是 NVIDIA 專有授權 |

### 授權
- 本專案的程式以 GNU AGPL-3.0-or-later 授權，全文見 [LICENSE](LICENSE)。Copyright (C) 2026 Ian-1234-Mei
- 本工具使用 MinerU。
- 要把它改成網路服務給別人用，先讀 AGPL-3.0 第 13 條、[Artifex 的授權說明](https://artifex.com/licensing/) 和 MinerU 的 LICENSE.md 第 2 條。

## 聲明
- 這份引擎是用 Claude（Claude Code）vibe coding 寫出來的。
- 轉檔規則只用手邊少量的 PDF 檢驗過，主要是 VLA、強化學習（RL）、醫療影像分割的論文，加上少量自己的報告；其他領域或排版可能轉錯。
- 適用：英文學術論文。不支援：投影片。沒測過：掃描檔、中文論文、Mac。
- 測過的環境：Ubuntu 22.04（WSL2）、Python 3.10。
