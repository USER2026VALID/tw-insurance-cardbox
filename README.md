# 壽險商品智慧查詢與自動更新系統

透過 **GitHub Actions + Playwright + PyMuPDF 規則引擎 + GitHub Pages**，建立台灣壽險商品條款追蹤與卡片盒檢索系統。

## 功能

- 目前先聚焦保經通常無法代銷的四家單一通路／大型壽險公司：國泰人壽、南山人壽、富邦人壽、中華郵政壽險。
- 從保發中心公開的商品結果頁查詢上述公司的商品名稱、銷售日、停售狀態與明細頁連結。
- 依壽險公會目前名錄支援 20 家公司，包含臺銀、台灣、保誠、國泰、凱基、南山、新光、富邦、三商美邦、遠雄、宏泰、安聯、中華郵政、全球、元大、第一金、合作金庫、安達，以及友邦與法國巴黎兩家外商分公司。
- 以純 Python 規則引擎分類險種、主附約、保證續保、2-2-7 限制、等待期及投保年齡。
- 分類規則涵蓋壽險、重大傷病、癌症、實支／定額醫療、意外、長照失能、年金、投資型及儲蓄型商品。
- `index.html` 可直接以 GitHub Pages 或靜態 HTTP 伺服器執行。
- GitHub Actions 可每日排程或手動執行爬蟲、分類、測試與 Pages 部署；若抓取或分類結果為空，流程會停止並保留上一版網站資料。
- Python 腳本的輸入輸出路徑以腳本所在目錄為基準，不受目前 shell 工作目錄影響。

## 本地安裝

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
playwright install chromium
```

若只要執行規則分類測試，不需要啟動瀏覽器：

```bash
python -m unittest discover -v
python -m py_compile batch_extract.py tii_full_crawler.py
```

## 執行資料同步

完整同步會連線至保發中心公開結果頁，掃描並只保留上述四家公司的商品資料，可能需要較長時間：

```bash
python tii_full_crawler.py
python batch_extract.py
mkdir -p data
cp tii_insurance_data/structured_products_final.json data/products.json
```

產物位置：

- `tii_insurance_data/all_products_metadata.json`：爬蟲原始商品 metadata
- `tii_insurance_data/structured_products_final.json`：規則引擎輸出的卡片資料
- `data/products.json`：前端優先載入的資料檔

若以 `file://` 開啟前端，會使用內嵌示範資料；在 GitHub Pages 或 HTTP 伺服器上，前端會優先載入 `data/products.json`，並以空資料顯示「目前沒有可用的同步商品資料」，不會把過期統計誤當成最新資料。

## 啟動前端

不要直接以 `file://` 開啟，因為瀏覽器會限制 JSON 載入；請使用 HTTP 伺服器：

```bash
python3 -m http.server 8000 --bind 0.0.0.0
```

然後開啟 <http://localhost:8000>。

## GitHub Actions

工作流程位於 `.github/workflows/daily_crawler.yml`，支援：

- 每日 UTC 18:00 排程執行
- GitHub Actions 介面手動執行
- 執行單元測試與 Python 編譯檢查
- 產生前端資料並部署 GitHub Pages
- 有資料變更時自動提交更新的 JSON metadata

首次使用 GitHub Pages 時，請在 repository 的 **Settings → Pages** 將來源設為 **GitHub Actions**。

公司名單參考中華民國人壽保險商業同業公會會員名錄（20 家）及保險事業發展中心國內壽險公司名單；公司代碼由保發中心查詢頁面實際下拉選項決定，爬蟲會優先以公司別名匹配，避免名稱差異造成漏抓。

## 注意事項

資料內容僅供商品檢索與研究，實際保障、費率及承保條件應以保險公司最新正式文件為準。
