# 사건 관리 절차

## 1. 사건 개시와 저장 방식

실질 검토 전에 다음 두 값이 반드시 있어야 한다.

- `case_id`: 사용자가 제공한 고유 ID 또는 `PROVISIONAL-YYYYMMDD-분류-일련번호` 형식의 임시 ID
- `tax_point_date`: 증여일, 상속개시일 또는 비교 시나리오의 명시적 기준일

파일을 만들 수 있고 사용자가 사건 산출물을 요청한 경우 아래 구조를 사용한다. 그렇지 않으면 같은 표를 답변 안에서 유지한다.

```text
<case_id>/
├── 00-case-intake.md
├── 01-evidence-index.md
├── 02-source-verification-log.md
├── calculations/
│   ├── case-input-v001.json
│   ├── legal-parameters-v001.json
│   └── calculation-result-v001.json
├── 03-calculation-result.md
├── 04-expert-review-approval.md
└── 05-final-opinion.md
```

원본 증거 파일을 임의로 이동·개명·변경하지 않는다. 원본 위치를 기록하고 산출물에는 마스킹된 식별자만 사용한다.

## 2. 필수 원장

다음 템플릿을 복사해 사건별로 유지한다.

| 원장/산출물 | 템플릿 | 갱신 시점 |
|---|---|---|
| 사건 초기 접수표 | [../assets/templates/case-intake.md](../assets/templates/case-intake.md) | 최초 접수 및 중요 사실 변경 |
| 증거자료 인덱스 | [../assets/templates/evidence-index.md](../assets/templates/evidence-index.md) | 자료 수령·검토·배제·교체 시 |
| 공식 출처 확인표 | [../assets/templates/source-verification-log.md](../assets/templates/source-verification-log.md) | 법령·안내 확인 또는 버전 변경 시 |
| 계산 결과표 | [../assets/templates/calculation-result.md](../assets/templates/calculation-result.md) | 모든 계산 실행 후 |
| 전문가 검토·승인표 | [../assets/templates/expert-review-approval.md](../assets/templates/expert-review-approval.md) | 검토 요청·회신·승인·조건부 승인 시 |
| 최종 의견서 | [../assets/templates/final-opinion.md](../assets/templates/final-opinion.md) | 승인용 초안 및 승인 반영본 작성 시 |

## 3. 사실 분류 규칙

각 사실은 하나의 범주에만 둔다.

- **확인된 사실:** 독립 증거 또는 공식 조회로 확인된 내용. 증거 ID를 연결한다.
- **사용자 진술:** 사용자가 말했으나 외부 증거로 확인되지 않은 내용.
- **가정:** 시나리오 계산을 위해 임시로 둔 조건. 결과에 미치는 영향을 표시한다.
- **미확인 사실:** 확인 전에는 결론을 바꿀 수 있는 공백. 담당자와 목표일을 둔다.

사용자 진술을 확인된 사실로 승격할 때 증거 ID, 확인자, 확인일을 남긴다. 폐기된 가정은 삭제하지 말고 `폐기` 상태와 이유를 기록한다.

## 4. 버전과 변경 이력

- 계산 버전: `CALC-<case_id>-vNNN`
- 의견 버전: `OPINION-<case_id>-vNNN`
- 동일 버전을 덮어쓰지 않는다. 입력, 법률 파라미터, 계산 결과, 의견을 함께 새 버전으로 올린다.
- 변경 로그에는 이전값, 새값, 변경 이유, 근거 ID, 작성자, 검토자, 승인 상태를 기록한다.
- 법령 시행일 또는 과세 기준일이 달라지면 기존 계산을 수정하지 말고 새 파라미터 세트와 새 계산 버전을 만든다.

## 5. 사건 상태

`접수 → 자료요청 → 자료검토 → 법령확인 → 계산중 → 전문가검토 → 승인대기 → 승인/조건부승인/반려 → 종료`

다음이면 `승인대기` 이상으로 이동할 수 없다.

- 중요 미확인 사실이 남아 있음
- 공식 출처 또는 시행일 미확인
- 계산 엔진의 방법 일치 검사가 실패함
- 전문가 필수 사안의 담당 전문가가 미지정
- 개인정보 마스킹 또는 증거 충돌 검토 미완료

## 6. 사람의 승인

최종 보고서는 최소한 다음을 표시한다.

- 작성자와 작성일
- 계산·의견 버전
- 검토자 이름/역할
- 승인 상태: `미검토 / 검토중 / 조건부승인 / 승인 / 반려`
- 승인 조건과 미확인 사항
- 실행 가능 여부: 이 스킬은 항상 `외부 실행 불가`로 표시

승인은 보고서 품질에 관한 사람의 판단이다. 신고, 납부, 제출, 계약 체결 또는 외부 연락 권한을 이 스킬에 부여하지 않는다.
