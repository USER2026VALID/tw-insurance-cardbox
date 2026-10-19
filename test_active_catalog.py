import unittest

from catalog_sync import is_active_record
from merge_tii_catalog import is_active


class ActiveCatalogTests(unittest.TestCase):
    def test_only_explicit_current_records_are_active(self):
        self.assertTrue(is_active({"sales_status": "現售", "discontinued_date": ""}))
        self.assertTrue(is_active({"sales_status": "現售", "discontinued_date": "未停售"}))
        self.assertFalse(is_active({"sales_status": "停售", "discontinued_date": "114/01/01"}))
        self.assertFalse(is_active({"sales_status": "待確認", "discontinued_date": ""}))
        self.assertFalse(is_active({"sales_status": "暫停銷售", "discontinued_date": ""}))

    def test_frontend_filter_matches_merge_filter(self):
        rows = [
            {"sales_status": "現售", "discontinued_date": ""},
            {"sales_status": "停售", "discontinued_date": "114/01/01"},
            {"sales_status": "現售", "discontinued_date": "未停售"},
        ]
        self.assertEqual([is_active(row) for row in rows], [is_active_record(row) for row in rows])


if __name__ == "__main__":
    unittest.main()
