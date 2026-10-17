"""只為商品目錄補查上市／停售日期的保發中心公開結果頁工具。

使用前提：官方公司頁先建立 catalog/catalog.json；本工具只處理仍缺日期的商品，
不把保發中心當成每日全量主資料源。它不繞過驗證碼，只讀取公開 ResultQueryAll.aspx 分頁。
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
import urllib3
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "catalog" / "catalog.json"
CHECKPOINT = ROOT / "catalog" / "tii_date_checkpoint.json"
TII_RESULT_URL = "https://insprod.tii.org.tw/ResultQueryAll.aspx"
PAGE_SIZE = 50
USER_AGENT = "insurance-cardbox-tii-date-enricher/1.0"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def normalize(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", (value or "").replace("台", "臺")).lower()


def session() -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(total=4, connect=4, read=4, status=4, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET", "POST"}),
                  respect_retry_after_header=True)
    s.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=2))
    s.get(TII_RESULT_URL + "?page=1", timeout=45)
    s.post(TII_RESULT_URL + "?page=1", data={"PageCrt": str(PAGE_SIZE)}, timeout=45)
    return s


def parse_total(html: str) -> int:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(r"總共找到\s*([\d,]+)", text)
    return int(m.group(1).replace(",", "")) if m else 0


def extract_dates(cells: list[str]) -> tuple[str, str]:
    date_pattern = re.compile(r"^\d{2,3}/\d{1,2}/\d{1,2}$")
    dates = [cell for cell in cells if date_pattern.match(cell)]
    sale_date = dates[0] if dates else ""
    stop_date = "未停售" if "未停售" in cells else (dates[1] if len(dates) > 1 else "")
    return sale_date, stop_date


def parse_page(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    for link in soup.select('a[href*="DetailList.aspx?productId="]'):
        row = link.find_parent("tr")
        cells = [c.get_text(" ", strip=True) for c in row.find_all("td")] if row else []
        sale_date, stop_date = extract_dates(cells)
        href = link.get("href", "")
        rows.append({
            "name": link.get_text(" ", strip=True),
            "sale_date": sale_date,
            "stop_date": stop_date,
            "tii_url": "https://insprod.tii.org.tw/" + href.lstrip("/"),
        })
    return rows


def missing(records: list[dict]) -> list[dict]:
    return [r for r in records if not r.get("market_date") or (r.get("sales_status") == "停售" and not r.get("discontinued_date"))]


def match_record(item: dict, candidates: list[dict[str, str]]) -> dict[str, str] | None:
    wanted = normalize(item.get("product_name", ""))
    if not wanted:
        return None
    exact = [c for c in candidates if normalize(c["name"]) == wanted]
    if len(exact) == 1:
        return exact[0]
    # 只接受長名稱的單向包含，避免短名稱誤配到其他商品。
    if len(wanted) >= 10:
        contained = [c for c in candidates if wanted in normalize(c["name"]) or normalize(c["name"]) in wanted]
        if len(contained) == 1:
            return contained[0]
    return None


def load_checkpoint() -> dict[str, Any]:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    return {"last_page": 0, "matched": 0, "updated_at": None}


def save_checkpoint(state: dict[str, Any]) -> None:
    CHECKPOINT.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enrich(start_page: int, end_page: int, resume: bool = True) -> tuple[int, int]:
    records = json.loads(CATALOG.read_text(encoding="utf-8"))
    pending = missing(records)
    if not pending:
        print("[OK] 目前沒有缺少日期的目錄資料。")
        return 0, 0
    state = load_checkpoint() if resume else {"last_page": 0, "matched": 0, "updated_at": None}
    start = max(start_page, int(state.get("last_page", 0)) + 1) if resume else start_page
    s = session()
    matched = 0
    changed = 0
    by_id = {r["product_id"]: r for r in pending}
    for page in range(start, end_page + 1):
        try:
            response = s.get(TII_RESULT_URL + f"?page={page}", timeout=45)
            response.raise_for_status()
            rows = parse_page(response.text)
            page_matched = 0
            for row in rows:
                for item in list(by_id.values()):
                    hit = match_record(item, [row])
                    if not hit:
                        continue
                    matched += 1
                    page_matched += 1
                    if not item.get("market_date") and hit.get("sale_date"):
                        item["market_date"] = hit["sale_date"]
                        changed += 1
                    if hit.get("stop_date") and hit["stop_date"] != "未停售":
                        if not item.get("discontinued_date"):
                            item["discontinued_date"] = hit["stop_date"]
                            changed += 1
                        item["sales_status"] = "停售"
                    elif item.get("sales_status") == "待確認":
                        item["sales_status"] = "現售"
                    item["tii_url"] = hit["tii_url"]
                    item["date_source"] = "保發中心公開結果頁"
                    item["last_checked"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    del by_id[item["product_id"]]
                    break
            state.update({"last_page": page, "matched": int(state.get("matched", 0)) + page_matched, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            save_checkpoint(state)
            if page % 25 == 0 or matched:
                print(f"[INFO] page={page}, matched_total={state['matched']}, remaining={len(by_id)}")
            if not by_id:
                break
        except Exception as exc:
            print(f"[WARN] page={page} skipped: {exc}")
            save_checkpoint(state)
    CATALOG.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] TII 日期補查完成：匹配 {matched} 筆，更新 {changed} 個欄位；checkpoint={CHECKPOINT}")
    return matched, changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-page", type=int, required=True)
    parser.add_argument("--end-page", type=int, required=True)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    if args.end_page < args.start_page:
        raise SystemExit("end-page 必須大於或等於 start-page")
    enrich(args.start_page, args.end_page, resume=not args.no_resume)


if __name__ == "__main__":
    main()
