import unittest

from tii_date_enricher import match_record, normalize


class TiiDateEnricherTests(unittest.TestCase):
    def test_normalize_handles_spacing_and_traditional_variant(self):
        self.assertEqual(normalize("台灣 人壽"), normalize("臺灣人壽"))

    def test_exact_match_is_preferred(self):
        item = {"product_name": "南山人壽安心終身壽險"}
        rows = [
            {"name": "南山人壽安心終身壽險", "sale_date": "113/01/01", "stop_date": "未停售", "tii_url": "https://tii/a"},
            {"name": "南山人壽安心終身壽險(第2次變更)", "sale_date": "114/01/01", "stop_date": "未停售", "tii_url": "https://tii/b"},
        ]
        self.assertEqual(match_record(item, rows)["tii_url"], "https://tii/a")

    def test_short_name_does_not_fuzzy_match(self):
        item = {"product_name": "安心"}
        rows = [{"name": "國泰人壽安心終身壽險", "sale_date": "113/01/01", "stop_date": "未停售", "tii_url": "https://tii/a"}]
        self.assertIsNone(match_record(item, rows))


if __name__ == "__main__":
    unittest.main()
