# LogAgent 후보 선별 + 원저장소 LLM 조사

현재 구현: `logagent-matched-llm-v2`. 실제 벤치마크 모델 호출 **0회**, 새 정답률 **미측정**입니다. 이전 HF 요약문 실험의 28.57%는 이 경로의 점수가 아닙니다.

## 원저장소는 어떻게 조사했는가

[고정 원본 agent.py](https://github.com/GreptimeTeam/agent-rca-bench/blob/fdfbca65c87c36c6b06bddfa6d611544f13bfa34/src/agent_rca_bench/agent.py)의 `run_agent`는 같은 조사 지침과 incident prompt를 모델에 주고 반복 도구 루프를 실행합니다. 모델이 저장소를 탐색하고 정상·이상 구간을 비교하면서 원인 범위나 기전이 다른 가설들을 검증합니다. 원저장소의 세 조건은 관측 인터페이스가 다릅니다: Split은 Prometheus·Loki·Tempo, Raw는 GreptimeDB SQL·PromQL, Graph는 Raw에 Semantic Graph 도구를 추가합니다.

최종 답은 `submit_diagnosis` 도구로 제출합니다. 하나의 컴포넌트·방향 있는 간선·노드, 장애 기전과 유형, 전파 영향, onset, 신뢰도, 대안 후보, 근거·설명을 담습니다. `Diagnosis`의 위치 필드 조건과 근거 query ID를 실제로 검증합니다. 잘못된 제출은 오류를 모델에 돌려줘 정해진 턴 안에서 새 제출을 받습니다. 생성 후 필드를 지우거나 답을 대신 고쳐주는 방식은 아닙니다. 완료 결과는 원래 `evaluate_transfer_run`으로 채점합니다.

## 지금 역할 분담

1. LogAgent가 원본 telemetry를 정규화하고 T1~T4·관측 관계·가설·Thread 점수를 계산합니다. 기존 engine·가설 설정·순위를 유지해 상위 **최대 5개** 후보를 선별합니다. 정답 파일 접근을 차단한 별도 프로세스에서 실행합니다.
2. 후보의 원인 위치·기전·점수·시간 구간·관측 연결을 원래 incident prompt 뒤에 탐색 문맥으로 전달합니다. Python의 최종 `diagnosis`, `selected_thread`, 정답, raw telemetry 행은 전달하지 않습니다. 후보 점수는 확률이 아닙니다.
3. 같은 모델이 원래 Raw 도구로 증거를 반복 조회하고 최종 판단합니다. 후보를 기각하거나 후보 밖을 조사할 수 있으며 후보가 없다고 자동 기권하지 않습니다. 후보 ID나 점수를 SQL 근거로 인용할 수 없습니다.
4. 원래 `submit_diagnosis`·형식/인용 검증·채점기를 사용합니다. 후보 중 하나가 정답이라는 이유로 최종 오답을 정답 처리하지 않습니다.

| 항목 | 원저장소 Raw | 현재 LogAgent 조건 |
|---|---|---|
| 후보 전처리 | 없음 | 같은 telemetry에서 상위 5개 후보 |
| system prompt·조사 지침 | 원본 | 원본과 동일 |
| incident prompt | 원본 | 원본을 그대로 두고 후보 문맥 추가 |
| 조회 도구 | 원래 SQL·PromQL 및 schema 도구 | Raw와 동일; 후보 전용 도구 추가 없음 |
| LLM·transport·reasoning·cache | 고정 6개 모델 설정 | 같은 설정 |
| 조사 한도 | 48회, 58턴, 응답당 16,384 tokens | 동일 |
| 최종 진단·오류 피드백·채점 | 원래 runner·schema·scorer | 동일 |
| 전처리 비용 | 없음 | 시간·후보 수·payload 해시 별도 기록, 전체 시간에도 포함 |

추가 후보 문맥과 전처리가 treatment 차이입니다. 전체 입력이 byte-identical하거나 추가 계산량이 없다고 주장하지 않습니다. 새 조건은 원본 운영 LogAgent의 보고서 전용 LLM을 그대로 재현한 경로가 아니라, 요청한 후보 선별과 원저장소 조사 방식을 결합한 연구 구현입니다.

## 이전 실험과 실행 상태

- Python 단독: Top-1 **11/14, 78.57%**. LLM을 호출하지 않은 기존 측정입니다.
- 이전 HF 실험: 1.7B 모델이 요약문과 후보를 보고 한 번 답했습니다. 실제 SQL/PromQL 도구 루프와 원래 오류 피드백을 실행하지 않았습니다. **8/28, 28.57%**는 이 별도 실험에만 해당하며 [결과](MEASUREMENT_HF_KO.md)를 보존합니다.
- 이전 API 계획 v1: LLM이 원할 때 `query_rca_threads`를 호출하는 방식이었고 실제 호출은 0회였습니다. v2에서는 선별을 먼저 실행하고 후보 문맥을 항상 제공합니다.
- 현재 v2: 원래 SDK를 사용한 오프라인 계약 테스트로 후보 전달 순서, 실제 도구 루프, 잘못된 형식·인용의 피드백, 후보 밖의 답 허용, 빈 후보 및 턴 소진을 검증합니다. 테스트의 provider 응답은 작성된 입력이며 실제 모델 측정이나 정확도가 아닙니다.

[검증 기록](../experiments/candidate_pipeline_validation.json)에 34개 테스트 통과, 분석 engine·가설 설정과 기존 결과 파일의 동일 해시, 새 모델 호출 0회를 기록했습니다.

원래 SDK는 **Python 3.11**을 요구합니다. 원래 모델 API 키, 고정 GreptimeDB release build, Docker, 가격 스냅샷이 없어 실제 실행은 preflight에서 중단됩니다. 필요한 조건과 명령은 [PAPER_PROTOCOL.md](PAPER_PROTOCOL.md)에 있습니다. HF의 다른 모델로 원래 6개 모델의 결과를 대신 채우지 않습니다.

같은 공개 사례에서 이전 결과를 확인한 뒤 정한 개발 protocol입니다. 새 점수를 얻더라도 미사용 사례의 확증 결과로 해석하지 않습니다. 동일 사례·모델·설정·반복·조회 한도·채점으로 새 Raw/Graph/LogAgent를 실행해야 비교할 수 있습니다.
