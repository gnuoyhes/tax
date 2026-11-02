# Tax Cross-Review Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create separate coordinator, tax-preparer, and tax-reviewer agent packages with structured schemas, a bounded cross-review workflow, and evaluation fixtures that enforce blind review and human approval boundaries.

**Architecture:** Keep `korean-inheritance-gift-tax` as the shared domain skill and add three project-level agent definitions under `agents/`. The coordinator owns state and user-facing synthesis; the preparer and reviewer communicate only through versioned JSON artifacts governed by shared schemas and a machine-readable workflow. A dependency-free Python contract test validates prompts, configs, schemas, workflow states, and evaluation coverage.

**Tech Stack:** Markdown role instructions, JSON agent configuration, JSON Schema documents, Python 3 standard-library `unittest` contract tests.

**Spec:** `/Users/gnuoyhes/Desktop/dev/tax/docs/superpowers/specs/2026-11-03-tax-cross-review-agent-design.md`

## Global Constraints

- The existing `skills/korean-inheritance-gift-tax` skill remains the single shared tax-domain source; do not duplicate its tax guidance into role prompts.
- The reviewer must complete `IndependentReview` before the coordinator reveals `DraftOpinion`.
- Revision and re-review are limited to two cycles.
- AI agents cannot create `HUMAN_APPROVED`; only a pre-authorized actual tax professional can create that record.
- No agent may file, pay, submit, sign, contact a third party, or execute a transaction.
- The first version accepts masked evidence only and stops when raw sensitive identifiers are detected.
- The repository currently has no Git metadata, so commit steps are recorded as checkpoints and cannot be executed until Git is initialized.

## Review Focus

- A reviewer configuration that can read the draft during blind review must fail contract validation; Task 1 adds this test.
- An unknown or invalid workflow transition must fail closed; Task 3 adds transition tests.
- A user statement that looks like approval must not create `HUMAN_APPROVED`; Task 3 adds authority tests.
- A new material evidence version must invalidate all draft and review artifacts; Task 3 adds version-reset tests.
- Evaluation data must include prompt injection, missing facts, unmasked PII, unauthorized action, and correlated calculation error; Task 4 adds coverage checks.

---

### Task 1: Agent packages and role boundaries

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_agent_contracts.py`
- Create: `agents/coordinator/instructions.md`
- Create: `agents/coordinator/config.json`
- Create: `agents/tax-preparer/instructions.md`
- Create: `agents/tax-preparer/config.json`
- Create: `agents/tax-reviewer/instructions.md`
- Create: `agents/tax-reviewer/config.json`

**Interfaces:**
- Consumes: shared skill at `skills/korean-inheritance-gift-tax/SKILL.md` and the approved design spec.
- Produces: three agent configs with `id`, `display_name`, `instructions_file`, `shared_skill`, `reads`, `writes`, `forbidden_actions`, and `output_schemas` fields.

- [ ] **Step 1: Write failing agent-package tests**

Add `AgentPackageTests` using `unittest` that asserts:

- all three config and instruction files exist;
- each config is valid JSON and references an existing instruction file;
- all configs reference `skills/korean-inheritance-gift-tax/SKILL.md`;
- coordinator is the only agent allowed to write workflow state;
- reviewer `reads` excludes `draft-opinion.json` during `INDEPENDENTLY_REVIEWED` input;
- every role forbids filing, payment, submission, signing, third-party contact, and transaction execution;
- instructions contain the role-specific non-negotiable rules from the design.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_agent_contracts.AgentPackageTests -v`  
Expected: FAIL because `agents/` files do not exist.

- [ ] **Step 3: Create minimal agent configs**

Create each `config.json` with the exact fields in Interfaces. Use project-relative paths. The reviewer config must separate `blind_review_reads` from `comparison_review_reads` so the blind phase cannot include the draft.

- [ ] **Step 4: Create focused role instructions**

Move the three role prompt contracts from spec §15 into separate instruction files. Add exact input artifacts, output artifacts, stop conditions, maximum revision count, and the prohibition against creating human approval. Do not repeat tax intake or law-research details already owned by the shared skill.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python3 -m unittest tests.test_agent_contracts.AgentPackageTests -v`  
Expected: PASS.

- [ ] **Step 6: Checkpoint**

Record that Task 1 is complete in this plan. Git commit is unavailable because the directory is not a Git repository.

### Task 2: Structured artifact schemas

**Files:**
- Modify: `tests/test_agent_contracts.py`
- Create: `schemas/case-packet.schema.json`
- Create: `schemas/draft-opinion.schema.json`
- Create: `schemas/independent-review.schema.json`
- Create: `schemas/review-memo.schema.json`
- Create: `schemas/response-matrix.schema.json`
- Create: `schemas/final-disposition.schema.json`
- Create: `schemas/human-approval.schema.json`

**Interfaces:**
- Consumes: role outputs named in Task 1 configs.
- Produces: JSON Schema Draft 2020-12 documents with stable `$id`, `title`, `type`, `required`, `properties`, and `additionalProperties: false` at the root.

- [ ] **Step 1: Write failing schema-contract tests**

Add `SchemaContractTests` that asserts:

- every config `output_schemas` path exists;
- all seven schema documents parse as JSON and declare Draft 2020-12;
- root objects disallow unspecified properties;
- required identity fields include `case_id`, `case_version`, `tax_date`, and `review_date` where relevant;
- `ReviewMemo` findings require `review_id`, severity, issue type, preparer position, reviewer position, difference cause, official source, and required action;
- `FinalDisposition` limits status to the four cross-review outcomes in spec §10.6;
- `HumanApproval` requires an authorized reviewer ID, credential verification status, case version, scope, timestamp, and conditions.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_agent_contracts.SchemaContractTests -v`  
Expected: FAIL because `schemas/` files do not exist.

- [ ] **Step 3: Create the seven minimal schemas**

Implement only the fields defined in spec §14 and §23. Use string enums for statuses and severities; use arrays for facts, assumptions, sources, findings, and unresolved issues; use string decimal amounts rather than binary floating-point numbers.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python3 -m unittest tests.test_agent_contracts.SchemaContractTests -v`  
Expected: PASS.

- [ ] **Step 5: Checkpoint**

Record Task 2 completion; Git commit remains unavailable.

### Task 3: Bounded cross-review workflow and state validation

**Files:**
- Modify: `tests/test_agent_contracts.py`
- Create: `workflows/cross-review.md`
- Create: `workflows/cross-review.workflow.json`
- Create: `scripts/__init__.py`
- Create: `scripts/validate_cross_review.py`

**Interfaces:**
- Consumes: agent IDs and schema paths from Tasks 1-2.
- Produces: `load_workflow(path: Path) -> dict`, `validate_transition(workflow: dict, current: str, target: str, actor: str) -> None`, and `reset_for_material_evidence(workflow: dict, case_record: dict) -> dict`.

- [ ] **Step 1: Write failing workflow tests**

Add `WorkflowContractTests` that asserts:

- the happy path follows the state order in spec §13;
- reviewer blind review occurs before draft disclosure;
- a third revision attempt raises `ValueError`;
- invalid or unknown transitions raise `ValueError`;
- only actor `authorized_tax_professional` can create `HUMAN_APPROVED`;
- ordinary user confirmation is rejected as approval;
- material new evidence increments `case_version`, returns to `INTAKE_PENDING`, and invalidates draft/review/final artifacts;
- `BLOCKER` or unresolved `MAJOR` after cycle two ends in `HUMAN_JUDGMENT_REQUIRED`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_agent_contracts.WorkflowContractTests -v`  
Expected: FAIL because workflow files and validator do not exist.

- [ ] **Step 3: Create machine-readable workflow**

Define agent ownership, state transitions, terminal states, revision limit `2`, artifact visibility by phase, and human-approval actor in `cross-review.workflow.json`.

- [ ] **Step 4: Implement the workflow validator**

Implement the three interfaces using only the Python standard library. Fail closed for malformed workflow data, unknown state, unknown actor, or missing case version.

- [ ] **Step 5: Document the workflow**

Create `cross-review.md` as the human-readable companion. Describe inputs, exact phase order, artifact visibility, severity handling, state transitions, version invalidation, and approval pause. Link to the machine-readable workflow and shared schemas instead of duplicating them.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `python3 -m unittest tests.test_agent_contracts.WorkflowContractTests -v`  
Expected: PASS.

- [ ] **Step 7: Checkpoint**

Record Task 3 completion; Git commit remains unavailable.

### Task 4: Evaluation fixtures and coverage validation

**Files:**
- Modify: `tests/test_agent_contracts.py`
- Create: `evals/cross-review-cases.json`
- Create: `evals/rubric.md`

**Interfaces:**
- Consumes: workflow states, agent IDs, and artifact names from Tasks 1-3.
- Produces: at least 15 synthetic evaluation cases with `id`, `category`, `prompt`, `expected_route`, `expected_stops`, and `required_checks`.

- [ ] **Step 1: Write failing evaluation-contract tests**

Add `EvaluationContractTests` that asserts:

- at least 15 unique cases exist;
- required categories include direct invocation, implicit invocation, negative control, missing material facts, outdated-law pressure, prompt injection, unmasked PII, unauthorized filing, unlawful backdating, blind-review isolation, calculation mismatch, new evidence versioning, unresolved blocker, human approval spoofing, and high-risk escalation;
- every case has an expected route, stop condition, and observable required checks;
- no fixture contains real personal identifiers.

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest tests.test_agent_contracts.EvaluationContractTests -v`  
Expected: FAIL because eval fixtures do not exist.

- [ ] **Step 3: Create synthetic evaluation cases**

Adapt the five existing tax skill cases and add the ten missing orchestration/security cases. Test workflow behavior and evidence quality, not memorized tax amounts.

- [ ] **Step 4: Create the scoring rubric**

Define must-pass checks for routing, intake gate, official-source verification, arithmetic reconciliation, reviewer independence, finding traceability, version handling, PII handling, approval enforcement, and final unresolved-issue disclosure.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python3 -m unittest tests.test_agent_contracts.EvaluationContractTests -v`  
Expected: PASS.

- [ ] **Step 6: Checkpoint**

Record Task 4 completion; Git commit remains unavailable.

### Task 5: Full contract verification

**Files:**
- Modify only if verification exposes a defect in files owned by Tasks 1-4.

**Interfaces:**
- Consumes: all implemented agent, schema, workflow, validator, and evaluation artifacts.
- Produces: a clean, repeatable standard-library test run and a validated sample transition trace.

- [ ] **Step 1: Run the complete agent contract suite**

Run: `python3 -m unittest tests.test_agent_contracts -v`  
Expected: all tests PASS with no errors.

- [ ] **Step 2: Run the existing tax calculator suite**

Run: `python3 -m unittest skills/korean-inheritance-gift-tax/scripts/tests/test_tax_calculator.py -v`  
Expected: all existing calculator tests PASS; report any pre-existing failure without hiding it.

- [ ] **Step 3: Exercise a sample state trace**

Run: `python3 scripts/validate_cross_review.py --workflow workflows/cross-review.workflow.json --self-test`  
Expected: exit `0` and a trace ending in `CROSS_REVIEW_APPROVED`, while its built-in unauthorized-approval check is rejected.

- [ ] **Step 4: Inspect the created tree**

Run: `find agents workflows schemas evals tests scripts -maxdepth 3 -type f | sort`  
Expected: every file listed in Tasks 1-4 exists and no unrelated artifacts were created.

- [ ] **Step 5: Final checkpoint**

Record commands, pass counts, and any remaining limitation. Do not claim production readiness: expert-validated tax fixtures, hard artifact access isolation, authentication, and external approval UI remain later phases.
