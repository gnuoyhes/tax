#!/usr/bin/env python3
"""Fail-closed contracts for the bounded tax cross-review workflow."""

import argparse
import copy
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
ARTIFACT_SCHEMAS = {
    "case-packet.json": "case-packet.schema.json",
    "draft-opinion.json": "draft-opinion.schema.json",
    "independent-review.json": "independent-review.schema.json",
    "review-memo.json": "review-memo.schema.json",
    "response-matrix.json": "response-matrix.schema.json",
    "final-disposition.json": "final-disposition.schema.json",
    "human-approval.json": "human-approval.schema.json",
}
IDENTITY_FIELDS = ("case_id", "case_version", "tax_date", "review_date")
SEVERITIES = {"BLOCKER", "MAJOR", "MINOR", "NOTE"}


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def load_workflow(path: Path) -> Dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("workflow must be a JSON object")

    required = {
        "version",
        "revision_limit",
        "human_approval_actor",
        "authorized_reviewers",
        "states",
        "transitions",
        "artifact_visibility",
        "version_invalidated_artifacts",
        "terminal_states",
        "required_artifacts_by_state",
    }
    missing = required.difference(data)
    if missing:
        raise ValueError(f"workflow missing fields: {sorted(missing)}")
    if not isinstance(data["version"], int) or data["version"] < 1:
        raise ValueError("workflow version must be a positive integer")
    if not isinstance(data["states"], list) or not data["states"]:
        raise ValueError("workflow states must be a non-empty list")
    if any(not isinstance(state, str) or not state for state in data["states"]):
        raise ValueError("workflow states must be non-empty strings")
    if len(data["states"]) != len(set(data["states"])):
        raise ValueError("workflow states must be unique")
    states = set(data["states"])
    if not isinstance(data["revision_limit"], int) or data["revision_limit"] < 1:
        raise ValueError("revision_limit must be a positive integer")
    _require_string(data["human_approval_actor"], "human_approval_actor")

    if not isinstance(data["transitions"], list):
        raise ValueError("workflow transitions must be a list")
    seen_transitions = set()
    for index, transition in enumerate(data["transitions"]):
        if not isinstance(transition, dict):
            raise ValueError(f"transition {index} must be an object")
        if set(transition) != {"from", "to", "actors"}:
            raise ValueError(f"transition {index} has invalid fields")
        if transition["from"] not in states or transition["to"] not in states:
            raise ValueError(f"transition {index} references an unknown state")
        actors = transition["actors"]
        if (
            not isinstance(actors, list)
            or not actors
            or any(not isinstance(actor, str) or not actor for actor in actors)
        ):
            raise ValueError(f"transition {index} actors must be a non-empty list")
        pair = (transition["from"], transition["to"])
        if pair in seen_transitions:
            raise ValueError(f"duplicate transition: {pair}")
        seen_transitions.add(pair)

    visibility = data["artifact_visibility"]
    if not isinstance(visibility, dict) or not visibility:
        raise ValueError("artifact_visibility must be a non-empty object")
    for phase, agents in visibility.items():
        _require_string(phase, "visibility phase")
        if not isinstance(agents, dict):
            raise ValueError(f"visibility phase {phase} must map agents")
        for agent, artifacts in agents.items():
            _require_string(agent, "visibility agent")
            if not isinstance(artifacts, list) or any(
                not isinstance(item, str) or not item for item in artifacts
            ):
                raise ValueError(f"visibility artifacts for {phase}/{agent} are invalid")

    invalidated = data["version_invalidated_artifacts"]
    if not isinstance(invalidated, list) or any(
        not isinstance(item, str) or not item for item in invalidated
    ):
        raise ValueError("version_invalidated_artifacts must be a list of names")
    terminals = data["terminal_states"]
    if not isinstance(terminals, list) or not set(terminals).issubset(states):
        raise ValueError("terminal_states must reference known states")
    required_artifacts = data["required_artifacts_by_state"]
    if not isinstance(required_artifacts, dict):
        raise ValueError("required_artifacts_by_state must be an object")
    for state, artifact_names in required_artifacts.items():
        if state not in states:
            raise ValueError("required_artifacts_by_state references an unknown state")
        if not isinstance(artifact_names, list) or any(
            name not in ARTIFACT_SCHEMAS for name in artifact_names
        ):
            raise ValueError(f"required artifacts for {state} are invalid")

    reviewers = data["authorized_reviewers"]
    if not isinstance(reviewers, list):
        raise ValueError("authorized_reviewers must be a list")
    reviewer_ids: Set[str] = set()
    for reviewer in reviewers:
        if not isinstance(reviewer, dict):
            raise ValueError("authorized reviewer must be an object")
        expected = {"reviewer_id", "credential_verified", "allowed_scopes"}
        if set(reviewer) != expected:
            raise ValueError("authorized reviewer has invalid fields")
        reviewer_id = _require_string(reviewer["reviewer_id"], "reviewer_id")
        if reviewer_id in reviewer_ids:
            raise ValueError("authorized reviewer IDs must be unique")
        reviewer_ids.add(reviewer_id)
        if reviewer["credential_verified"] is not True:
            raise ValueError("authorized reviewer credentials must be verified")
        scopes = reviewer["allowed_scopes"]
        if not isinstance(scopes, list) or not scopes or any(
            not isinstance(scope, str) or not scope for scope in scopes
        ):
            raise ValueError("authorized reviewer scopes are invalid")
    return data


def _validate_case_context(case_record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(case_record, dict):
        raise ValueError("case_record is required")
    _require_string(case_record.get("case_id"), "case_id")
    version = case_record.get("case_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("case_version must be a positive integer")
    _require_string(case_record.get("tax_date"), "tax_date")
    _require_string(case_record.get("review_date"), "review_date")
    revision_cycle = case_record.get("revision_cycle")
    if (
        not isinstance(revision_cycle, int)
        or isinstance(revision_cycle, bool)
        or revision_cycle < 0
    ):
        raise ValueError("revision_cycle must be a non-negative integer")
    severities = case_record.get("unresolved_severities")
    if not isinstance(severities, list) or any(item not in SEVERITIES for item in severities):
        raise ValueError("unresolved_severities contains an unknown severity")
    if case_record.get("pii_masking_status") not in {"MASKED", "REJECTED_UNMASKED"}:
        raise ValueError("pii_masking_status is required")
    for field in ("human_review_required", "high_risk", "external_action_requested"):
        if not isinstance(case_record.get(field), bool):
            raise ValueError(f"{field} must be boolean")
    artifacts = case_record.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("artifacts must be an object")
    return case_record


def allowed_artifacts_for_phase(
    workflow: Dict[str, Any], agent: str, phase: str
) -> List[str]:
    phase_map = workflow.get("artifact_visibility", {}).get(phase)
    if not isinstance(phase_map, dict):
        raise ValueError(f"unknown artifact-visibility phase: {phase}")
    artifacts = phase_map.get(agent)
    if artifacts is None:
        return []
    if not isinstance(artifacts, list):
        raise ValueError("malformed artifact visibility")
    return list(artifacts)


def authorize_artifact_read(
    workflow: Dict[str, Any], agent: str, phase: str, artifact: str
) -> bool:
    return artifact in allowed_artifacts_for_phase(workflow, agent, phase)


def next_state_after_review(
    workflow: Dict[str, Any], revision_cycle: int, unresolved_severities: Iterable[str]
) -> str:
    if (
        not isinstance(revision_cycle, int)
        or isinstance(revision_cycle, bool)
        or revision_cycle < 0
    ):
        raise ValueError("revision_cycle must be a non-negative integer")
    severities = set(unresolved_severities)
    unknown = severities.difference(SEVERITIES)
    if unknown:
        raise ValueError(f"unknown severities: {sorted(unknown)}")
    if severities.intersection({"BLOCKER", "MAJOR"}):
        if revision_cycle >= workflow["revision_limit"]:
            return "HUMAN_JUDGMENT_REQUIRED"
        return "REVISION_REQUIRED"
    return "CROSS_REVIEW_APPROVED"


def _resolve_ref(ref: str, current_schema_path: Path) -> tuple:
    file_part, _, fragment = ref.partition("#")
    target_path = current_schema_path if not file_part else SCHEMA_DIR / file_part
    target = json.loads(target_path.read_text(encoding="utf-8"))
    if fragment:
        for token in fragment.lstrip("/").split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            target = target[token]
    return target, target_path


def _validate_format(value: str, format_name: str, path: str) -> None:
    try:
        if format_name == "date":
            date.fromisoformat(value)
        elif format_name == "date-time":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif format_name == "uri":
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError
    except ValueError as exc:
        raise ValueError(f"{path} is not a valid {format_name}") from exc


def validate_json_instance(
    instance: Any, schema: Dict[str, Any], schema_path: Path, path: str = "$"
) -> None:
    if "$ref" in schema:
        target, target_path = _resolve_ref(schema["$ref"], schema_path)
        validate_json_instance(instance, target, target_path, path)
        return

    schema_type = schema.get("type")
    type_checks = {
        "object": lambda value: isinstance(value, dict),
        "array": lambda value: isinstance(value, list),
        "string": lambda value: isinstance(value, str),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda value: isinstance(value, bool),
        "null": lambda value: value is None,
    }
    if schema_type and (schema_type not in type_checks or not type_checks[schema_type](instance)):
        raise ValueError(f"{path} must be of type {schema_type}")
    if "const" in schema and instance != schema["const"]:
        raise ValueError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed value")

    if schema_type == "object":
        required = schema.get("required", [])
        missing = set(required).difference(instance)
        if missing:
            raise ValueError(f"{path} missing fields: {sorted(missing)}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(instance).difference(properties)
            if extras:
                raise ValueError(f"{path} has unexpected fields: {sorted(extras)}")
        for key, value in instance.items():
            if key in properties:
                validate_json_instance(value, properties[key], schema_path, f"{path}.{key}")
    elif schema_type == "array":
        if len(instance) < schema.get("minItems", 0):
            raise ValueError(f"{path} has too few items")
        if schema.get("uniqueItems"):
            canonical = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in instance]
            if len(canonical) != len(set(canonical)):
                raise ValueError(f"{path} must contain unique items")
        item_schema = schema.get("items")
        if item_schema:
            for index, value in enumerate(instance):
                validate_json_instance(value, item_schema, schema_path, f"{path}[{index}]")
    elif schema_type == "string":
        if len(instance) < schema.get("minLength", 0):
            raise ValueError(f"{path} is too short")
        if "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
            raise ValueError(f"{path} does not match the required pattern")
        if "format" in schema:
            _validate_format(instance, schema["format"], path)
    elif schema_type in {"integer", "number"}:
        if "minimum" in schema and instance < schema["minimum"]:
            raise ValueError(f"{path} is below the minimum")
        if "maximum" in schema and instance > schema["maximum"]:
            raise ValueError(f"{path} is above the maximum")


def validate_artifact(artifact_name: str, artifact: Dict[str, Any]) -> None:
    schema_name = ARTIFACT_SCHEMAS.get(artifact_name)
    if schema_name is None:
        raise ValueError(f"unknown artifact: {artifact_name}")
    schema_path = SCHEMA_DIR / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate_json_instance(artifact, schema, schema_path)


def validate_case_bundle(
    workflow: Dict[str, Any],
    case_record: Dict[str, Any],
    artifacts: Dict[str, Dict[str, Any]],
) -> None:
    context = _validate_case_context(case_record)
    if not isinstance(artifacts, dict):
        raise ValueError("artifacts must be an object")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            raise ValueError(f"artifact {name} must be an object")
        validate_artifact(name, artifact)
        for field in IDENTITY_FIELDS:
            if artifact.get(field) != context.get(field):
                raise ValueError(f"artifact {name} has mismatched {field}")

    memo = artifacts.get("review-memo.json")
    matrix = artifacts.get("response-matrix.json")
    if memo:
        review_ids = [finding["review_id"] for finding in memo["findings"]]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("ReviewMemo review_id values must be unique")
        if matrix:
            response_ids = [response["review_id"] for response in matrix["responses"]]
            if len(response_ids) != len(set(response_ids)):
                raise ValueError("ResponseMatrix review_id values must be unique")
            if set(response_ids) != set(review_ids):
                raise ValueError("every ReviewMemo finding must have exactly one response")

    disposition = artifacts.get("final-disposition.json")
    if disposition:
        expected = next_state_after_review(
            workflow,
            context["revision_cycle"],
            context["unresolved_severities"],
        )
        if disposition["status"] == "CROSS_REVIEW_APPROVED" and expected != "CROSS_REVIEW_APPROVED":
            raise ValueError("approved disposition conflicts with unresolved findings")
        requires_human = (
            context["human_review_required"]
            or context["high_risk"]
            or context["external_action_requested"]
        )
        if disposition["human_review_required"] != requires_human:
            raise ValueError("disposition human-review flag conflicts with case context")


def _validate_human_approval(
    workflow: Dict[str, Any], case_record: Dict[str, Any], target: str
) -> None:
    approval = case_record.get("human_approval")
    principal = case_record.get("authenticated_principal")
    if not isinstance(approval, dict) or not isinstance(principal, dict):
        raise ValueError("human approval and authenticated principal are required")
    validate_artifact("human-approval.json", approval)
    if principal.get("authentication_verified") is not True:
        raise ValueError("human approver authentication is not verified")
    reviewer_id = principal.get("reviewer_id")
    if reviewer_id != approval.get("authorized_reviewer_id"):
        raise ValueError("authenticated principal does not match approval record")
    registry_entry = next(
        (
            reviewer
            for reviewer in workflow["authorized_reviewers"]
            if reviewer["reviewer_id"] == reviewer_id
        ),
        None,
    )
    if registry_entry is None or registry_entry["credential_verified"] is not True:
        raise ValueError("approver is not a pre-authorized tax professional")
    if not set(approval["approval_scope"]).issubset(registry_entry["allowed_scopes"]):
        raise ValueError("approval scope exceeds the approver authorization")
    for field in IDENTITY_FIELDS:
        if approval.get(field) != case_record.get(field):
            raise ValueError(f"human approval has mismatched {field}")
    decision_for_target = {
        "HUMAN_APPROVED": "APPROVED",
        "HUMAN_REJECTED": "REJECTED",
        "MORE_INFO_REQUIRED": "MORE_INFO_REQUIRED",
        "READY_FOR_ACTION": "APPROVED",
    }
    if approval.get("decision") != decision_for_target[target]:
        raise ValueError("human approval decision does not match target state")


def validate_transition(
    workflow: Dict[str, Any],
    current: str,
    target: str,
    actor: str,
    case_record: Optional[Dict[str, Any]] = None,
) -> None:
    context = _validate_case_context(case_record)
    states = set(workflow["states"])
    if current not in states or target not in states:
        raise ValueError(f"unknown workflow state: {current!r} -> {target!r}")
    transition = next(
        (
            item
            for item in workflow["transitions"]
            if item["from"] == current and item["to"] == target
        ),
        None,
    )
    if transition is None:
        raise ValueError(f"transition is not allowed: {current} -> {target}")
    if actor not in transition["actors"]:
        raise ValueError(f"actor {actor!r} cannot perform {current} -> {target}")

    if current == "INTAKE_PENDING" and target == "READY_FOR_DRAFT":
        if context["pii_masking_status"] != "MASKED":
            raise ValueError("unmasked PII cannot enter drafting")
    if target == "BLOCKED_UNMASKED_PII" and context["pii_masking_status"] == "MASKED":
        raise ValueError("masked cases cannot enter the unmasked-PII stop")
    if target == "REVISION_REQUIRED":
        if not set(context["unresolved_severities"]).intersection({"BLOCKER", "MAJOR"}):
            raise ValueError("revision requires an unresolved BLOCKER or MAJOR")
        if context["revision_cycle"] >= workflow["revision_limit"]:
            raise ValueError("revision limit exceeded")
    if target == "CROSS_REVIEW_APPROVED":
        expected = next_state_after_review(
            workflow,
            context["revision_cycle"],
            context["unresolved_severities"],
        )
        if expected != "CROSS_REVIEW_APPROVED":
            raise ValueError("unresolved material findings cannot be approved")
    if target == "HUMAN_JUDGMENT_REQUIRED":
        expected = next_state_after_review(
            workflow,
            context["revision_cycle"],
            context["unresolved_severities"],
        )
        if expected != "HUMAN_JUDGMENT_REQUIRED" and not context["high_risk"]:
            raise ValueError("human judgment is not required by the case context")
    if target == "HUMAN_REVIEW_REQUIRED":
        if not (
            context["human_review_required"]
            or context["high_risk"]
            or context["external_action_requested"]
        ):
            raise ValueError("human review is not required for this case")
    if target in {"HUMAN_APPROVED", "HUMAN_REJECTED", "MORE_INFO_REQUIRED"}:
        if actor != workflow["human_approval_actor"]:
            raise ValueError("only the configured human approval actor may decide")
        _validate_human_approval(workflow, context, target)
    if target == "READY_FOR_ACTION":
        _validate_human_approval(workflow, context, target)


def advance_case(
    workflow: Dict[str, Any],
    case_record: Dict[str, Any],
    target: str,
    actor: str,
) -> Dict[str, Any]:
    context = _validate_case_context(case_record)
    current = _require_string(context.get("state"), "state")
    validate_transition(workflow, current, target, actor, context)
    validate_case_bundle(workflow, context, context["artifacts"])
    required = set(workflow["required_artifacts_by_state"].get(target, []))
    missing = required.difference(context["artifacts"])
    if missing:
        raise ValueError(
            f"state {target} requires artifacts: {sorted(missing)}"
        )
    disposition_targets = {
        "CROSS_REVIEW_APPROVED",
        "CROSS_REVIEW_CONDITIONAL",
        "CROSS_REVIEW_REJECTED",
        "HUMAN_JUDGMENT_REQUIRED",
    }
    if target in disposition_targets:
        disposition = context["artifacts"]["final-disposition.json"]
        if disposition["status"] != target:
            raise ValueError("FinalDisposition status does not match target state")
    if target in {"HUMAN_APPROVED", "HUMAN_REJECTED", "MORE_INFO_REQUIRED"}:
        if context["artifacts"]["human-approval.json"] != context.get(
            "human_approval"
        ):
            raise ValueError("human approval artifact does not match approval context")
    advanced = copy.deepcopy(context)
    advanced["state"] = target
    if target == "REVISION_REQUIRED":
        advanced["revision_cycle"] += 1
    if target in {"CROSS_REVIEW_APPROVED", "CROSS_REVIEW_CONDITIONAL"} and (
        context["human_review_required"]
        or context["high_risk"]
        or context["external_action_requested"]
    ):
        advanced["required_next_state"] = "HUMAN_REVIEW_REQUIRED"
    else:
        advanced.pop("required_next_state", None)
    return advanced


def reset_for_material_evidence(
    workflow: Dict[str, Any], case_record: Dict[str, Any]
) -> Dict[str, Any]:
    version = case_record.get("case_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ValueError("case_version must be a positive integer")
    reset = copy.deepcopy(case_record)
    reset["case_version"] = version + 1
    reset["state"] = "INTAKE_PENDING"
    reset["artifacts"] = {}
    reset["invalidated_artifacts"] = list(workflow["version_invalidated_artifacts"])
    reset["revision_cycle"] = 0
    reset.pop("human_approval", None)
    reset.pop("authenticated_principal", None)
    reset.pop("required_next_state", None)
    return reset


def run_self_test(workflow: Dict[str, Any]) -> Dict[str, Any]:
    case_context = {
        "case_id": "SELF-TEST-001",
        "case_version": 1,
        "tax_date": "2026-01-01",
        "review_date": "2026-01-02",
        "revision_cycle": 0,
        "pii_masking_status": "MASKED",
        "unresolved_severities": [],
        "human_review_required": False,
        "high_risk": False,
        "external_action_requested": False,
        "artifacts": {},
    }
    steps = [
        ("NEW", "INTAKE_PENDING", "coordinator"),
        ("INTAKE_PENDING", "READY_FOR_DRAFT", "coordinator"),
        ("READY_FOR_DRAFT", "DRAFTED", "tax-preparer"),
        ("DRAFTED", "INDEPENDENT_REVIEW_IN_PROGRESS", "coordinator"),
        ("INDEPENDENT_REVIEW_IN_PROGRESS", "INDEPENDENTLY_REVIEWED", "tax-reviewer"),
        ("INDEPENDENTLY_REVIEWED", "REVIEW_ISSUED", "tax-reviewer"),
        ("REVIEW_ISSUED", "CROSS_REVIEW_APPROVED", "tax-reviewer"),
    ]
    for current, target, actor in steps:
        validate_transition(workflow, current, target, actor, case_context)

    unauthorized_rejected = False
    try:
        rejected_context = copy.deepcopy(case_context)
        rejected_context["human_review_required"] = True
        validate_transition(
            workflow,
            "HUMAN_REVIEW_REQUIRED",
            "HUMAN_APPROVED",
            "authorized_tax_professional",
            rejected_context,
        )
    except ValueError:
        unauthorized_rejected = True
    if not unauthorized_rejected:
        raise AssertionError("approval without an authenticated record was not rejected")
    return {
        "final_state": steps[-1][1],
        "unauthorized_approval_rejected": unauthorized_rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    workflow = load_workflow(args.workflow)
    if args.self_test:
        print(json.dumps(run_self_test(workflow), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
