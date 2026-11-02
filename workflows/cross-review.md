# 증여·상속세 교차검토 워크플로

기계 판정 기준은 [cross-review.workflow.json](cross-review.workflow.json)을 사용하고, 산출물 형식은 `schemas/`의 JSON Schema를 따른다.

실제 상태 변경은 `advance_case`로만 수행한다. 이 함수는 목표 상태의 필수 산출물, JSON Schema, 사건 식별자·버전, 검수번호 대응 관계와 정책 게이트를 모두 검사한 뒤 복사본의 상태를 변경한다. `validate_transition`은 저수준 정책 검사이며 상태를 변경하지 않는다.

## 단계

1. 조정자가 마스킹된 자료로 `case-packet.json`을 만든다.
2. 담당 세무사 AI가 `draft-opinion.json`을 작성한다.
3. 조정자가 `INDEPENDENT_REVIEW_IN_PROGRESS`로 전환한 뒤, 검수 세무사 AI는 초안을 보지 않고 `independent-review.json`을 작성한다.
4. 조정자가 독립 검수 완료를 확인한 후에만 초안을 공개한다.
5. 검수 세무사 AI가 차이를 `review-memo.json`으로 작성한다.
6. 담당 세무사 AI가 각 `review_id`에 답하고 `response-matrix.json`과 수정 초안을 만든다.
7. 검수 세무사 AI가 `final-disposition.json`을 작성한다.
8. 고위험 사건, 미해결 중요 지적 또는 외부 실행은 실제 세무사 승인 단계에서 멈춘다.

## 가시성

독립 검수 단계의 검수자는 `case-packet.json`만 읽을 수 있다. 증거 인덱스는 CasePacket 안에 포함하고 공식 출처는 검수자가 독립적으로 조사한다. `draft-opinion.json`은 `independent-review.json`이 완료된 뒤 비교 검수 단계에서 공개한다. 실제 파일 요청은 `BLIND_REVIEW`, `COMPARISON_REVIEW`, `FINAL_REVIEW` capability와 `authorize_artifact_read`로 검사한다.

## 회차와 중단

- 담당 수정과 재검수는 최대 2회다.
- 2회 후 `BLOCKER` 또는 `MAJOR`가 남으면 `HUMAN_JUDGMENT_REQUIRED`다.
- 중요 증거가 추가되면 사건 버전을 올리고 `INTAKE_PENDING`으로 되돌린다. 이전 초안과 검수 결과는 무효화한다.
- 법령 출처를 확인할 수 없거나 계산이 일치하지 않으면 각각 `BLOCKED_SOURCE_UNAVAILABLE`, `BLOCKED_CALCULATION_MISMATCH`로 중단한다.
- `pii_masking_status`가 `MASKED`가 아니면 `BLOCKED_UNMASKED_PII`로 중단하며 담당자나 검수자를 호출하지 않는다.

## 사람 승인

AI는 `HUMAN_APPROVED`를 만들 수 없다. 워크플로의 승인자 명부에 사전 등록되고 인증된 실제 세무사가 동일 사건 버전의 `human-approval.json`을 제출해야 한다. 기본 명부는 비어 있어 등록 전에는 어떤 승인도 통과하지 않는다. 사용자의 일반 확인, 사전 포괄승인 또는 두 AI의 합의는 이를 대신하지 않는다.

신고, 납부, 제출, 서명, 제3자 연락 및 거래 실행은 사람 승인 전에는 허용되지 않는다.
