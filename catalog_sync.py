"""四家壽險公司的官方商品目錄增量同步器。

正式資料源是 catalog/catalog.json；SQLite 是可重建的查詢索引，Notion 可在未來作為人工覆核匯入／匯出端點。
本模組不再掃描保發中心全站，也不會猜測上市日或停售日。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CATALOG_DIR = ROOT / "catalog"
CATALOG_JSON = CATALOG_DIR / "catalog.json"
CATALOG_DB = CATALOG_DIR / "catalog.sqlite3"
USER_AGENT = "insurance-cardbox-catalog/1.0"


@dataclass(frozen=True)
class Source:
    company_code: str
    company_name: str
    official_url: str
    categories: tuple[tuple[str, str], ...]
    kind: str = "official_product_index"


SOURCES = (
    Source(
        "204", "國泰人壽", "https://www.cathaylife.com.tw/official/",
        (("健康醫療險", "https://www.cathaylife.com.tw/cathaylife/products/health-surgery"),
         ("意外傷害險", "https://www.cathaylife.com.tw/cathaylife/products/accident"),
         ("壽險", "https://www.cathaylife.com.tw/cathaylife/products/life-caring"),
         ("投資型保險", "https://www.cathaylife.com.tw/cathaylife/products/investment-va"),
         ("還本/年金型保險", "https://www.cathaylife.com.tw/cathaylife/products/savings-refund")),
    ),
    Source(
        "206", "南山人壽", "https://www.nanshanlife.com.tw/nanshanlife/",
        (("壽險", "https://www.nanshanlife.com.tw/nanshanlife/products-life-caring"),
         ("健康醫療", "https://www.nanshanlife.com.tw/nanshanlife/products-health"),
         ("長期照顧", "https://www.nanshanlife.com.tw/nanshanlife/products-long-term-care"),
         ("還本/增額/年金", "https://www.nanshanlife.com.tw/nanshanlife/products-savings-refund"),
         ("意外傷害", "https://www.nanshanlife.com.tw/nanshanlife/products-accident"),
         ("投資型保險", "https://www.nanshanlife.com.tw/nanshanlife/products-investment")),
    ),
    Source(
        "209", "富邦人壽", "https://www.fubon.com/life/",
        (("壽險保障", "https://www.fubon.com/life/product/personal/life-refund"),
         ("健康醫療", "https://www.fubon.com/life/product/personal/health"),
         ("還本/養老", "https://www.fubon.com/life/product/personal/long-term-saving"),
         ("意外傷害", "https://www.fubon.com/life/product/personal/accident"),
         ("年金保險", "https://www.fubon.com/life/product/personal/annuity-assurance"),
         ("投資型保險", "https://www.fubon.com/life/product/personal/investing")),
    ),
    Source(
        "220", "中華郵政壽險", "https://www.post.gov.tw/post/internet/Insurance/",
        (("壽險保障", "https://www.post.gov.tw/post/internet/Insurance/"),
         ("增額/還本", "https://www.post.gov.tw/post/internet/Insurance/"),
         ("意外傷害", "https://www.post.gov.tw/post/internet/Insurance/"),
         ("醫療保障", "https://www.post.gov.tw/post/internet/Insurance/")),
    ),
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def is_active_record(record: dict) -> bool:
    """網站與匯出只呈現明確現售／未停售商品。"""
    status = (record.get("sales_status") or "").strip()
    discontinued = (record.get("discontinued_date") or "").strip()
    return status == "現售" and discontinued in {"", "未停售"}


def stable_id(company_code: str, name: str, url: str) -> str:
    raw = f"{company_code}|{normalize(name)}|{url}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def is_product_candidate(source: Source, label: str, url: str) -> bool:
    text = f"{label} {url}".lower()
    blocked = ("了解更多", "詳細內容", "服務", "新聞", "活動", "會員", "保單變更", "保險視圖", "客製", "訂製", "人生階段", "規劃", "團體有保", "夢想的家", "查看商品內容", "宣告利率", "說走就走", "個人保險", "銀行保險商品", "網路投保商品", "企業及學生團體", "旅行險")
    if any(word.lower() in text for word in blocked):
        return False
    if source.company_code == "204":
        return len(label) >= 8 and "/cathaylife/products/" in url and url.rstrip("/") not in {u.rstrip("/") for _, u in source.categories}
    if source.company_code == "220":
        return "IP_ID=" in url or "page_type=3" in url
    if source.company_code == "209":
        return "/life/product/" in url
    if source.company_code == "206":
        return "/products-" in url or "/product/" in url
    return True


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=45) as response:
        return response.read().decode("utf-8", "replace")


def extract_links(source: Source, html: str, base_url: str, category: str | None = None) -> list[dict]:
    """從官方 HTML 擷取有意義的商品／分類連結；不將導覽頁當商品。"""
    from html.parser import HTMLParser

    class LinkParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: list[tuple[str, str]] = []
            self.href = ""
            self.parts: list[str] = []
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.href = dict(attrs).get("href", "")
                self.parts = []
        def handle_data(self, data):
            if self.href:
                self.parts.append(data)
        def handle_endtag(self, tag):
            if tag == "a" and self.href:
                self.links.append((normalize(" ".join(self.parts)), urljoin(base_url, self.href)))
                self.href, self.parts = "", []

    parser = LinkParser()
    parser.feed(html)
    category_urls = {url for _, url in source.categories}
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for label, url in parser.links:
        if not label or len(label) < 3 or len(label) > 160:
            continue
        if url.startswith("mailto:") or url.startswith("javascript:"):
            continue
        if not is_product_candidate(source, label, url):
            continue
        if url in category_urls or url.rstrip("/") == source.official_url.rstrip("/"):
            continue
        # 保留商品、商品詳情、保單內容連結；排除客服、新聞、活動與追蹤網址。
        if not any(k in (label + " " + url).lower() for k in ("保險", "保單", "壽險", "醫療", "年金", "傷害", "癌", "長照", "失能", "product", "insurance")):
            continue
        key = (label, url.split("?")[0])
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "product_id": stable_id(source.company_code, label, key[1]),
            "company_code": source.company_code,
            "company_name": source.company_name,
            "product_name": label,
            "official_url": url,
            "source_url": source.official_url,
            "categories": [category] if category else [],
            "market_date": None,
            "discontinued_date": None,
            "sales_status": "待確認",
            "last_checked": now(),
            "record_source": "official_company_page",
        })
    return result


def seed_records() -> list[dict]:
    records: list[dict] = []
    for source in SOURCES:
        try:
            html = fetch(source.official_url)
            found = extract_links(source, html, source.official_url)
            for category, category_url in source.categories:
                try:
                    category_html = fetch(category_url)
                    found.extend(extract_links(source, category_html, category_url, category))
                except Exception as exc:
                    print(f"[WARN] {source.company_name}/{category} 分類頁暫時無法讀取：{exc}", file=sys.stderr)
            # 同一商品可能出現在多個分類頁；合併分類而不是重複建立資料列。
            merged: dict[str, dict] = {}
            for item in found:
                existing = merged.get(item["product_id"])
                if existing:
                    existing["categories"] = sorted(set(existing.get("categories", [])) | set(item.get("categories", [])))
                else:
                    merged[item["product_id"]] = item
            records.extend(merged.values())
        except Exception as exc:
            print(f"[WARN] {source.company_name} 官方頁暫時無法讀取：{exc}", file=sys.stderr)
    return records


def load_catalog() -> list[dict]:
    if not CATALOG_JSON.exists():
        return []
    return json.loads(CATALOG_JSON.read_text(encoding="utf-8"))


def save_catalog(records: Iterable[dict]) -> None:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted((r for r in records if is_active_record(r)), key=lambda x: (x.get("company_name", ""), x.get("product_name", "")))
    CATALOG_JSON.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_records(old: list[dict], incoming: list[dict]) -> tuple[list[dict], list[dict]]:
    by_id = {item["product_id"]: dict(item) for item in old}
    history: list[dict] = []
    for item in incoming:
        previous = by_id.get(item["product_id"])
        if previous:
            # 官方頁只覆蓋可觀測欄位；人工補上的日期與分類不被空值洗掉。
            for field in ("product_name", "official_url", "source_url", "last_checked", "record_source"):
                if item.get(field):
                    previous[field] = item[field]
            if item.get("categories"):
                previous["categories"] = sorted(set(item["categories"]))
            for field in ("market_date", "discontinued_date"):
                if item.get(field) and not previous.get(field):
                    previous[field] = item[field]
            if previous.get("discontinued_date"):
                previous["sales_status"] = "停售"
            elif item.get("sales_status") and previous.get("sales_status") == "待確認":
                previous["sales_status"] = item["sales_status"]
        else:
            by_id[item["product_id"]] = item
            history.append({"at": now(), "product_id": item["product_id"], "event": "discovered", "new": item})
    return list(by_id.values()), history


def init_db() -> None:
    CATALOG_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CATALOG_DB) as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS products (
          product_id TEXT PRIMARY KEY, company_code TEXT NOT NULL, company_name TEXT NOT NULL,
          product_name TEXT NOT NULL, official_url TEXT NOT NULL, source_url TEXT NOT NULL,
          categories_json TEXT NOT NULL, market_date TEXT, discontinued_date TEXT,
          sales_status TEXT NOT NULL, last_checked TEXT NOT NULL, record_source TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, product_id TEXT NOT NULL,
          event TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        """)


def rebuild_db(records: list[dict], history: list[dict], reset_history: bool = True) -> None:
    init_db()
    with sqlite3.connect(CATALOG_DB) as db:
        db.execute("DELETE FROM products")
        if reset_history:
            db.execute("DELETE FROM product_history")
        db.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (r["product_id"], r["company_code"], r["company_name"], r["product_name"], r["official_url"], r["source_url"], json.dumps(r.get("categories", []), ensure_ascii=False), r.get("market_date"), r.get("discontinued_date"), r.get("sales_status", "待確認"), r.get("last_checked", now()), r.get("record_source", "official_company_page")) for r in records
        ])
        db.executemany("INSERT INTO product_history(at, product_id, event, payload_json) VALUES (?, ?, ?, ?)", [(h["at"], h["product_id"], h["event"], json.dumps(h.get("new", {}), ensure_ascii=False)) for h in history])


def sync() -> int:
    old = load_catalog()
    incoming = seed_records()
    if not incoming:
        raise RuntimeError("四家官方來源都未取得商品連結，拒絕覆蓋既有 catalog")
    merged, history = merge_records(old, incoming)
    save_catalog(merged)
    rebuild_db(merged, history)
    (CATALOG_DIR / "change_log.json").write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 官方目錄同步完成：新增 {len(history)} 筆，總目錄 {len(merged)} 筆")
    return len(history)


def export_metadata() -> int:
    records = [r for r in load_catalog() if is_active_record(r)]
    if not records:
        raise RuntimeError("catalog/catalog.json 沒有商品資料")
    target = ROOT / "tii_insurance_data" / "all_products_metadata.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = [{
        "company_code": r["company_code"],
        "company_name": r["company_name"],
        "product_full_name": r["product_name"],
        "product_code": r["product_id"],
        "official_product_code": r.get("official_product_code", ""),
        "approval_date": r.get("market_date") or "",
        "approval_number": "官方商品目錄，待補正式文號",
        "pdf_url": "",
        "source_url": r["official_url"],
        "sales_status": r.get("sales_status", "待確認"),
        "discontinued_date": r.get("discontinued_date"),
        "scraped_at": r.get("last_checked") or now(),
    } for r in records]
    target.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 已輸出 {len(metadata)} 筆 metadata：{target}")
    return len(metadata)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sync", "init-db", "export-metadata"])
    args = parser.parse_args()
    if args.command == "init-db":
        rebuild_db(load_catalog(), [])
        print(f"[OK] SQLite index: {CATALOG_DB}")
    elif args.command == "export-metadata":
        export_metadata()
    else:
        sync()


if __name__ == "__main__":
    main()
