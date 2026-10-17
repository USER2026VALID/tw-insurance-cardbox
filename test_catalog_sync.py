import unittest

from catalog_sync import merge_records, stable_id


class CatalogSyncTests(unittest.TestCase):
    def test_stable_id_is_repeatable(self):
        self.assertEqual(stable_id("206", "南山人壽測試商品", "https://example.test/p"), stable_id("206", "南山人壽測試商品", "https://example.test/p"))

    def test_merge_preserves_manual_dates_and_adds_new_record(self):
        old = [{
            "product_id": "old-1",
            "company_name": "南山人壽",
            "product_name": "測試商品",
            "official_url": "https://example.test/old",
            "market_date": "2024-01-01",
            "discontinued_date": None,
            "sales_status": "現售",
            "categories": ["壽險"],
        }]
        incoming = [{
            "product_id": "old-1",
            "company_name": "南山人壽",
            "product_name": "測試商品新版名稱",
            "official_url": "https://example.test/old",
            "market_date": None,
            "discontinued_date": None,
            "sales_status": "待確認",
            "categories": ["終身"],
            "last_checked": "2026-10-17T00:00:00+00:00",
            "record_source": "official_company_page",
        }, {
            "product_id": "new-1",
            "company_name": "富邦人壽",
            "product_name": "新商品",
            "official_url": "https://example.test/new",
            "market_date": None,
            "discontinued_date": None,
            "sales_status": "待確認",
            "categories": [],
            "last_checked": "2026-10-17T00:00:00+00:00",
            "record_source": "official_company_page",
        }]
        merged, history = merge_records(old, incoming)
        updated = next(item for item in merged if item["product_id"] == "old-1")
        self.assertEqual(updated["market_date"], "2024-01-01")
        self.assertIn("終身", updated["categories"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["product_id"], "new-1")


if __name__ == "__main__":
    unittest.main()
