import json
import importlib
import unittest
import re
import copy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_IDS = ("coordinator", "tax-preparer", "tax-reviewer")
FORBIDDEN_ACTIONS = {
    "file_tax_return",
    "pay_tax",
    "submit_document",
    "sign_document",
    "contact_third_party",
    "execute_transaction",
}
SCHEMA_FILES = (
    "case-packet.schema.json",
    "draft-opinion.schema.json",
    "independent-review.schema.json",
    "review-memo.schema.json",
    "response-matrix.schema.json",
    "final-disposition.schema.json",
    "human-approval.schema.json",
)


class AgentPackageTests(unittest.TestCase):
    def load_config(self, agent_id: str) -> dict:
        config_path = ROOT / "agents" / agent_id / "config.json"
        return json.loads(config_path.read_text(encoding="utf-8"))

    def test_agent_packages_exist(self):
        for agent_id in AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                package = ROOT / "agents" / agent_id
                self.assertTrue((package / "config.json").is_file())
                self.assertTrue((package / "instructions.md").is_file())

    def test_configs_link_to_shared_skill_and_instructions(self):
        shared_skill = ROOT / "skills" / "korean-inheritance-gift-tax" / "SKILL.md"
        self.assertTrue(shared_skill.is_file())

        for agent_id in AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                config = self.load_config(agent_id)
                self.assertEqual(agent_id, config["id"])
                self.assertTrue(config["display_name"].strip())
                self.assertEqual(
                    "skills/korean-inheritance-gift-tax/SKILL.md",
                    config["shared_skill"],
                )
                instructions = ROOT / config["instructions_file"]
                self.assertTrue(instructions.is_file())
                self.assertTrue(instructions.read_text(encoding="utf-8").strip())
                self.assertIsInstance(config["output_schemas"], list)
                self.assertTrue(config["output_schemas"])

    def test_only_coordinator_can_write_workflow_state(self):
        writers = []
        for agent_id in AGENT_IDS:
            config = self.load_config(agent_id)
            if "workflow-state.json" in config["writes"]:
                writers.append(agent_id)
        self.assertEqual(["coordinator"], writers)

    def test_reviewer_blind_phase_cannot_read_draft(self):
        reviewer = self.load_config("tax-reviewer")
        self.assertEqual([], reviewer["reads"])
        self.assertNotIn(
            "draft-opinion.json",
            reviewer["phase_reads"]["BLIND_REVIEW"],
        )
        self.assertIn(
            "draft-opinion.json",
            reviewer["phase_reads"]["COMPARISON_REVIEW"],
        )

    def test_every_role_forbids_external_tax_actions(self):
        for agent_id in AGENT_IDS:
            with self.subTest(agent_id=agent_id):
                config = self.load_config(agent_id)
                self.assertTrue(
                    FORBIDDEN_ACTIONS.issubset(set(config["forbidden_actions"]))
                )


class SchemaContractTests(unittest.TestCase):
    def load_schema(self, filename: str) -> dict:
        path = ROOT / "schemas" / filename
        return json.loads(path.read_text(encoding="utf-8"))

    def test_agent_output_schema_paths_exist(self):
        for agent_id in AGENT_IDS:
            config_path = ROOT / "agents" / agent_id / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            for schema_path in config["output_schemas"]:
                with self.subTest(agent_id=agent_id, schema_path=schema_path):
                    self.assertTrue((ROOT / schema_path).is_file())

    def test_schemas_use_strict_draft_2020_12_objects(self):
        for filename in SCHEMA_FILES:
            with self.subTest(filename=filename):
                schema = self.load_schema(filename)
                self.assertEqual(
                    "https://json-schema.org/draft/2020-12/schema",
                    schema["$schema"],
                )
                self.assertEqual("object", schema["type"])
                self.assertFalse(schema["additionalProperties"])
                self.assertTrue(schema["$id"].startswith("https://tax-agent.local/"))
                self.assertTrue(schema["title"].strip())

    def test_every_artifact_has_case_identity_and_dates(self):
        identity = {"case_id", "case_version", "tax_date", "review_date"}
        for filename in SCHEMA_FILES:
            with self.subTest(filename=filename):
                schema = self.load_schema(filename)
                self.assertTrue(identity.issubset(set(schema["required"])))
                self.assertTrue(identity.issubset(set(schema["properties"])))

    def test_review_memo_finding_contract(self):
        schema = self.load_schema("review-memo.schema.json")
        finding = schema["properties"]["findings"]["items"]
        required = {
            "review_id",
            "severity",
            "issue_type",
            "preparer_position",
            "reviewer_position",
            "difference_cause",
            "official_source",
            "required_action",
        }
        self.assertTrue(required.issubset(set(finding["required"])))
        self.assertEqual(
            ["BLOCKER", "MAJOR", "MINOR", "NOTE"],
            finding["properties"]["severity"]["enum"],
        )

    def test_final_disposition_has_only_cross_review_outcomes(self):
        schema = self.load_schema("final-disposition.schema.json")
        self.assertEqual(
            [
                "CROSS_REVIEW_APPROVED",
                "CROSS_REVIEW_CONDITIONAL",
                "CROSS_REVIEW_REJECTED",
                "HUMAN_JUDGMENT_REQUIRED",
            ],
            schema["properties"]["status"]["enum"],
        )

    def test_human_approval_requires_authority_and_scope(self):
        schema = self.load_schema("human-approval.schema.json")
        required = {
            "authorized_reviewer_id",
            "credential_verified",
            "approval_scope",
            "approved_at",
            "conditions",
        }
        self.assertTrue(required.issubset(set(schema["required"])))

    def test_every_nested_object_schema_is_strict(self):
        def walk(node, path="$"):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(
                        False,
                        node.get("additionalProperties"),
                        f"non-strict object schema at {path}",
                    )
                for key, value in node.items():
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    walk(value, f"{path}[{index}]")

        for filename in SCHEMA_FILES:
            with self.subTest(filename=filename):
                walk(self.load_schema(filename))

    def test_substantive_arrays_and_strings_have_quality_floors(self):
        draft = self.load_schema("draft-opinion.schema.json")
        self.assertEqual(1, draft["properties"]["legal_issues"]["minItems"])
        self.assertEqual(1, draft["properties"]["calculation"]["properties"]["inputs"]["minItems"])
        independent = self.load_schema("independent-review.schema.json")
        self.assertEqual(1, independent["properties"]["official_sources"]["minItems"])

    def test_official_sources_use_shared_provenance_definition(self):
        common_path = ROOT / "schemas" / "common-definitions.schema.json"
        common = json.loads(common_path.read_text(encoding="utf-8"))
        required = {
            "source_id",
            "title",
            "law",
            "article",
            "effective_date",
            "verified_at",
            "url",
            "excerpt",
            "content_hash",
            "snapshot_id",
        }
        self.assertTrue(
            required.issubset(
                set(common["$defs"]["official_source"]["required"])
            )
        )


class WorkflowContractTests(unittest.TestCase):
    def case_context(self, **overrides):
        context = {
            "case_id": "CASE-001",
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
        context.update(overrides)
        return context

    def official_source(self):
        return {
            "source_id": "SRC-001",
            "title": "상속세 및 증여세법",
            "law": "상속세 및 증여세법",
            "article": "제1조",
            "effective_date": "2026-01-01",
            "verified_at": "2026-01-02T10:00:00+09:00",
            "url": "https://www.law.go.kr/example",
            "excerpt": "합성 검증용 발췌",
            "content_hash": "sha256:" + "a" * 64,
            "snapshot_id": "SNAP-001",
        }

    def review_memo(self):
        return {
            "case_id": "CASE-001",
            "case_version": 1,
            "tax_date": "2026-01-01",
            "review_date": "2026-01-02",
            "findings": [
                {
                    "review_id": "R-001",
                    "severity": "MAJOR",
                    "issue_type": "CALCULATION",
                    "preparer_position": "합성 담당자 의견",
                    "reviewer_position": "합성 검수자 의견",
                    "difference_cause": "ARITHMETIC",
                    "official_source": self.official_source(),
                    "required_action": "재계산",
                }
            ],
        }

    def final_disposition(self, human_review_required=False):
        return {
            "case_id": "CASE-001",
            "case_version": 1,
            "tax_date": "2026-01-01",
            "review_date": "2026-01-02",
            "status": "CROSS_REVIEW_APPROVED",
            "agreed_items": ["합성 검증 항목"],
            "conditions": [],
            "unresolved_items": [],
            "human_review_required": human_review_required,
            "human_review_reason": "외부 실행 또는 고위험 여부에 따른 검토",
            "external_action_allowed": False,
            "artifact_id": "FD-001",
        }

    def load_module(self):
        try:
            return importlib.import_module("scripts.validate_cross_review")
        except ModuleNotFoundError:
            self.fail("scripts.validate_cross_review is not implemented")

    def load_workflow(self):
        module = self.load_module()
        path = ROOT / "workflows" / "cross-review.workflow.json"
        return module, module.load_workflow(path)

    def test_happy_path_reaches_cross_review_approved(self):
        module, workflow = self.load_workflow()
        steps = [
            ("NEW", "INTAKE_PENDING", "coordinator"),
            ("INTAKE_PENDING", "READY_FOR_DRAFT", "coordinator"),
            ("READY_FOR_DRAFT", "DRAFTED", "tax-preparer"),
            ("DRAFTED", "INDEPENDENT_REVIEW_IN_PROGRESS", "coordinator"),
            ("INDEPENDENT_REVIEW_IN_PROGRESS", "INDEPENDENTLY_REVIEWED", "tax-reviewer"),
            ("INDEPENDENTLY_REVIEWED", "REVIEW_ISSUED", "tax-reviewer"),
            ("REVIEW_ISSUED", "REVISION_REQUIRED", "coordinator"),
            ("REVISION_REQUIRED", "REVISED", "tax-preparer"),
            ("REVISED", "CROSS_REVIEW_APPROVED", "tax-reviewer"),
        ]
        for current, target, actor in steps:
            with self.subTest(current=current, target=target, actor=actor):
                module.validate_transition(
                    workflow,
                    current,
                    target,
                    actor,
                    self.case_context(
                        revision_cycle=0,
                        unresolved_severities=["MAJOR"]
                        if target == "REVISION_REQUIRED"
                        else [],
                    ),
                )

    def test_blind_review_visibility_excludes_draft(self):
        module, workflow = self.load_workflow()
        blind = workflow["artifact_visibility"]["BLIND_REVIEW"]
        comparison = workflow["artifact_visibility"]["COMPARISON_REVIEW"]
        self.assertNotIn("draft-opinion.json", blind["tax-reviewer"])
        self.assertIn("draft-opinion.json", comparison["tax-reviewer"])

        self.assertFalse(
            module.authorize_artifact_read(
                workflow, "tax-reviewer", "BLIND_REVIEW", "draft-opinion.json"
            )
        )
        self.assertTrue(
            module.authorize_artifact_read(
                workflow,
                "tax-reviewer",
                "COMPARISON_REVIEW",
                "draft-opinion.json",
            )
        )

    def test_third_revision_attempt_is_rejected(self):
        module, workflow = self.load_workflow()
        with self.assertRaises(ValueError):
            module.validate_transition(
                workflow,
                "REVIEW_ISSUED",
                "REVISION_REQUIRED",
                "coordinator",
                self.case_context(
                    revision_cycle=2, unresolved_severities=["MAJOR"]
                ),
            )

    def test_revision_counter_is_advanced_atomically(self):
        module, workflow = self.load_workflow()
        case = self.case_context(
            state="REVIEW_ISSUED",
            revision_cycle=1,
            unresolved_severities=["MAJOR"],
            artifacts={"review-memo.json": self.review_memo()},
        )
        advanced = module.advance_case(
            workflow, case, "REVISION_REQUIRED", "coordinator"
        )
        self.assertEqual(2, advanced["revision_cycle"])
        self.assertEqual("REVISION_REQUIRED", advanced["state"])
        self.assertEqual(1, case["revision_cycle"])

    def test_unknown_transition_is_rejected(self):
        module, workflow = self.load_workflow()
        with self.assertRaises(ValueError):
            module.validate_transition(
                workflow,
                "NEW",
                "HUMAN_APPROVED",
                "coordinator",
                self.case_context(human_review_required=True),
            )

    def test_only_authorized_tax_professional_can_approve(self):
        module, workflow = self.load_workflow()
        workflow = copy.deepcopy(workflow)
        workflow["authorized_reviewers"] = [
            {
                "reviewer_id": "demo-tax-pro-001",
                "credential_verified": True,
                "allowed_scopes": ["FINAL_REPORT"],
            }
        ]
        approval = {
            "case_id": "CASE-001",
            "case_version": 1,
            "tax_date": "2026-01-01",
            "review_date": "2026-01-02",
            "authorized_reviewer_id": "demo-tax-pro-001",
            "credential_verified": True,
            "approval_scope": ["FINAL_REPORT"],
            "approved_at": "2026-01-02T12:00:00+09:00",
            "conditions": [],
            "decision": "APPROVED",
            "artifact_id": "HA-001",
        }
        authorized = self.case_context(
            human_review_required=True,
            authenticated_principal={
                "reviewer_id": "demo-tax-pro-001",
                "authentication_verified": True,
            },
            human_approval=approval,
        )
        module.validate_transition(
            workflow,
            "HUMAN_REVIEW_REQUIRED",
            "HUMAN_APPROVED",
            "authorized_tax_professional",
            authorized,
        )
        with self.assertRaises(ValueError):
            module.validate_transition(
                workflow,
                "HUMAN_REVIEW_REQUIRED",
                "HUMAN_APPROVED",
                "authorized_tax_professional",
                self.case_context(human_review_required=True),
            )

    def test_blocker_cannot_enter_cross_review_approved(self):
        module, workflow = self.load_workflow()
        with self.assertRaises(ValueError):
            module.validate_transition(
                workflow,
                "REVIEW_ISSUED",
                "CROSS_REVIEW_APPROVED",
                "tax-reviewer",
                self.case_context(unresolved_severities=["BLOCKER"]),
            )

    def test_unmasked_pii_cannot_enter_drafting(self):
        module, workflow = self.load_workflow()
        with self.assertRaises(ValueError):
            module.validate_transition(
                workflow,
                "INTAKE_PENDING",
                "READY_FOR_DRAFT",
                "coordinator",
                self.case_context(pii_masking_status="REJECTED_UNMASKED"),
            )

    def test_high_risk_case_requires_human_review_after_disposition(self):
        module, workflow = self.load_workflow()
        case = self.case_context(
            state="CROSS_REVIEW_APPROVED",
            high_risk=True,
            human_review_required=True,
            artifacts={
                "final-disposition.json": self.final_disposition(
                    human_review_required=True
                )
            },
        )
        advanced = module.advance_case(
            workflow, case, "HUMAN_REVIEW_REQUIRED", "coordinator"
        )
        self.assertEqual("HUMAN_REVIEW_REQUIRED", advanced["state"])

    def test_malformed_workflow_fails_closed(self):
        module, workflow = self.load_workflow()
        malformed = copy.deepcopy(workflow)
        malformed["transitions"][0]["actors"] = "coordinator"
        path = ROOT / "tests" / "_malformed-workflow.json"
        try:
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaises(ValueError):
                module.load_workflow(path)
        finally:
            path.unlink(missing_ok=True)

    def test_case_context_and_version_are_required(self):
        module, workflow = self.load_workflow()
        with self.assertRaises(ValueError):
            module.validate_transition(
                workflow, "NEW", "INTAKE_PENDING", "coordinator", None
            )
        with self.assertRaises(ValueError):
            module.validate_transition(
                workflow,
                "NEW",
                "INTAKE_PENDING",
                "coordinator",
                {"case_id": "CASE-001"},
            )

    def test_case_bundle_rejects_stale_or_missing_responses(self):
        module, workflow = self.load_workflow()
        case = self.case_context()
        memo = self.review_memo()
        matrix = {
            "case_id": "CASE-001",
            "case_version": 2,
            "tax_date": "2026-01-01",
            "review_date": "2026-01-02",
            "revision_cycle": 1,
            "responses": [],
        }
        with self.assertRaises(ValueError):
            module.validate_case_bundle(
                workflow,
                case,
                {"review-memo.json": memo, "response-matrix.json": matrix},
            )

    def test_case_bundle_accepts_consistent_review_responses(self):
        module, workflow = self.load_workflow()
        case = self.case_context()
        matrix = {
            "case_id": "CASE-001",
            "case_version": 1,
            "tax_date": "2026-01-01",
            "review_date": "2026-01-02",
            "revision_cycle": 1,
            "responses": [
                {
                    "review_id": "R-001",
                    "disposition": "ACCEPT",
                    "modification": "계산을 수정함",
                    "additional_evidence": [],
                    "remaining_uncertainty": "없음",
                }
            ],
        }
        module.validate_case_bundle(
            workflow,
            case,
            {
                "review-memo.json": self.review_memo(),
                "response-matrix.json": matrix,
            },
        )

    def test_advance_case_requires_target_artifacts(self):
        module, workflow = self.load_workflow()
        case = self.case_context(state="REVIEW_ISSUED")
        with self.assertRaises(ValueError):
            module.advance_case(
                workflow, case, "CROSS_REVIEW_APPROVED", "tax-reviewer"
            )

    def test_advance_case_rejects_mismatched_disposition(self):
        module, workflow = self.load_workflow()
        disposition = self.final_disposition()
        disposition["status"] = "CROSS_REVIEW_CONDITIONAL"
        case = self.case_context(
            state="REVIEW_ISSUED",
            artifacts={"final-disposition.json": disposition},
        )
        with self.assertRaises(ValueError):
            module.advance_case(
                workflow, case, "CROSS_REVIEW_APPROVED", "tax-reviewer"
            )

    def test_high_risk_approval_sets_mandatory_next_state(self):
        module, workflow = self.load_workflow()
        case = self.case_context(
            state="REVIEW_ISSUED",
            high_risk=True,
            human_review_required=True,
            artifacts={
                "final-disposition.json": self.final_disposition(
                    human_review_required=True
                )
            },
        )
        advanced = module.advance_case(
            workflow, case, "CROSS_REVIEW_APPROVED", "tax-reviewer"
        )
        self.assertEqual("HUMAN_REVIEW_REQUIRED", advanced["required_next_state"])


class ExecutableEvaluationTests(unittest.TestCase):
    """Execute deterministic security fixtures; model-quality cases run later."""

    def setUp(self):
        self.module = importlib.import_module("scripts.validate_cross_review")
        self.workflow = self.module.load_workflow(
            ROOT / "workflows" / "cross-review.workflow.json"
        )
        self.categories = {
            case["category"]
            for case in json.loads(
                (ROOT / "evals" / "cross-review-cases.json").read_text(
                    encoding="utf-8"
                )
            )
        }

    def context(self, **overrides):
        value = {
            "case_id": "EVAL-CASE",
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
        value.update(overrides)
        return value

    def test_unmasked_pii_fixture_executes_stop(self):
        self.assertIn("unmasked_pii", self.categories)
        with self.assertRaises(ValueError):
            self.module.validate_transition(
                self.workflow,
                "INTAKE_PENDING",
                "READY_FOR_DRAFT",
                "coordinator",
                self.context(pii_masking_status="REJECTED_UNMASKED"),
            )

    def test_unresolved_blocker_fixture_executes_escalation(self):
        self.assertIn("unresolved_blocker", self.categories)
        self.assertEqual(
            "HUMAN_JUDGMENT_REQUIRED",
            self.module.next_state_after_review(
                self.workflow, 2, ["BLOCKER"]
            ),
        )

    def test_human_approval_spoofing_fixture_executes_rejection(self):
        self.assertIn("human_approval_spoofing", self.categories)
        with self.assertRaises(ValueError):
            self.module.validate_transition(
                self.workflow,
                "HUMAN_REVIEW_REQUIRED",
                "HUMAN_APPROVED",
                "authorized_tax_professional",
                self.context(human_review_required=True),
            )

    def test_new_evidence_fixture_executes_invalidation(self):
        self.assertIn("new_evidence_versioning", self.categories)
        reset = self.module.reset_for_material_evidence(
            self.workflow,
            self.context(
                state="CROSS_REVIEW_APPROVED",
                artifacts={"final-disposition.json": {"old": True}},
            ),
        )
        self.assertEqual(2, reset["case_version"])
        self.assertEqual("INTAKE_PENDING", reset["state"])
        self.assertEqual({}, reset["artifacts"])

    def test_blind_review_fixture_executes_capability_denial(self):
        self.assertIn("blind_review_isolation", self.categories)
        self.assertFalse(
            self.module.authorize_artifact_read(
                self.workflow,
                "tax-reviewer",
                "BLIND_REVIEW",
                "draft-opinion.json",
            )
        )

    def test_material_evidence_resets_version_and_artifacts(self):
        case_record = {
            "case_version": 2,
            "state": "CROSS_REVIEW_APPROVED",
            "artifacts": {
                "case-packet.json": "keep",
                "draft-opinion.json": "old",
                "independent-review.json": "old",
                "review-memo.json": "old",
                "response-matrix.json": "old",
                "final-disposition.json": "old",
            },
        }
        reset = self.module.reset_for_material_evidence(self.workflow, case_record)
        self.assertEqual(3, reset["case_version"])
        self.assertEqual("INTAKE_PENDING", reset["state"])
        self.assertEqual({}, reset["artifacts"])
        self.assertEqual(
            sorted(self.workflow["version_invalidated_artifacts"]),
            sorted(reset["invalidated_artifacts"]),
        )

    def test_unresolved_major_after_cycle_two_requires_human(self):
        self.assertEqual(
            "HUMAN_JUDGMENT_REQUIRED",
            self.module.next_state_after_review(self.workflow, 2, ["MAJOR"]),
        )
        self.assertEqual(
            "CROSS_REVIEW_APPROVED",
            self.module.next_state_after_review(self.workflow, 1, []),
        )


class EvaluationContractTests(unittest.TestCase):
    REQUIRED_CATEGORIES = {
        "direct_invocation",
        "implicit_invocation",
        "negative_control",
        "missing_material_facts",
        "outdated_law_pressure",
        "prompt_injection",
        "unmasked_pii",
        "unauthorized_filing",
        "unlawful_backdating",
        "blind_review_isolation",
        "calculation_mismatch",
        "new_evidence_versioning",
        "unresolved_blocker",
        "human_approval_spoofing",
        "high_risk_escalation",
    }

    def load_cases(self):
        path = ROOT / "evals" / "cross-review-cases.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_has_at_least_fifteen_unique_cases(self):
        cases = self.load_cases()
        self.assertGreaterEqual(len(cases), 15)
        ids = [case["id"] for case in cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_required_evaluation_categories_are_covered(self):
        cases = self.load_cases()
        categories = {case["category"] for case in cases}
        self.assertTrue(self.REQUIRED_CATEGORIES.issubset(categories))

    def test_every_case_has_observable_expectations(self):
        for case in self.load_cases():
            with self.subTest(case_id=case["id"]):
                self.assertTrue(case["prompt"].strip())
                self.assertTrue(case["expected_route"])
                self.assertTrue(case["expected_stops"])
                self.assertTrue(case["required_checks"])

    def test_fixtures_contain_no_resident_registration_number(self):
        serialized = json.dumps(self.load_cases(), ensure_ascii=False)
        self.assertIsNone(re.search(r"\b\d{6}-?\d{7}\b", serialized))


if __name__ == "__main__":
    unittest.main()
