# 壽險商品智慧查詢與自動更新系統

透過 **GitHub Actions + Playwright + PyMuPDF 規則引擎 + GitHub Pages**，建立台灣壽險商品條款追蹤與卡片盒檢索系統。

## 功能

- 從保發中心查詢各保險公司的商品資料與條款 PDF 連結。
- 以純 Python 規則引擎分類險種、主附約、保證續保、2-2-7 限制、等待期及投保年齡。
- `index.html` 可直接以 GitHub Pages 或靜態 HTTP 伺服器執行。
- GitHub Actions 可每日排程或手動執行爬蟲、分類、測試與 Pages 部署。
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

完整同步會連線至保發中心，抓取 20 家公司的商品資料，可能需要較長時間：

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

若沒有 `data/products.json`，前端仍會使用 `index.html` 內的示範資料執行。

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

## 注意事項

資料內容僅供商品檢索與研究，實際保障、費率及承保條件應以保險公司最新正式文件為準。
