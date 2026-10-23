"""以保發中心公開結果頁建立四家公司主資料庫。

TII 是商品母資料來源；官方頁面資料後續只補充分類與官方連結。掃描可分段、可重試、可中斷續跑。
"""
from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tii_full_crawler import PAGE_SIZE, TII_RESULT_URL, REQUEST_TIMEOUT, make_session, parse_result_page, parse_total

ROOT = Path(__file__).resolve().parent
CATALOG_DIR = ROOT / "catalog"
MASTER_FILE = CATALOG_DIR / "tii_master.json"
CHECKPOINT_FILE = CATALOG_DIR / "tii_master_checkpoint.json"
COMPANY_CODES = {"204", "206", "209", "220"}
DEFAULT_START_PAGE = 1
DEFAULT_END_PAGE = 4000
WORKERS = 4
PAGES_PER_BATCH = 10
INNER_WORKERS = 4


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_pages(pages: list[int]) -> tuple[list[dict], list[int], list[int]]:
    session = make_session()
    def fetch_one(page: int) -> tuple[int, list[dict], str | None]:
        try:
            response = session.get(f"{TII_RESULT_URL}?page={page}", timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            rows = [row for row in parse_result_page(response.text) if row.get("company_code") in COMPANY_CODES]
            return page, rows, None
        except Exception as exc:
            return page, [], str(exc)

    found: list[dict] = []
    completed, failed = [], []
    with ThreadPoolExecutor(max_workers=INNER_WORKERS) as executor:
        futures = [executor.submit(fetch_one, page) for page in pages]
        for future in as_completed(futures):
            page, rows, error = future.result()
            if error:
                print(f"[WARN] TII page {page} failed: {error}")
                failed.append(page)
            else:
                found.extend(rows)
                completed.append(page)
    return found, completed, failed


def dedupe(rows: list[dict]) -> list[dict]:
    by_key = {}
    for row in rows:
        key = (row.get("company_code", ""), row.get("product_code") or row.get("source_url", ""))
        if key[1]:
            by_key[key] = row
    return sorted(by_key.values(), key=lambda x: (x.get("company_name", ""), x.get("product_full_name", ""), x.get("product_code", "")))


def sync(start_page: int, end_page: int, workers: int = WORKERS) -> dict:
    master = read_json(MASTER_FILE, [])
    checkpoint = read_json(CHECKPOINT_FILE, {"completed_pages": [], "failed_pages": [], "start_page": start_page, "end_page": end_page})
    completed = set(checkpoint.get("completed_pages", []))
    pages = [p for p in range(start_page, end_page + 1) if p not in completed]
    batches = [pages[i:i + PAGES_PER_BATCH] for i in range(0, len(pages), PAGES_PER_BATCH)]
    all_rows = list(master)
    failed = set(checkpoint.get("failed_pages", []))
    print(f"[*] TII master scan pages {start_page}-{end_page}; pending={len(pages)}; existing={len(master)}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_pages, batch): batch for batch in batches}
        for index, future in enumerate(as_completed(futures), 1):
            rows, done, errors = future.result()
            all_rows.extend(rows)
            completed.update(done)
            failed.update(errors)
            all_rows = dedupe(all_rows)
            write_json(MASTER_FILE, all_rows)
            write_json(CHECKPOINT_FILE, {
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "start_page": start_page, "end_page": end_page,
                "completed_pages": sorted(completed), "failed_pages": sorted(failed),
                "record_count": len(all_rows),
            })
            print(f"  --> batch {index}/{len(batches)}; rows={len(rows)}; master={len(all_rows)}; completed={len(completed)}")
    return {"records": len(all_rows), "completed": len(completed), "failed": len(failed), "pending": end_page - start_page + 1 - len(completed)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sync", nargs="?", choices=["sync"])
    parser.add_argument("--start-page", type=int, default=DEFAULT_START_PAGE)
    parser.add_argument("--end-page", type=int, default=DEFAULT_END_PAGE)
    parser.add_argument("--workers", type=int, default=WORKERS)
    args = parser.parse_args()
    if args.start_page < 1 or args.end_page < args.start_page:
        raise SystemExit("invalid page range")
    print(sync(args.start_page, args.end_page, max(1, min(args.workers, 6))))


if __name__ == "__main__":
    main()
