"""將 TII 主資料轉成正式 catalog，並保留可匹配的官方補充欄位。"""
from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path

from catalog_sync import CATALOG_DIR, load_catalog, now, rebuild_db, save_catalog

MASTER = CATALOG_DIR / "tii_master.json"
POSTAL_CANDIDATES = CATALOG_DIR / "post_undiscontinued_candidates.json"


def is_active(row: dict) -> bool:
    """主目錄只收錄明確未停售商品；未知狀態不冒充現售。"""
    status = (row.get("sales_status") or "").strip()
    stop_date = (row.get("discontinued_date") or "").strip()
    return status == "現售" and stop_date in {"", "未停售"}


def norm(value: str) -> str:
    value = (value or "").replace("臺", "台")
    value = re.sub(r"南山人壽|國泰人壽|富邦人壽|中華郵政股份有限公司|中華郵政壽險", "", value)
    return re.sub(r"[^0-9a-zA-Z一-龥]", "", value).lower()


def merge() -> int:
    master = json.loads(MASTER.read_text(encoding="utf-8"))
    official = load_catalog()
    by_name = {}
    for row in official:
        by_name.setdefault((row.get("company_code", ""), norm(row.get("product_name", ""))), []).append(row)
    result = []
    matched = 0
    for row in master:
        if not is_active(row):
            continue
        candidates = by_name.get((row.get("company_code", ""), norm(row.get("product_full_name", ""))), [])
        supplement = candidates[0] if candidates else {}
        if supplement:
            matched += 1
        result.append({
            "product_id": f"tii-{row['company_code']}-{row.get('product_code') or hashlib.sha256(row['source_url'].encode()).hexdigest()[:20]}",
            "company_code": row["company_code"],
            "company_name": row["company_name"],
            "product_name": row["product_full_name"],
            "official_url": supplement.get("official_url") or row["source_url"],
            "source_url": supplement.get("source_url") or "https://insprod.tii.org.tw/",
            "categories": supplement.get("categories", []),
            "market_date": row.get("approval_date") or supplement.get("market_date"),
            "discontinued_date": row.get("discontinued_date") or supplement.get("discontinued_date"),
            "sales_status": "停售" if row.get("discontinued_date") else ("現售" if row.get("sales_status") == "現售" else row.get("sales_status", "待確認")),
            "last_checked": now(),
            "record_source": "tii_primary_with_official_supplement",
            "tii_url": row["source_url"],
            "official_match": bool(supplement),
        })

    # 圖片／人工核對的中華郵政現售商品先進入可查詢主目錄，
    # 但保留待補 TII 編號的來源標記，不自行生成 TII 編號。
    if POSTAL_CANDIDATES.exists():
        for row in json.loads(POSTAL_CANDIDATES.read_text(encoding="utf-8")):
            name = row.get("product_full_name", "")
            product_id = "postal-evidence-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:20]
            result.append({
                "product_id": product_id,
                "company_code": "220",
                "company_name": "中華郵政壽險",
                "product_name": name,
                "official_url": "",
                "source_url": "IMG_1173.PNG",
                "categories": [],
                "market_date": row.get("sales_date"),
                "discontinued_date": "未停售",
                "sales_status": "現售",
                "last_checked": now(),
                "record_source": "user_evidence_pending_tii",
                "tii_url": "",
                "official_match": False,
            })
    save_catalog(result)
    rebuild_db(result, [], reset_history=False)
    print(f"[OK] TII master merged: {len(result)} records; official supplements matched={matched}")
    return len(result)


if __name__ == "__main__":
    merge()
