"""分析四家公司現售商品分布；主打候選是規則式代理指標，不代表銷售量。"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "products.json"
OUTPUT = ROOT / "data" / "market_summary.json"


def active(row: dict) -> bool:
    return row.get("sales_status") == "現售" and (row.get("discontinued_date") or "") in ("", "未停售")


def prominence_score(row: dict) -> int:
    """可觀測商品欄位的透明 proxy：不是保費、銷量或市場占有率。"""
    return (
        2 if row.get("contract_type") == "主約" else 0
    ) + (
        2 if row.get("is_guaranteed_renewal") else 0
    ) + min(3, len(row.get("categories") or [])) \
        + min(3, len(row.get("coverage_highlights") or [])) \
        + min(2, len(row.get("feature_chips") or []) // 3)


def analyze(rows: list[dict]) -> dict:
    rows = [r for r in rows if active(r)]
    by_company: dict[str, list[dict]] = {}
    for row in rows:
        by_company.setdefault(row.get("company") or "未標示", []).append(row)

    companies = []
    for company, group in sorted(by_company.items(), key=lambda item: (-len(item[1]), item[0])):
        category_counts = Counter(c for row in group for c in (row.get("categories") or []))
        scored = sorted(
            group,
            key=lambda row: (-prominence_score(row), row.get("product_full_name", "")),
        )
        companies.append({
            "company": company,
            "count": len(group),
            "share": round(len(group) / len(rows), 4) if rows else 0,
            "main_contract_count": sum(row.get("contract_type") == "主約" for row in group),
            "rider_count": sum(row.get("contract_type") == "附約" for row in group),
            "top_categories": [
                {"name": name, "count": count, "share": round(count / len(group), 4)}
                for name, count in category_counts.most_common(6)
            ],
            "candidates": [
                {
                    "id": row.get("id"),
                    "name": row.get("product_full_name", ""),
                    "categories": row.get("categories") or [],
                    "contract_type": row.get("contract_type") or "未標示",
                    "score": prominence_score(row),
                }
                for row in scored[:5]
            ],
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "active_count": len(rows),
        "method": {
            "title": "主打候選透明代理指標",
            "description": "資料未包含銷售量、保費收入、搜尋量或市占率，因此不能宣稱熱門排行；分數僅依現有商品欄位找出較適合優先檢視的主約候選。",
            "signals": ["主約 +2", "保證續保 +2", "分類數最多 +3", "保障摘要最多 +3", "特色標籤完整度 +2"],
        },
        "companies": companies,
    }


def main() -> None:
    rows = json.loads(SOURCE.read_text(encoding="utf-8"))
    OUTPUT.write_text(json.dumps(analyze(rows), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 已產生 {OUTPUT}：{len(rows)} 筆輸入，{analyze(rows)['active_count']} 筆現售分析")


if __name__ == "__main__":
    main()
