import unittest

from catalog_lifecycle import merge_incoming


class CatalogLifecycleTests(unittest.TestCase):
    def item(self, name, **extra):
        value = {
            "product_id": name,
            "company_code": "206",
            "company_name": "南山人壽",
            "product_name": name,
            "official_url": f"https://example.test/{name}",
            "source_url": "https://example.test/index",
            "categories": ["壽險"],
            "market_date": None,
            "discontinued_date": None,
            "sales_status": "現售",
            "last_checked": "old",
            "record_source": "official_company_page",
        }
        value.update(extra)
        return value

    def test_new_product_enters_market_date_queue(self):
        records, diff = merge_incoming([], [self.item("新商品", sales_status="待確認")], "now")
        self.assertEqual(len(diff["new"]), 1)
        self.assertEqual(diff["tii_queue"][0]["reason"], "new_product_market_date")
        self.assertEqual(records[0]["missing_streak"], 0)

    def test_one_missing_is_not_tii_confirmation(self):
        old = [self.item("舊商品", missing_streak=0)]
        records, diff = merge_incoming(old, [], "now")
        self.assertEqual(records[0]["sales_status"], "疑似停售")
        self.assertEqual(diff["tii_queue"], [])

    def test_two_missing_enters_tii_queue(self):
        old = [self.item("舊商品", missing_streak=1)]
        records, diff = merge_incoming(old, [], "now")
        self.assertEqual(records[0]["sales_status"], "待TII確認")
        self.assertEqual(diff["tii_queue"][0]["reason"], "missing_product_discontinued_date")

    def test_returned_product_clears_temporary_missing_state(self):
        old = [self.item("回歸商品", missing_streak=1, sales_status="疑似停售")]
        records, diff = merge_incoming(old, [self.item("回歸商品")], "now")
        self.assertEqual(records[0]["sales_status"], "現售")
        self.assertEqual(len(diff["returned"]), 1)


if __name__ == "__main__":
    unittest.main()
