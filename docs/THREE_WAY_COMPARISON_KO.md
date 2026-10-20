# 세 방법 × Raw·Graph: 실제 실행 범위와 논문 평가 공백

**요청한 세 방법의 Raw·Graph 비교와 논문 전체 평가는 아직 완료하지 않았습니다.** 이전 표는 Python의 단일 조건 결과와 원저장소의 Raw·Graph 결과를 함께 배치해 비교 범위가 불명확했습니다. Python의 기존 90%·50%·78.57%는 Raw/Graph로 분리한 점수가 아닙니다.

Raw·Graph는 원저장소의 관측 인터페이스 조건이고, EM·F1·PR 등은 논문의 평가 지표입니다. 두 축을 모두 맞춰야 합니다. 원저장소 Graph는 실제 GreptimeDB Semantic Graph 접근 권한을 추가하는 조건이며, 정답 causal_graph.json을 분석 입력으로 제공하는 조건이 아닙니다.

## 표 1. 요청한 세 방법 × 두 인터페이스의 현재 상태

| 방법 | Raw | Graph |
|---|---|---|
| ① Python LogAgent | 미측정 — 해당 접근 경로 미구현 | 미측정 — 해당 접근 경로 미구현 |
| ② LogAgent 후보 + HF LLM | 기존 Raw 실행 중·미집계 | 미측정 — 해당 접근 경로 미구현 |
| ③ 원래 GitHub 루프 + 동일 HF | 기존 Raw 실행 중·미집계 | 미측정 — 해당 접근 경로 미구현 |

전체 14개 선정 사례 기준입니다. 미측정은 0%가 아닙니다. 위 표의 ③은 모델 차이를 통제하기 위해 같은 HF 모델을 쓰는 원래 GitHub 루프 대조군이며, 기존 6개 모델의 공개 결과는 표 3에 따로 보관합니다. 현재 HF 실행이 끝나도 채워지는 칸은 Raw 두 개뿐입니다. Graph와 Python 두 조건은 자동으로 완성되지 않습니다.

## 표 2. 현재 확보된 별도 실측 — 서로 다른 실행 범위

| 방법 | LLM | OpenRCA2 선정 10개 | RCA100 선정 4개 | 전체 14개 |
|---|---|---:|---:|---:|
| Python 사전실험 — Raw/Graph 미분리 | 사용 안 함 | 90.00% (18/20회) | 50.00% (4/8회) | 78.57% (22/28회) |
| ② LogAgent 후보 + 원래 LLM 루프 | Qwen3-1.7B Q8_0 (HF) | 미집계 | 미집계 | 미집계 |
| ③ 원래 Raw LLM 루프 — 동일 HF 대조군 | Qwen3-1.7B Q8_0 (HF) | 미집계 | 미집계 | 미집계 |

분자는 정답 실행 수, 분모는 전체 실행 수입니다. Python은 각각 9/10개·2/4개·11/14개 사례가 정답이며 두 반복의 예측 해시가 동일합니다. 반복을 곱해 독립 사례 수를 늘리지 않습니다. HF도 조건당 OpenRCA2 20회, RCA100 8회, 전체 28회를 모두 검증한 뒤 집계합니다. 미집계는 0%가 아닙니다.

HF 두 방법은 같은 HF 가중치·sampling·DB·원본 파일·Raw 도구·원래 제출 검증 및 scorer를 사용합니다. 후보 추가 조건에 Python 처리 시간이 포함됩니다. 기존 Python 사전실험은 Parquet 관측을 직접 읽고 trace에서 자체 온톨로지를 구성했습니다. 이것을 원저장소 Raw 또는 Graph의 실측으로 재명명하지 않습니다.

진행 확인: `2026-10-20T13:45:09.943347+00:00`, 사례 작업 5/14개 완료, 0개 실패. GitHub 작업의 성공은 정답을 뜻하지 않습니다. 개별 작업에 여러 실행이 포함되므로 완료 작업 수를 모델 호출 수로 읽지 않습니다.

[고정 HF 실행](https://github.com/dooyoung94/openrca_logagent/actions/runs/39419829987) · [측정 프로토콜](../experiments/hf_tool_loop_protocol.json) · [HF 조건 차이](HF_TOOL_LOOP_KO.md)

## 표 3. 원저장소의 기존 공개 결과

| 원래 공개 방식 | OpenRCA2 선정 10개 | RCA100 선정 4개 | 전체 14개 |
|---|---:|---:|---:|
| 원저장소 Raw · 공개 6개 모델 합산 | 88.33% (106/120회) | 50.00% (24/48회) | 77.38% (130/168회) |
| 원저장소 Graph · 공개 6개 모델 합산 | 93.33% (112/120회) | 25.00% (12/48회) | 73.81% (124/168회) |
| 원저장소 Split · 공개 6개 모델 합산 | 70.83% (85/120회) | 41.67% (20/48회) | 62.50% (105/168회) |

기존 6개 모델×2반복이므로 조건당 OpenRCA2 120회, RCA100 48회, 전체 168회입니다. 위 HF 경량 모델과 모델·transport·DB build가 다릅니다. 같은 사례와 같은 진단 채점 기준의 기술적 비교이며, 이 표만으로 LogAgent의 우월성이나 열등성을 검정할 수 없습니다. 모델별 값은 [기존 모델 표](BASELINE_RESULTS.md)에 있습니다.

## 표 4. 논문 설계와 현재 실험의 대응

[OpenRCA 2.0 논문](https://arxiv.org/pdf/2606.27154v2)의 §3.1–3.2, Appendix F–G를 확인했습니다. 논문은 결과와 인과 과정 평가를 구분합니다.

| 항목 | 논문 설계 | 현재 확보한 데이터·실행 | 판정 |
|---|---|---|---|
| 데이터 범위 | 3개 시스템, 500개 사례 | ops-lite의 고정 10개 + 별도 RCA100 4개 | 축소·외부 확장 평가; 논문 전체 재현 아님 |
| 모델 비교 | 같은 도구·prompt 조건에서 backbone 비교 | HF ②·③의 모델과 Raw 조사 조건 고정, ②에 후보 추가 | 후보 전처리 전체 효과 비교 |
| 조사·출력 | ReAct 조사 뒤 원인 집합·전파 간선·SQL 근거 출력 | 원래 GitHub 루프와 단일 typed-locus Diagnosis 유지 | 출력 계약 다름 |
| 도구·한도 | Parquet/DuckDB 도구, hard cap 100 | GreptimeDB SQL/PromQL, 도구 48회·58턴 | 원저장소 조건 유지; 논문과 다름 |
| 정답 분리 | 개입 정보와 검증 그래프를 평가에 사용 | 분석 프로세스의 label·metadata 접근 차단 | 유지 |
| 독립 단위 | 사례별 지표 집계 | 14개 사례; 각 2반복 | 반복은 독립 표본 아님 |

원저장소 DATASETS.md도 현재 ops-lite artifact가 논문의 archival release와 동일하지 않다고 명시합니다. RCA100의 노드 사례는 논문의 service 수준 결과와 분리해 보고합니다. 전체 14개 합산은 이 선정 cohort에 대한 기술 통계입니다. [기존 공개 JSON 원본 대조](../experiments/historical_source_verification.json)에서 source SHA256과 데이터셋별 수치의 일치를 확인했습니다.

## 표 5. 논문 Table 2 형식의 지표 적용 가능성

| 평가층 | 지표 | ① Python | ② LogAgent+HF | ③ 원래 Raw+HF | 현재의 제약 |
|---|---|---|---|---|---|
| Outcome | EM·Precision·Recall·F1 | 미산출 | 미산출 | 미산출 | service/fault_kind 원인 집합·동등성 계약이 기존 typed-locus 진단과 다름 |
| Outcome | AnySvc | 미산출 | 미산출 | 미산출 | 위치 정답률에는 방향 간선·인프라 노드가 포함되어 service hit와 다름 |
| Process | PR·Node F1·Edge F1 | 미산출 | 미산출 | 미산출 | 최종 전파 그래프가 기존 출력에 없음; RCA100에는 같은 형식의 검증된 장애 그래프가 없음 |
| Process | SQL Exec | 미산출 | 미산출 | 미산출 | query-ID 인용 유효성과 논문의 비어 있지 않은 DuckDB SQL 재실행 비율은 다름 |
| 별도 공통 지표 | 원저장소 진단 정답률 | 표 2의 단일 사전실험 | Raw 56회 전체 검증 후 | Raw 56회 전체 검증 후 | scope·원인 위치·유형·허용 기전의 동시 일치; 전체 Raw/Graph 설계와 별개 |

과거 6개 모델 공개 점수에도 같은 변환 제약이 있습니다. 현재 진단 정답률 90%를 논문 EM 90%로 쓰거나, 위치 정답률을 AnySvc로 복사하거나, 인용 검증률을 SQL Exec로 대체하지 않습니다.

OpenRCA2 10개 사례의 publisher causal_graph.json은 고정 revision에서 별도 확보 가능함을 [가용성·형식 감사](../experiments/paper_graph_availability.json)로 확인합니다. 기존 158개 파일 해시 감사에는 이 그래프들이 포함되지 않았습니다. 그래프 존재와 JSON 필드 확인은 PAVE 정답의 의미 검증이나 논문 archival release와의 동일성 검증을 대신하지 않습니다. 원본 그래프 내용은 공개하지 않습니다.

## 답변 수와 채점

현재 14개 사례는 하나의 컴포넌트·방향 간선·노드를 맞히는 선정 집합입니다. 사례 001–003의 허용 기전은 OR 조건이며 여러 독립 원인을 동시에 요구한다는 뜻이 아닙니다. 간선은 방향과 두 endpoint를 모두 맞혀야 합니다. alternative_candidates나 여러 Thread 중 하나만 맞았다고 정답 처리하지 않습니다.

논문 원인 집합 평가를 실행하려면 세 방법 모두 동일한 root_causes[]와 propagation[] 계약으로 새 예측을 봉인하고, 서비스·fault_kind 매핑과 평가용 그래프를 먼저 고정해야 합니다. RCA100은 별도의 typed-locus 확장으로 명시해야 합니다. 현재 결과를 보고 예측 그래프를 보충하거나 추정 정답을 채우지 않습니다. 이 추가 실행은 아직 수행하지 않았습니다.

## 누락된 구현과 필요한 새 실험

- Python: 현재 Parquet 입력을 원저장소 Raw SQL/PromQL 접근과 실제 Semantic Graph 접근으로 분리하는 adapter가 필요합니다. 두 조건 모두 LogAgent 가설·시간·온톨로지·점수화 구조를 유지해야 합니다. 온톨로지를 끄는 ablation을 원저장소 Raw 조건으로 대체하지 않습니다.
- LogAgent+HF 및 원래 루프+HF: 현재 후보 bridge는 Visibility.RAW만 허용합니다. 동일 HF 모델로 Graph 도구·후보 선별의 접근 경로까지 구현·검증해야 합니다.
- 논문 지표: 모든 조건의 원인 집합·전파 그래프·근거 SQL 출력과 평가용 그래프·fault_kind 정규화를 먼저 고정해야 합니다. 평가 기준을 맞춘 새 실행이 필요합니다.
- 완전한 단일 HF 설계는 3방법×2인터페이스×14사례×2반복 = 168회입니다. 이는 설계 수량이며 실행 완료 수가 아닙니다. 현재 진행 중인 56회는 Raw 두 방법만 평가하는 별도 protocol입니다.

## 재현과 해석

```bash
python scripts/build_three_way_comparison.py
```

[구조화 비교 결과](../results/three_way_comparison.json)에는 입력 해시, 실행별 분모, null의 이유를 보관합니다. 지정한 HF run 39419829987 결과만 사용하며 더 좋은 후속 run을 자동 선택하지 않습니다. 비교표 갱신 workflow는 추론을 재실행하지 않고 저장된 결과를 집계합니다.

실패·기권·잘못된 제출은 완료된 실행의 분모에서 제외하지 않습니다. HF 원래 전체 success와 인용·도구 사용 지표는 측정 JSON에서 별도 확인하며, 진단 정답만으로 근거가 검증됐다고 해석하지 않습니다. 후보 전처리 시간은 포함하지만 그 파일 I/O는 DB query 카운터에 포함되지 않아 DB 조회 감소를 전체 I/O 절감으로 주장할 수 없습니다.

이는 이미 공개 사례와 이전 결과를 확인한 뒤 작성한 비교·설계 감사입니다. 미관측 holdout이나 사전등록 확증 실험으로 주장하지 않습니다. 완성된 동일 HF 두 조건의 사례별 비교가 확보되기 전에는 유의성·우월성 결론을 만들지 않습니다.

출처: [논문](https://arxiv.org/pdf/2606.27154v2), [선정 데이터](https://github.com/GreptimeTeam/agent-rca-bench/blob/fdfbca65c87c36c6b06bddfa6d611544f13bfa34/DATASETS.md), [진단 채점](https://github.com/GreptimeTeam/agent-rca-bench/blob/fdfbca65c87c36c6b06bddfa6d611544f13bfa34/SCORING.md), [기존 공개 수치](../results/baseline_public.json), [Python 공식 scorer 재검증](../results/v1/upstream_scorer_validation.json).
