# 四家公司商品目錄

`catalog.json` 是可審閱、可提交 Git 的正式商品目錄；每筆資料保留官方商品頁、來源頁、險種分類、上市日期、停售日期、狀態與最後確認時間。

`catalog.sqlite3` 是由 `catalog_sync.py` 重建的本地查詢索引，不是唯一來源，也不需要提交到 Git。`change_log.json` 保存每次同步發現的新商品事件。

目前來源限定為：

- 國泰人壽
- 南山人壽
- 富邦人壽
- 中華郵政壽險

同步方式：

```bash
python3 catalog_sync.py sync
python3 catalog_sync.py init-db
```

同步器只從四家公司的官方商品入口發現與更新連結，不掃描保發中心全站，也不會把無法確認的上市日或停售日自行填入。日期可由人工覆核、官方公告或未來的公司專用 adapter 補上。
