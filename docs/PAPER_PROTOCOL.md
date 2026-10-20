# LLM 비교 실험: 고정 조건과 실행 상태

arXiv:2606.27154v2를 참조한 [세 방법의 실측 비교와 지표 대응표](THREE_WAY_COMPARISON_KO.md)는 별도 문서입니다. 현재 진단 점수를 논문 원인 집합 EM·F1로 간주하지 않으며, HF 원래 조사 루프 실험의 진행 및 집계를 기존 요약문 실험과 구분합니다.

이 문서는 원래 6개 API 모델의 672회 비교 계획입니다. 별도의 단일 HF 경량 모델 실험 56회는 완료했으며, [실측 결과와 출력 계약 실패](MEASUREMENT_HF_KO.md)에 기록합니다. 두 실험의 모델과 분모를 합치지 않습니다.

현재 protocol은 **`logagent-matched-llm-v2`**입니다. LogAgent가 먼저 후보를 선별한 후 원래 LLM 도구 루프를 실행합니다. 이전 v1의 선택적 `query_rca_threads` 도구는 제거했습니다. v1은 모델 호출 0회였고, 기존 HF 실측 56회는 원래 도구 루프를 사용하지 않은 별도 실험으로 보존합니다. [처리 순서와 원저장소 대비표](UPSTREAM_PIPELINE_KO.md)를 참고하십시오.

원래 6개 모델 실험 상태: **구현·계약 테스트 완료, 해당 모델 설정의 실제 호출 0회**. API 키, 고정 GreptimeDB release build, Docker와 실행 시점 가격 스냅샷이 없어 실행 전 점검에서 중단됩니다. `experiments/environment_check.json`이 실제 점검 결과입니다. 이 6개 모델 재실행의 정확도와 비용은 `null`이며 Python의 90%를 LLM 성능으로 복사하지 않습니다. 별도 HF 실측은 위 링크에서 확인할 수 있습니다.

## 비교할 네 조건

| 조건 | 원저장소 코드 | LLM에 제공하는 인터페이스 |
|---|---|---|
| Split | 원래 `run_split_agent` | Prometheus·Loki·Tempo |
| Raw | 원래 `run_agent` | GreptimeDB SQL·PromQL |
| Graph | 원래 `run_agent` | Raw + 원래 Semantic Graph 도구 |
| LogAgent | 후보 선별 후 같은 구조화 API runner | 같은 Raw 도구 + 첫 입력의 상위 5개 후보 문맥 |

주 비교는 같은 모델의 **LogAgent vs Raw**입니다. LogAgent vs Graph는 별도로 보고하고, 과거 공개 결과는 참고값으로만 둡니다. LogAgent는 Python의 T1~T4·실측 ontology·가설·Thread 점수로 먼저 상위 5개 후보를 선별합니다. 기존 engine과 가설 설정은 바꾸지 않았습니다. 선별은 정답 파일 접근을 차단한 별도 프로세스에서 실행하며, 원래 incident prompt 뒤에 후보 문맥을 추가합니다. Python의 `diagnosis`나 `selected_thread`를 확정 답으로 전달하지 않습니다.

후보는 탐색 안내이며 인용 근거로 인정하지 않습니다. LLM은 같은 Raw SQL/PromQL 도구로 검증하고, 후보를 기각하거나 후보 밖의 원인을 조사할 수 있습니다. 후보가 0개여도 원래 조사를 계속합니다. 선별은 첫 모델 호출 전에 실행하므로 조사 도구 48회를 차감하지 않습니다. 대신 Python 선별 시간을 전체 `elapsed_seconds`에 포함하고 `architecture_build_seconds`, 후보 수·해시, LLM 시간도 별도로 기록합니다. 따라서 효율 비교는 추가 전처리 비용까지 포함하는 전체 파이프라인 비교입니다.

이는 원본 LogAgent 운영 코드에서 LLM이 보고서만 작성하던 역할과 다른, 사용자가 요청한 **후보 선별 + 원래 LLM 조사 방식의 연구용 treatment**입니다. 같은 LLM이 근거 조회와 최종 진단을 수행합니다. 비교 대상은 후보 전처리와 전달 문맥을 추가한 전체 방식이며 후보 순위 알고리즘만의 효과를 분리한 실험은 아닙니다.

## 동일하게 고정하는 항목

- Benchmark commit: `fdfbca65c87c36c6b06bddfa6d611544f13bfa34`.
- GreptimeDB revision: `15317a131bc63a680d3571e5f681bee4acc86228`, release build.
- 데이터: 원래 고정 선택 fixture의 OpenRCA2 10개 사례, RCA100 v1.1 4개 사례와 원래 시각·identity·원본 파일 해시.
- 모델: 원래 protocol의 6개 설정. 모델명, provider transport, reasoning effort, cache 정책을 임의로 대체하지 않습니다.
- 최대 도구 호출 48회, 최대 턴 58회, 응답당 출력 상한 16,384 tokens, provider 기본 sampling, seed 전송 없음.
- Raw·Graph·LogAgent의 system prompt는 byte-identical한 원본 함수를 사용합니다. LogAgent의 조사 도구는 Raw와 동일합니다. incident prompt의 원본 바이트는 그대로 보존하고 LogAgent 조건에만 후보 문맥을 덧붙이므로 전체 user prompt와 입력 토큰 수는 다릅니다. Split의 store 사용 설명은 원저장소의 차이를 유지합니다.
- 최종 답은 원래 `Diagnosis`, `submit_diagnosis`, 인용 검증을 사용합니다. 잘못된 형식·인용은 원래 루프에서 모델에 오류를 돌려주며 58턴 안에서 새 제출을 허용합니다. 실행이 끝난 답을 사후 보정하거나 채점 결과를 보고 재시도하지 않습니다.
- 원래 `execute_transfer_cell`과 `evaluate_transfer_run`을 재사용합니다. 원인·인용·근거 검증 조건을 완화하지 않습니다.
- 원래 데이터 적재·identity·시간창·raw/graph 일치·Tempo 가시성·split 데이터 동등성 gate를 통과해야 모델을 호출합니다.
- 각 모델·사례·조건 2회씩, 총 **6×14×4×2 = 672개 cell**을 계획했습니다.
- 원저장소와 같은 데이터셋별 합산 분모는 **각 arm의 OpenRCA2 120회(6×10×2), RCA100 48회(6×4×2)**입니다. `summary_by_dataset`에 과거 공개 참고값과 새 실행값을 별도 필드로 기록합니다. 미실행/미완료 정확도는 `null`이며 과거 결과를 새 결과로 복사하지 않습니다.

새 treatment의 실험에서는 모든 arm을 동일하게 직렬 실행하고 순서를 회전해 균형화합니다. 따라서 원저장소의 과거 병렬 실행을 그대로 재현한 실험이라고 주장하지 않습니다. SDK 버전도 새 실험 protocol에 함께 기록합니다. 새로 호출한 모델 응답은 과거 보고서의 byte-for-byte 재생성이 아닙니다.

## 정답 및 멀티 답변 처리

- 선정 14개 사례의 공식 `TransferCaseSpec`은 하나의 컴포넌트, 하나의 **방향 있는 간선**, 또는 하나의 인프라 노드를 원인으로 평가합니다. 여러 독립 원인을 모두 맞혀야 하는 multi-fault cohort는 아닙니다.
- 간선은 source와 destination이 모두 일치해야 합니다. 두 endpoint 중 하나만 맞으면 정답이 아닙니다.
- 사례 001~003에는 `workload_restart` 외에 직접 로그로 지지되는 `configuration_error`도 허용됩니다. 원래 scorer의 허용 목록을 그대로 사용합니다.
- 실제 source가 선언한 Pod/Container 별칭은 원래 `component_matches`가 처리합니다. 이름 prefix를 임의로 자르거나 문자열을 나열해 정답을 맞히는 규칙을 만들지 않습니다.
- 최종 `alternative_candidates`와 Python의 여러 Thread는 보존합니다. 공식 Top-1 진단 정답률을 후보 중 하나만 맞아도 정답으로 바꾸지 않습니다.
- 추후 여러 독립 원인을 요구하는 데이터셋을 추가한다면 별도 protocol에서 set precision/recall/F1·전체 원인 일치율을 평가해야 하며, 현재 14개 사례의 점수와 섞지 않습니다.

Python 이식본의 저장된 예측도 원래 scorer로 재검증했습니다. 실행 명령은 아래와 같습니다.

```bash
python -m logagent_bench.canonical_scoring
```

결과는 `results/v1/upstream_scorer_validation.json`이며 정답 11/14가 유지됩니다. 이 검증은 구조화 진단 필드만 확인하며 Python 출력을 LLM 실행이나 SQL 인용 적합성으로 간주하지 않습니다.

## 실행

```bash
uv venv --python 3.11
uv pip install --python .venv/bin/python -e '.[llm]'
source .venv/bin/activate
logagent-llm plan --output experiments/llm_plan.json
logagent-llm doctor --greptimedb-repo /path/to/pinned-greptimedb \
  --pricing-snapshot /path/to/reviewed-pricing.json \
  --output .reports/llm-environment.json
```

키는 provider별 환경변수로 읽습니다: `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `BIGMODEL_API_KEY`, `GEMINI_API_KEY`, `DASHSCOPE_API_KEY`. DashScope의 caller-owned endpoint는 `DASHSCOPE_BASE_URL`입니다. 모델 제공 여부와 계정 quota는 실행 전 별도 확인해야 하며, 사용할 수 없는 모델을 조용히 바꾸지 않습니다.

실제 실행은 원저장소 `run-rca-bench` 지침에 따라 모델 설정·cell 수·비용 범위가 검토된 bounded batch로 수행합니다. 다음은 실행 형식입니다. `--max-new-runs`는 cell 수 제한이며 금액 한도는 아닙니다.

```bash
logagent-llm run --greptimedb-repo /path/to/pinned-greptimedb \
  --pricing-snapshot /path/to/reviewed-pricing.json \
  --run-root .reports/llm-v2 \
  --max-new-runs 2 --confirm-paid-api \
  --output .reports/llm-v2/public-progress.json
```

같은 run root로 재개하면 완료 cell은 건너뜁니다. 잘못된 답이나 한도 초과를 점수 향상을 위해 재실행하지 않습니다. STARTED 상태로 끝난 paid cell은 자동 재시도하지 않고 기록 확인이 필요합니다.

가격 스냅샷은 `verified_at`과 `models`별 확인된 요율·통화·출처를 보관합니다. 원래 API usage와 native usage를 보존하며 cache 상세가 없으면 비용을 0으로 채우지 않습니다. 현재 exporter의 합산 비용은 미계산(`null`)입니다. 논문에서 비용을 보고하려면 이 native usage를 당시 확인 요율과 provider 계약에 맞춰 해석해 산출해야 합니다.

## 논문 집계

- 독립 단위는 사례입니다. 반복 2회를 독립 사례 28개로 늘리지 않습니다.
- 모델별로 사례 안의 두 정답 여부를 평균하고 같은 사례끼리 차이를 계산합니다.
- 주 정확도 비교는 사례별 차이의 exact sign test와 모델 간 Holm 보정을 사용합니다. 이는 평균 차이 크기가 아니라 방향의 일관성을 검정합니다.
- 차이 크기의 95% 구간은 사례 단위 paired bootstrap으로 기술합니다.
- 기권·실행 실패를 분모에서 제거하지 않습니다. 아직 실행하지 않은 cell이 있으면 비교 정확도나 우월성 결론을 생성하지 않습니다.
- 토큰·도구 호출은 원래 효율 적격 조건을 충족한 paired 사례에 한해 별도 보고합니다. 비용과 cache 불명확성은 결과 옆에 명시해야 합니다. 현재 자동 통계 코드는 주 정확도 비교를 구현하며, 효율·비용의 별도 보정 분석은 추가 검증 전까지 기술 통계로만 취급합니다.

```bash
logagent-llm compare --input .reports/llm-v2/public-progress.json \
  --output .reports/llm-v2/paired-analysis.json
```

14개 선정 사례와 공개 taxonomy를 알고 만든 초기 연구 구현입니다. v2는 이전 HF 실험의 결과를 확인한 뒤 사용자의 역할 분담 요청을 반영한 개발 실험이며, 미관측 holdout의 확증 결과로 주장할 수 없습니다. 논문에서 일반화나 실질적 우월성을 주장하려면 추가 비공개/미사용 사례, 가설·온톨로지·후보 선별의 ablation, 여러 반복을 통한 안정성 평가가 필요합니다. 이 실험 설정은 파일로 고정한 분석 계획이며 제3자 공개 사전등록을 뜻하지 않습니다.
