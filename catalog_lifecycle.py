"""官方商品快照生命週期：新商品、持續存在、暫時消失、疑似停售。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from catalog_sync import CATALOG_DIR, SOURCES, is_product_candidate, load_catalog, now, save_catalog, seed_records, rebuild_db

SNAPSHOT_DIR = CATALOG_DIR / "snapshots"
CURRENT_SNAPSHOT = CATALOG_DIR / "official_snapshot.json"
PREVIOUS_SNAPSHOT = CATALOG_DIR / "previous_snapshot.json"
DIFF_FILE = CATALOG_DIR / "latest_diff.json"
QUEUE_FILE = CATALOG_DIR / "change_queue.json"
MISSING_CONFIRMATIONS = 2


def norm(value: str) -> str:
    return "".join((value or "").replace("台", "臺").split()).lower()


def snapshot_key(item: dict) -> tuple[str, str]:
    return item.get("company_code", ""), norm(item.get("product_name", ""))


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_invalid_records(records: list[dict]) -> tuple[list[dict], list[dict]]:
    source_by_code = {source.company_code: source for source in SOURCES}
    valid, removed = [], []
    for record in records:
        source = source_by_code.get(record.get("company_code"))
        if source and not is_product_candidate(source, record.get("product_name", ""), record.get("official_url", "")):
            removed.append(record)
        else:
            valid.append(record)
    return valid, removed


def merge_incoming(existing: list[dict], incoming: list[dict], observed_at: str) -> tuple[list[dict], dict]:
    by_key = {snapshot_key(item): dict(item) for item in existing}
    old_keys = set(by_key)
    incoming_by_key = {snapshot_key(item): item for item in incoming}
    new_items: list[dict] = []
    returned_items: list[dict] = []
    suspected_missing: list[dict] = []
    tii_queue: list[dict] = []

    for key, item in incoming_by_key.items():
        if key not in by_key:
            record = dict(item)
            record.update({
                "discovered_at": observed_at,
                "last_seen_at": observed_at,
                "missing_streak": 0,
                "sales_status": "待確認",
                "date_status": "待補上市日",
                "status_source": "official_company_page",
            })
            by_key[key] = record
            new_items.append(record)
            tii_queue.append({"product_id": record["product_id"], "reason": "new_product_market_date"})
            continue
        record = by_key[key]
        was_missing = int(record.get("missing_streak", 0)) > 0
        record["last_seen_at"] = observed_at
        record["missing_streak"] = 0
        record["last_checked"] = observed_at
        if was_missing:
            returned_items.append(record)
        # 只補新官方可觀測欄位，不清除人工或 TII 日期。
        for field in ("official_url", "source_url", "record_source"):
            if item.get(field):
                record[field] = item[field]
        if item.get("categories"):
            record["categories"] = sorted(set(item["categories"]))
        if record.get("sales_status") in {"疑似停售", "待TII確認"} and record.get("status_source") != "manual":
            record["sales_status"] = "現售"
            record["status_source"] = "official_company_page"

    for key in old_keys - set(incoming_by_key):
        record = by_key[key]
        if record.get("status_source") == "manual" or record.get("sales_status") == "停售":
            continue
        record["missing_streak"] = int(record.get("missing_streak", 0)) + 1
        record["last_checked"] = observed_at
        if record["missing_streak"] >= MISSING_CONFIRMATIONS:
            record["sales_status"] = "待TII確認"
            record["date_status"] = "待補停售日"
            suspected_missing.append(record)
            tii_queue.append({"product_id": record["product_id"], "reason": "missing_product_discontinued_date"})
        else:
            record["sales_status"] = "疑似停售"

    diff = {
        "observed_at": observed_at,
        "new": new_items,
        "returned": returned_items,
        "suspected_missing": suspected_missing,
        "tii_queue": tii_queue,
    }
    return list(by_key.values()), diff


def sync_lifecycle() -> dict:
    incoming = seed_records()
    if not incoming:
        raise RuntimeError("官方來源沒有取得商品，拒絕更新快照與目錄")
    observed_at = now()
    existing, removed_invalid = clean_invalid_records(load_catalog())
    merged, diff = merge_incoming(existing, incoming, observed_at)
    diff["removed_invalid"] = removed_invalid
    if CURRENT_SNAPSHOT.exists():
        CURRENT_SNAPSHOT.replace(PREVIOUS_SNAPSHOT)
    write_json(CURRENT_SNAPSHOT, incoming)
    stamp = observed_at.replace(":", "").replace("+00:00", "Z")
    write_json(SNAPSHOT_DIR / f"official-{stamp}.json", incoming)
    save_catalog(merged)
    rebuild_db(merged, [], reset_history=False)
    write_json(DIFF_FILE, diff)
    write_json(QUEUE_FILE, diff["tii_queue"])
    print(f"[OK] lifecycle sync: new={len(diff['new'])}, returned={len(diff['returned'])}, suspected_missing={len(diff['suspected_missing'])}, tii_queue={len(diff['tii_queue'])}")
    return diff


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["sync"])
    args = parser.parse_args()
    sync_lifecycle()


if __name__ == "__main__":
    main()
