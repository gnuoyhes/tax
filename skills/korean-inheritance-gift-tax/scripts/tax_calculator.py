#!/usr/bin/env python3
"""Provenance-gated progressive tax calculator.

The engine contains no Korean tax rates, deductions, or credits.  It accepts
case facts and a separately sourced legal-parameter file, validates provenance
and effective dates, then cross-checks marginal-bracket and quick-deduction
calculations.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


class CalculationError(Exception):
    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def fail(code: str, message: str, **details: Any) -> None:
    raise CalculationError(code, message, details)


def parse_date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        fail("invalid_date", f"{field} must be an ISO date", field=field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        fail("invalid_date", f"{field} must be YYYY-MM-DD", field=field)


def amount(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        fail("invalid_amount", f"{field} must be a non-negative KRW integer")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("invalid_amount", f"{field} must be a non-negative KRW integer")
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        fail("invalid_amount", f"{field} must be a non-negative KRW integer")
    return parsed


def decimal_value(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        fail("invalid_parameter", f"{field} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("invalid_parameter", f"{field} must be numeric")
    if not parsed.is_finite():
        fail("invalid_parameter", f"{field} must be finite")
    return parsed


def output_number(value: Decimal) -> Any:
    integral = value.to_integral_value()
    return int(integral) if value == integral else format(value.normalize(), "f")


def require_integer_krw_result(value: Decimal, field: str) -> None:
    if value != value.to_integral_value():
        fail(
            "fractional_krw_result",
            "A calculation produced fractional KRW; do not use it without a sourced rounding rule and matching engine support",
            field=field,
            value=output_number(value),
        )


def require_fields(data: dict, fields: Iterable[str], scope: str) -> None:
    for field in fields:
        if field not in data or data[field] in (None, ""):
            fail(
                "missing_required_field",
                f"Missing required field: {scope}.{field}",
                field=f"{scope}.{field}",
            )


def validate_provenance(parameter: dict, name: str, tax_point: date) -> None:
    required = ("effective_from", "verified_on", "source")
    missing = [field for field in required if parameter.get(field) in (None, "")]
    source = parameter.get("source")
    if not isinstance(source, dict):
        missing.append("source")
    else:
        for field in ("authority", "law_or_guidance", "article", "url"):
            if source.get(field) in (None, ""):
                missing.append(f"source.{field}")
        url = source.get("url", "")
        if url and not str(url).startswith(("https://", "http://")):
            missing.append("source.url(valid http/https URL)")
    if missing:
        fail(
            "missing_parameter_provenance",
            f"Legal parameter {name} lacks required provenance",
            parameter=name,
            missing=sorted(set(missing)),
        )

    effective_from = parse_date(parameter["effective_from"], f"{name}.effective_from")
    effective_to_raw = parameter.get("effective_to")
    effective_to = (
        parse_date(effective_to_raw, f"{name}.effective_to")
        if effective_to_raw
        else None
    )
    parse_date(parameter["verified_on"], f"{name}.verified_on")
    if tax_point < effective_from or (effective_to and tax_point > effective_to):
        fail(
            "parameter_not_effective",
            f"Legal parameter {name} is not effective on the tax point date",
            parameter=name,
            tax_point_date=tax_point.isoformat(),
            effective_from=effective_from.isoformat(),
            effective_to=effective_to.isoformat() if effective_to else None,
        )


def validate_rate_schedule(schedule: dict, tax_point: date) -> List[dict]:
    validate_provenance(schedule, "rate_schedule", tax_point)
    brackets = schedule.get("brackets")
    if not isinstance(brackets, list) or not brackets:
        fail("invalid_rate_schedule", "rate_schedule.brackets must be non-empty")

    normalized: List[dict] = []
    lower = Decimal(0)
    cumulative = Decimal(0)
    prior_rate = Decimal(0)

    for index, bracket in enumerate(brackets):
        if not isinstance(bracket, dict):
            fail("invalid_rate_schedule", "Each rate bracket must be an object")
        require_fields(bracket, ("rate", "quick_deduction"), f"brackets[{index}]")
        rate = decimal_value(bracket["rate"], f"brackets[{index}].rate")
        quick = amount(
            bracket["quick_deduction"], f"brackets[{index}].quick_deduction"
        )
        if rate < 0 or rate > 1 or rate < prior_rate:
            fail(
                "invalid_rate_schedule",
                "Rates must be non-negative, no greater than 1, and non-decreasing",
                bracket=index,
            )

        upper_raw = bracket.get("up_to")
        if upper_raw is None:
            if index != len(brackets) - 1:
                fail(
                    "invalid_rate_schedule",
                    "Only the final bracket may have a null upper bound",
                )
            upper = None
        else:
            upper = amount(upper_raw, f"brackets[{index}].up_to")
            if upper <= lower:
                fail(
                    "invalid_rate_schedule",
                    "Bracket upper bounds must be strictly increasing",
                    bracket=index,
                )

        expected_quick = lower * rate - cumulative
        if quick != expected_quick:
            fail(
                "rate_schedule_inconsistent",
                "Quick deduction does not match the marginal bracket schedule",
                bracket=index,
                supplied=output_number(quick),
                expected=output_number(expected_quick),
            )

        normalized.append(
            {"lower": lower, "upper": upper, "rate": rate, "quick": quick}
        )
        if upper is not None:
            cumulative += (upper - lower) * rate
            lower = upper
        prior_rate = rate

    if normalized[-1]["upper"] is not None:
        fail("invalid_rate_schedule", "The final bracket must have no upper bound")
    return normalized


def sum_items(items: Any, field: str) -> Tuple[Decimal, List[dict]]:
    if not isinstance(items, list):
        fail("invalid_case_input", f"{field} must be a list")
    seen = set()
    normalized = []
    total = Decimal(0)
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            fail("invalid_case_input", f"{field}[{index}] must be an object")
        require_fields(item, ("id", "amount"), f"{field}[{index}]")
        item_id = str(item["id"])
        if item_id in seen:
            fail(
                "duplicate_case_item",
                f"Duplicate item id in {field}: {item_id}",
                field=field,
                id=item_id,
            )
        seen.add(item_id)
        item_amount = amount(item["amount"], f"{field}[{index}].amount")
        total += item_amount
        normalized.append({**item, "amount": output_number(item_amount)})
    return total, normalized


def progressive_tax(base: Decimal, brackets: List[dict]) -> Decimal:
    tax = Decimal(0)
    for bracket in brackets:
        lower = bracket["lower"]
        upper = bracket["upper"]
        if base <= lower:
            break
        taxable_slice = base - lower if upper is None else min(base, upper) - lower
        tax += taxable_slice * bracket["rate"]
        if upper is None or base <= upper:
            break
    return tax


def quick_tax(base: Decimal, brackets: List[dict]) -> Decimal:
    for bracket in brackets:
        upper = bracket["upper"]
        if upper is None or base <= upper:
            return base * bracket["rate"] - bracket["quick"]
    fail("invalid_rate_schedule", "No rate bracket covers the taxable base")
    return Decimal(0)


def calculate(case: dict, params: dict) -> dict:
    require_fields(
        case,
        (
            "schema_version",
            "case_id",
            "tax_point_date",
            "tax_type",
            "currency",
            "amount_unit",
        ),
        "case",
    )
    require_fields(
        params,
        (
            "schema_version",
            "parameter_set_id",
            "tax_type",
            "currency",
            "rate_schedule",
        ),
        "params",
    )
    supported_schema_version = "1.0"
    if (
        case["schema_version"] != supported_schema_version
        or params["schema_version"] != supported_schema_version
    ):
        fail(
            "unsupported_schema_version",
            "Case and legal parameters must use the supported schema version",
            supported=supported_schema_version,
            case_schema_version=case["schema_version"],
            parameter_schema_version=params["schema_version"],
        )

    supported_tax_types = {"gift_tax", "inheritance_tax"}
    if (
        case["tax_type"] not in supported_tax_types
        or params["tax_type"] not in supported_tax_types
    ):
        fail(
            "unsupported_tax_type",
            "Only Korean gift tax and inheritance tax are supported",
            case_tax_type=case["tax_type"],
            parameter_tax_type=params["tax_type"],
        )

    if case["currency"] != "KRW" or case["amount_unit"] != "KRW":
        fail(
            "unit_mismatch",
            "The calculator accepts integer Korean won only",
            currency=case["currency"],
            amount_unit=case["amount_unit"],
        )
    if params["currency"] != "KRW":
        fail("unit_mismatch", "Legal parameters must use KRW")
    if case["tax_type"] != params["tax_type"]:
        fail(
            "tax_type_mismatch",
            "Case tax_type and parameter tax_type differ",
            case_tax_type=case["tax_type"],
            parameter_tax_type=params["tax_type"],
        )

    tax_point = parse_date(case["tax_point_date"], "case.tax_point_date")
    brackets = validate_rate_schedule(params["rate_schedule"], tax_point)

    deduction_rules = params.get("deduction_rules", {})
    deduction_groups = params.get("deduction_groups", {})
    adjustment_rules = params.get("adjustment_rules", {})
    if (
        not isinstance(deduction_rules, dict)
        or not isinstance(deduction_groups, dict)
        or not isinstance(adjustment_rules, dict)
    ):
        fail("invalid_parameter", "Rule collections must be objects")
    for rule_id, rule in deduction_rules.items():
        if not isinstance(rule, dict):
            fail("invalid_parameter", f"Deduction rule {rule_id} must be an object")
        validate_provenance(rule, f"deduction_rules.{rule_id}", tax_point)
        if "limit" not in rule:
            fail("invalid_parameter", f"Deduction rule {rule_id} requires a limit")
        amount(rule["limit"], f"deduction_rules.{rule_id}.limit")
    for group_id, group in deduction_groups.items():
        if not isinstance(group, dict):
            fail("invalid_parameter", f"Deduction group {group_id} must be an object")
        validate_provenance(group, f"deduction_groups.{group_id}", tax_point)
        rules = group.get("rules")
        if not isinstance(rules, list) or not rules or len(set(rules)) != len(rules):
            fail(
                "invalid_parameter",
                f"Deduction group {group_id} requires a non-empty unique rules list",
            )
        unknown_rules = [rule_id for rule_id in rules if rule_id not in deduction_rules]
        if unknown_rules:
            fail(
                "invalid_parameter",
                f"Deduction group {group_id} refers to unknown rules",
                unknown_rules=unknown_rules,
            )
        if "aggregate_limit" not in group and "max_rules" not in group:
            fail(
                "invalid_parameter",
                f"Deduction group {group_id} requires aggregate_limit or max_rules",
            )
        if "aggregate_limit" in group:
            amount(
                group["aggregate_limit"],
                f"deduction_groups.{group_id}.aggregate_limit",
            )
        if "max_rules" in group:
            max_rules = amount(
                group["max_rules"], f"deduction_groups.{group_id}.max_rules"
            )
            if max_rules < 1:
                fail("invalid_parameter", "Deduction group max_rules must be positive")
    for rule_id, rule in adjustment_rules.items():
        if not isinstance(rule, dict):
            fail("invalid_parameter", f"Adjustment rule {rule_id} must be an object")
        validate_provenance(rule, f"adjustment_rules.{rule_id}", tax_point)

    gross, gross_items = sum_items(case.get("gross_assets", []), "gross_assets")
    additions, addition_items = sum_items(case.get("additions", []), "additions")
    liabilities, liability_items = sum_items(
        case.get("liabilities", []), "liabilities"
    )
    exclusions, exclusion_items = sum_items(case.get("exclusions", []), "exclusions")

    warnings: List[str] = []
    raw_taxable_value = gross + additions - liabilities - exclusions
    taxable_value = raw_taxable_value
    if taxable_value < 0:
        taxable_value = Decimal(0)
        warnings.append("taxable_value_clamped_to_zero")

    deductions = case.get("deductions", [])
    if not isinstance(deductions, list):
        fail("invalid_case_input", "deductions must be a list")
    deduction_lines = []
    deduction_total = Decimal(0)
    used_rules = set()
    applied_by_rule: Dict[str, Decimal] = {}
    for index, deduction in enumerate(deductions):
        if not isinstance(deduction, dict):
            fail("invalid_case_input", f"deductions[{index}] must be an object")
        require_fields(deduction, ("rule_id", "amount"), f"deductions[{index}]")
        rule_id = deduction["rule_id"]
        if rule_id in used_rules:
            fail(
                "duplicate_deduction",
                f"Deduction rule used more than once: {rule_id}",
                rule_id=rule_id,
            )
        used_rules.add(rule_id)
        rule = deduction_rules.get(rule_id)
        if rule is None:
            fail("unknown_rule", f"Unknown deduction rule: {rule_id}")
        applied = amount(deduction["amount"], f"deductions[{index}].amount")
        limit = amount(rule["limit"], f"deduction_rules.{rule_id}.limit")
        if applied > limit:
            fail(
                "deduction_limit_exceeded",
                f"Deduction {rule_id} exceeds its legal limit",
                rule_id=rule_id,
                applied=output_number(applied),
                limit=output_number(limit),
            )
        deduction_total += applied
        applied_by_rule[rule_id] = applied
        deduction_lines.append(
            {"rule_id": rule_id, "amount": output_number(applied), "limit": output_number(limit)}
        )

    for group_id, group in deduction_groups.items():
        applied_rules = [
            rule_id for rule_id in group["rules"] if rule_id in applied_by_rule
        ]
        if "max_rules" in group:
            max_rules = amount(
                group["max_rules"], f"deduction_groups.{group_id}.max_rules"
            )
            if Decimal(len(applied_rules)) > max_rules:
                fail(
                    "deduction_group_conflict",
                    f"Too many deductions were selected from group {group_id}",
                    group_id=group_id,
                    applied_rules=applied_rules,
                    max_rules=output_number(max_rules),
                )
        group_total = sum(
            (applied_by_rule[rule_id] for rule_id in applied_rules), Decimal(0)
        )
        if "aggregate_limit" in group:
            group_limit = amount(
                group["aggregate_limit"],
                f"deduction_groups.{group_id}.aggregate_limit",
            )
            if group_total > group_limit:
                fail(
                    "deduction_group_limit_exceeded",
                    f"Combined deductions exceed the limit for group {group_id}",
                    group_id=group_id,
                    applied=output_number(group_total),
                    limit=output_number(group_limit),
                )

    raw_taxable_base = taxable_value - deduction_total
    taxable_base = raw_taxable_base
    if taxable_base < 0:
        taxable_base = Decimal(0)
        warnings.append("taxable_base_clamped_to_zero")

    marginal = progressive_tax(taxable_base, brackets)
    quick = quick_tax(taxable_base, brackets)
    if marginal != quick:
        fail(
            "calculation_mismatch",
            "Progressive and quick-deduction calculations differ",
            progressive=output_number(marginal),
            quick_deduction=output_number(quick),
        )
    require_integer_krw_result(marginal, "gross_tax")

    adjustment_lines = []
    credit_total = Decimal(0)
    surcharge_total = Decimal(0)
    penalty_total = Decimal(0)
    used_adjustments = set()
    for index, requested in enumerate(case.get("adjustments", [])):
        if not isinstance(requested, dict) or not requested.get("rule_id"):
            fail("invalid_case_input", f"adjustments[{index}] requires rule_id")
        rule_id = requested["rule_id"]
        if rule_id in used_adjustments:
            fail("duplicate_adjustment", f"Adjustment used more than once: {rule_id}")
        used_adjustments.add(rule_id)
        rule = adjustment_rules.get(rule_id)
        if rule is None:
            fail("unknown_rule", f"Unknown adjustment rule: {rule_id}")
        category = rule.get("category")
        method = rule.get("method")
        if category not in ("credit", "surcharge", "penalty"):
            fail("invalid_parameter", f"Unsupported adjustment category: {category}")
        if method == "fixed":
            applied = amount(rule.get("value"), f"adjustment_rules.{rule_id}.value")
        elif method == "rate":
            if rule.get("base") != "gross_tax":
                fail("invalid_parameter", "Rate adjustments must use gross_tax base")
            rate = decimal_value(rule.get("value"), f"adjustment_rules.{rule_id}.value")
            if rate < 0 or rate > 1:
                fail("invalid_parameter", "Adjustment rate must be between 0 and 1")
            applied = marginal * rate
        else:
            fail("invalid_parameter", f"Unsupported adjustment method: {method}")
        limit_raw = rule.get("limit")
        if limit_raw is not None:
            applied = min(applied, amount(limit_raw, f"adjustment_rules.{rule_id}.limit"))
        require_integer_krw_result(applied, f"adjustments.{rule_id}")
        if category == "credit":
            credit_total += applied
        elif category == "surcharge":
            surcharge_total += applied
        else:
            penalty_total += applied
        adjustment_lines.append(
            {
                "rule_id": rule_id,
                "category": category,
                "method": method,
                "amount": output_number(applied),
            }
        )

    primary_total = marginal + surcharge_total + penalty_total - credit_total
    if primary_total < 0:
        primary_total = Decimal(0)
        warnings.append("primary_tax_total_clamped_to_zero")
    require_integer_krw_result(primary_total, "primary_tax_total")

    other_taxes = case.get("other_taxes", [])
    if not isinstance(other_taxes, list):
        fail("invalid_case_input", "other_taxes must be a list")
    other_tax_lines = []
    other_taxes_total = Decimal(0)
    for index, other in enumerate(other_taxes):
        if not isinstance(other, dict):
            fail("invalid_case_input", f"other_taxes[{index}] must be an object")
        require_fields(other, ("tax_type", "amount"), f"other_taxes[{index}]")
        other_amount = amount(other["amount"], f"other_taxes[{index}].amount")
        other_taxes_total += other_amount
        other_tax_lines.append({**other, "amount": output_number(other_amount)})

    return {
        "schema_version": "1.0",
        "case_id": case["case_id"],
        "tax_point_date": tax_point.isoformat(),
        "tax_type": case["tax_type"],
        "currency": "KRW",
        "amount_unit": "KRW",
        "parameter_set_id": params["parameter_set_id"],
        "calculation_steps": {
            "gross_assets": output_number(gross),
            "additions": output_number(additions),
            "liabilities": output_number(liabilities),
            "exclusions": output_number(exclusions),
            "raw_taxable_value": output_number(raw_taxable_value),
            "taxable_value": output_number(taxable_value),
            "deductions": output_number(deduction_total),
            "raw_taxable_base": output_number(raw_taxable_base),
        },
        "input_lines": {
            "gross_assets": gross_items,
            "additions": addition_items,
            "liabilities": liability_items,
            "exclusions": exclusion_items,
            "deductions": deduction_lines,
        },
        "taxable_base": output_number(taxable_base),
        "gross_tax": output_number(marginal),
        "method_check": {
            "progressive": output_number(marginal),
            "quick_deduction": output_number(quick),
            "matches": marginal == quick,
        },
        "adjustments": adjustment_lines,
        "credits_total": output_number(credit_total),
        "surcharges_total": output_number(surcharge_total),
        "penalties_total": output_number(penalty_total),
        "primary_tax_total": output_number(primary_total),
        "other_taxes": other_tax_lines,
        "other_taxes_total": output_number(other_taxes_total),
        "warnings": warnings,
    }


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail("file_not_found", f"File not found: {path}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", f"Invalid JSON in {path}", line=exc.lineno, column=exc.colno)
    if not isinstance(data, dict):
        fail("invalid_json", f"Top-level JSON in {path} must be an object")
    return data


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Calculate and cross-check tax from sourced legal parameters."
    )
    parser.add_argument("--case", required=True, type=Path, help="Case input JSON")
    parser.add_argument(
        "--params", required=True, type=Path, help="Sourced legal-parameter JSON"
    )
    parser.add_argument("--out", type=Path, help="Optional output JSON path")
    args = parser.parse_args(argv)

    try:
        result = calculate(load_json(args.case), load_json(args.params))
    except CalculationError as exc:
        payload = {
            "error_code": exc.code,
            "message": exc.message,
            "details": exc.details,
        }
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 2

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    sys.stdout.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
