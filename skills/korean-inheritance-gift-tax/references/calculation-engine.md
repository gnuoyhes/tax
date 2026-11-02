# 계산 엔진 사용법

## 원칙

`scripts/tax_calculator.py`는 산술과 일관성만 검증한다. 세율, 누진공제, 공제한도, 세액공제율을 내장하지 않는다. 법률 판단이 잘못되면 계산이 정확해도 결론은 잘못되므로, 먼저 [source-verification.md](source-verification.md)를 완료한다.

## 입력 분리

- **사건 입력 JSON:** 사건 ID, 과세 기준일, 재산·가산·채무·비과세, 실제 적용할 공제, 조정 규칙, 별도 세금
- **법률 파라미터 JSON:** 세율 구간, 누진공제, 공제한도, 세액공제·할증·가산세 규칙과 각 규칙의 출처·시행일·확인일

초안은 [case-input.template.json](../assets/templates/case-input.template.json)과 [legal-parameters.template.json](../assets/templates/legal-parameters.template.json)을 복사해 작성한다. 템플릿의 빈 값은 공식 확인 전에는 채우지 않는다.

## 실행

```bash
python3 scripts/tax_calculator.py \
  --case <case-input.json> \
  --params <legal-parameters.json> \
  --out <calculation-result.json>
```

금액 단위는 정수 원(`KRW`)만 허용한다. 억원·만원 단위 자료는 사건 입력 전에 원으로 변환하고 변환 근거를 계산 결과표에 기록한다.

## 엔진이 강제하는 검사

- 사건 ID와 과세 기준일 존재
- 사건 세목과 법률 파라미터 세목 일치
- 모든 법률 파라미터의 출처·시행일·확인일 존재
- 법률 파라미터의 효력기간이 과세 기준일을 포함
- 구간별 누진계산과 누진공제 방식의 결과 일치
- 동일 공제·조정의 중복 적용 금지
- 출처가 연결된 `deduction_groups`의 상호배타(`max_rules`) 및 합산한도(`aggregate_limit`) 검사
- 공제 한도 초과 금지
- 음수 과세가액·과세표준·최종세액의 0 보정과 경고
- 원 이외 단위 거부
- 소수 원 산출 거부: 공식 절사·반올림 규칙을 구현·테스트하기 전에는 결과를 확정하지 않음
- 증여세·상속세 본세와 양도소득세·취득세·외국세 등의 별도 표시

`deduction_groups`의 각 그룹도 법률 파라미터이므로 출처·시행일·확인일이 필요하다. `rules`에는 그룹에 속한 공제 규칙 ID를 나열하고, 필요에 따라 동시에 적용 가능한 수인 `max_rules`와 합산 한도인 `aggregate_limit`을 둔다.

## 결과 해석

`method_check.matches`가 `true`가 아니면 결과를 사용하지 않는다. `fractional_krw_result`가 발생하면 임의 반올림하지 말고 적용 법령의 절사·반올림 시점과 단위를 확인한 뒤 엔진 규칙과 테스트를 먼저 추가한다. `warnings`가 있으면 계산 결과표와 최종 의견서에 그대로 옮기고 원인을 검토한다. `other_taxes_total`은 참고 합계이며 `primary_tax_total`에 포함되지 않는다.

## 변경 이력

입력 또는 법률 파라미터가 바뀔 때마다 파일을 새 버전으로 저장한다. 계산 결과의 `parameter_set_id`, 사건 입력 버전, 변경 사유, 연결된 증거·출처 ID를 [calculation-result.md](../assets/templates/calculation-result.md)에 남긴다.

## 테스트

```bash
python3 -m unittest discover -s scripts/tests -v
```

테스트는 합성 숫자만 사용한다. 테스트 숫자를 실제 한국 세율·공제라고 해석하거나 사건 계산에 복사하지 않는다.
