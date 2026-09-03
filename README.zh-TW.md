# Data to SVG

一個開源 Codex skill，將使用者提供的數值資料轉成正確、可讀的本機 SVG 圖表。

範圍刻意保持單純：

- 資料只來自使用者訊息或本機檔案。
- SVG renderer 除 Python 外沒有 runtime 依賴，輸出可重現。
- 若本機有 `rsvg-convert`，可選擇另外輸出本機 PNG。
- 不搜尋資料、不猜缺值、不做上傳、不碰資料庫，也不發布內容。

## 支援圖表

- 單系列長條圖
- 群組長條圖
- 適合排行與長標籤的水平長條圖
- 可明確保留缺值斷點的多系列折線圖
- 可分組的 x/y 散點圖
- 中心值／下界／上界區間圖
- 可顯示 `N/A` 的同單位數值熱圖

Renderer 會驗證類別和值是否對齊、數字是否有限、系列名稱是否唯一、區間順序、座標範圍、文字是否安全 escape，以及長條圖是否保留零基線。它刻意不支援容易誤導的雙 y 軸，也不會默默計算趨勢、信賴區間、百分比、平均或排名。

這批能力來自對 EasyVibeCoding 已發布策展的唯讀稽核：263 篇策展、637 個圖表媒體。各種資料形狀的實際數量與取捨見[策展資料形狀研究](CORPUS_STUDY.md)。

## 安裝

```bash
git clone https://github.com/easyvibecoding/data-to-svg.git
mkdir -p ~/.codex/skills
cp -R data-to-svg/skills/data-to-svg ~/.codex/skills/
```

重新啟動 Codex 後即可探索到這個 skill。

## 在 Codex 使用

```text
使用 $data-to-svg 把以下資料畫成群組長條圖：
Engine A：prefill 5749.9、decode 186.6
Engine B：prefill 4737.5、decode 140.9
單位：tokens per second
```

Codex 會把你提供的數值整理成 JSON 規格、執行本機 renderer、實際檢查產物，再回傳本機檔案。

## 直接使用 renderer

```bash
python3 skills/data-to-svg/scripts/render_chart.py \
  skills/data-to-svg/examples/grouped-bar.json \
  --output chart.svg
```

選擇性輸出本機 PNG：

```bash
python3 skills/data-to-svg/scripts/render_chart.py \
  skills/data-to-svg/examples/grouped-bar.json \
  --output chart.svg \
  --png chart.png
```

所有欄位與正確性規則見[資料規格](skills/data-to-svg/references/spec.md)。

另有[散點圖](skills/data-to-svg/examples/scatter.json)、[區間圖](skills/data-to-svg/examples/interval.json)、[熱圖](skills/data-to-svg/examples/heatmap.json)、[水平長條圖](skills/data-to-svg/examples/horizontal-bar.json)與[含缺值折線圖](skills/data-to-svg/examples/line-missing.json)範例。

## 驗證

```bash
python3 -m unittest discover -s tests -v
python3 tests/validate_package.py
```

## 來源

這個專案把 EasyVibeCoding 私有編輯流程中「用程式精準繪製資料圖」的方法抽成通用版本。公開 renderer 與中性視覺系統為本 repo 重新撰寫；不包含私有品牌、資料庫、物件儲存上傳、快取刷新或發布程式，也沒有綑綁第三方原始碼。

## 授權

[MIT](LICENSE) © 2026 EasyVibeCoding。
