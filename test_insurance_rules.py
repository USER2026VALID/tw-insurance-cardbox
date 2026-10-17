import unittest

from batch_extract import classify_by_name_and_text, extract_code_from_name


class InsuranceRuleTests(unittest.TestCase):
    def test_classifies_cancer_rider_and_waiting_period(self):
        result = classify_by_name_and_text(
            "安聯人壽一年定期癌症醫療健康保險附約(CHR2)",
            "本附約生效日起持續有效第九十日以後，經醫師診斷確定初次罹患癌症。",
        )
        self.assertEqual(result["contract_type"], "附約")
        self.assertEqual(result["sales_status"], "現售")
        self.assertIn("癌症險", result["categories"])
        self.assertEqual(result["waiting_days"], 90)
        self.assertIn("附約", result["feature_chips"])

    def test_classifies_medical_reimbursement(self):
        result = classify_by_name_and_text(
            "一年定期住院醫療費用保險附約(HMRA)",
            "住院醫療費用保險金按實際醫療費用給付。",
        )
        self.assertEqual(result["categories"], ["醫療(實支)"])
        self.assertIn("實支實付", result["feature_chips"])

    def test_extracts_product_code_from_full_width_parentheses(self):
        self.assertEqual(
            extract_code_from_name("安心重大傷病保險（NCIC）", ""),
            "NCIC",
        )

    def test_existing_default_code_has_priority(self):
        self.assertEqual(extract_code_from_name("商品（OTHER）", "HMRA"), "HMRA")


if __name__ == "__main__":
    unittest.main()
