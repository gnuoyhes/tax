import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tax_calculator.py"


def provenance(article="테스트 조문"):
    return {
        "effective_from": "2026-01-01",
        "effective_to": None,
        "verified_on": "2026-11-03",
        "source": {
            "authority": "테스트 공식기관",
            "law_or_guidance": "테스트 법령",
            "article": article,
            "url": "https://official.example.test/law",
        },
    }


def legal_parameters():
    return {
        "schema_version": "1.0",
        "parameter_set_id": "SYNTHETIC-2026-01",
        "tax_type": "gift_tax",
        "currency": "KRW",
        "rate_schedule": {
            **provenance("세율표"),
            "brackets": [
                {"up_to": 100, "rate": "0.10", "quick_deduction": 0},
                {"up_to": 200, "rate": "0.20", "quick_deduction": 10},
                {"up_to": None, "rate": "0.30", "quick_deduction": 30},
            ],
        },
        "deduction_rules": {
            "basic": {**provenance("공제"), "limit": 50}
        },
        "adjustment_rules": {
            "filing_credit": {
                **provenance("신고공제"),
                "category": "credit",
                "method": "rate",
                "value": "0.10",
                "base": "gross_tax",
            },
            "late_penalty": {
                **provenance("가산세"),
                "category": "penalty",
                "method": "fixed",
                "value": 5,
                "base": None,
            },
        },
    }


def case_input():
    return {
        "schema_version": "1.0",
        "case_id": "GIFT-TEST-001",
        "tax_point_date": "2026-06-30",
        "tax_type": "gift_tax",
        "currency": "KRW",
        "amount_unit": "KRW",
        "gross_assets": [{"id": "asset-1", "amount": 250}],
        "additions": [],
        "liabilities": [],
        "exclusions": [],
        "deductions": [{"rule_id": "basic", "amount": 50}],
        "adjustments": [{"rule_id": "filing_credit"}],
        "other_taxes": [
            {"tax_type": "acquisition_tax", "amount": 7, "status": "illustrative"}
        ],
    }


class CalculatorCliTests(unittest.TestCase):
    def run_calculator(self, case=None, params=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            case_path = tmp_path / "case.json"
            params_path = tmp_path / "params.json"
            case_path.write_text(
                json.dumps(case or case_input(), ensure_ascii=False), encoding="utf-8"
            )
            params_path.write_text(
                json.dumps(params or legal_parameters(), ensure_ascii=False),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--case",
                    str(case_path),
                    "--params",
                    str(params_path),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            return result

    def assert_error(self, result, code):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stderr)
        self.assertEqual(payload["error_code"], code)

    def test_progressive_and_quick_deduction_methods_match(self):
        result = self.run_calculator()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["taxable_base"], 200)
        self.assertEqual(payload["gross_tax"], 30)
        self.assertEqual(payload["method_check"]["progressive"], 30)
        self.assertEqual(payload["method_check"]["quick_deduction"], 30)
        self.assertTrue(payload["method_check"]["matches"])
        self.assertEqual(payload["primary_tax_total"], 27)

    def test_other_taxes_are_reported_separately(self):
        result = self.run_calculator()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["primary_tax_total"], 27)
        self.assertEqual(payload["other_taxes_total"], 7)
        self.assertEqual(payload["other_taxes"][0]["tax_type"], "acquisition_tax")

    def test_negative_taxable_base_is_clamped_and_warned(self):
        case = case_input()
        case["gross_assets"][0]["amount"] = 20
        case["adjustments"] = []
        result = self.run_calculator(case=case)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["taxable_base"], 0)
        self.assertIn("taxable_base_clamped_to_zero", payload["warnings"])

    def test_missing_case_id_is_rejected(self):
        case = case_input()
        del case["case_id"]
        self.assert_error(self.run_calculator(case=case), "missing_required_field")

    def test_non_krw_unit_is_rejected(self):
        case = case_input()
        case["amount_unit"] = "만원"
        self.assert_error(self.run_calculator(case=case), "unit_mismatch")

    def test_duplicate_deduction_is_rejected(self):
        case = case_input()
        case["deductions"].append({"rule_id": "basic", "amount": 10})
        self.assert_error(self.run_calculator(case=case), "duplicate_deduction")

    def test_deduction_over_legal_limit_is_rejected(self):
        case = case_input()
        case["deductions"][0]["amount"] = 51
        self.assert_error(self.run_calculator(case=case), "deduction_limit_exceeded")

    def test_missing_parameter_provenance_is_rejected(self):
        params = legal_parameters()
        del params["deduction_rules"]["basic"]["verified_on"]
        self.assert_error(
            self.run_calculator(params=params), "missing_parameter_provenance"
        )

    def test_parameter_effective_date_must_cover_tax_point(self):
        params = legal_parameters()
        params["rate_schedule"]["effective_from"] = "2027-01-01"
        self.assert_error(self.run_calculator(params=params), "parameter_not_effective")

    def test_inconsistent_quick_deduction_is_rejected(self):
        params = legal_parameters()
        params["rate_schedule"]["brackets"][1]["quick_deduction"] = 9
        self.assert_error(
            self.run_calculator(params=params), "rate_schedule_inconsistent"
        )

    def test_tax_type_mismatch_is_rejected(self):
        case = case_input()
        case["tax_type"] = "inheritance_tax"
        self.assert_error(self.run_calculator(case=case), "tax_type_mismatch")

    def test_unsupported_case_schema_version_is_rejected(self):
        case = case_input()
        case["schema_version"] = "2.0"
        self.assert_error(
            self.run_calculator(case=case), "unsupported_schema_version"
        )

    def test_unsupported_parameter_schema_version_is_rejected(self):
        params = legal_parameters()
        params["schema_version"] = "2.0"
        self.assert_error(
            self.run_calculator(params=params), "unsupported_schema_version"
        )

    def test_unsupported_tax_type_is_rejected(self):
        case = case_input()
        params = legal_parameters()
        case["tax_type"] = "income_tax"
        params["tax_type"] = "income_tax"
        self.assert_error(self.run_calculator(case=case, params=params), "unsupported_tax_type")

    def test_inheritance_tax_uses_the_same_provenance_gates(self):
        case = case_input()
        params = legal_parameters()
        case["case_id"] = "ESTATE-TEST-001"
        case["tax_type"] = "inheritance_tax"
        params["tax_type"] = "inheritance_tax"
        result = self.run_calculator(case=case, params=params)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["tax_type"], "inheritance_tax")
        self.assertEqual(payload["primary_tax_total"], 27)

    def test_penalty_is_added_but_other_tax_remains_separate(self):
        case = case_input()
        case["adjustments"].append({"rule_id": "late_penalty"})
        result = self.run_calculator(case=case)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["penalties_total"], 5)
        self.assertEqual(payload["primary_tax_total"], 32)
        self.assertEqual(payload["other_taxes_total"], 7)

    def test_parameter_effective_end_date_is_enforced(self):
        params = legal_parameters()
        params["rate_schedule"]["effective_to"] = "2026-06-29"
        self.assert_error(self.run_calculator(params=params), "parameter_not_effective")

    def test_adjustment_parameter_also_requires_provenance(self):
        params = legal_parameters()
        del params["adjustment_rules"]["filing_credit"]["source"]
        self.assert_error(
            self.run_calculator(params=params), "missing_parameter_provenance"
        )

    def test_fractional_krw_result_is_rejected_without_rounding_support(self):
        case = case_input()
        case["gross_assets"][0]["amount"] = 251
        self.assert_error(self.run_calculator(case=case), "fractional_krw_result")

    def test_cross_rule_aggregate_deduction_limit_is_enforced(self):
        case = case_input()
        params = legal_parameters()
        params["deduction_rules"]["special"] = {
            **provenance("특별공제"),
            "limit": 50,
        }
        params["deduction_groups"] = {
            "combined": {
                **provenance("공제 합산한도"),
                "rules": ["basic", "special"],
                "aggregate_limit": 60,
                "max_rules": 2,
            }
        }
        case["deductions"].append({"rule_id": "special", "amount": 20})
        self.assert_error(
            self.run_calculator(case=case, params=params),
            "deduction_group_limit_exceeded",
        )

    def test_mutually_exclusive_deduction_rules_are_enforced(self):
        case = case_input()
        params = legal_parameters()
        params["deduction_rules"]["alternative"] = {
            **provenance("선택공제"),
            "limit": 50,
        }
        params["deduction_groups"] = {
            "choose_one": {
                **provenance("선택공제 관계"),
                "rules": ["basic", "alternative"],
                "aggregate_limit": 100,
                "max_rules": 1,
            }
        }
        case["deductions"].append({"rule_id": "alternative", "amount": 10})
        self.assert_error(
            self.run_calculator(case=case, params=params),
            "deduction_group_conflict",
        )


if __name__ == "__main__":
    unittest.main()
