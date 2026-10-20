# LogAgent × OpenRCA Benchmark

첨부 LogAgent v2의 **관측 정규화 → 시간·온톨로지 연결 → 가설 평가 → 후보 Thread → 점수화** 구조를 OpenRCA 데이터에 맞게 구현한 평가 프로젝트입니다.

운영 코드 전체나 Jennifer 전용 임계치를 복사하지 않습니다. 원래 ZIP의 해시와 설계 참조 모듈은 `provenance/architecture_source.json`에 기록합니다. Python 단독 실행에는 운영 DB, Neo4j 서버, Jennifer API, LLM API 키가 필요하지 않습니다.

## 현재 LLM 연결 방식

**LogAgent가 상위 5개 후보 선별 → 원저장소 LLM이 SQL·PromQL로 반복 조사 → 원래 `submit_diagnosis`로 최종 제출 → 원래 채점기** 순서입니다. 후보는 첫 모델 호출 전에 제공하며, 후보가 틀리거나 없으면 LLM이 다른 원인도 조사합니다. Python의 Top-1을 LLM의 최종 답으로 고정하지 않습니다.

원저장소와 같은 모델 설정·system prompt·Raw 도구·48회 도구 한도·58턴·16,384 출력 상한·진단 및 인용 검증을 사용합니다. LogAgent 조건에는 원래 incident prompt 뒤에 후보 문맥이 추가되므로 **전체 입력이 동일하다고 주장하지 않습니다**. 선별 시간은 전체 소요 시간에 포함하고 별도로 기록합니다. [원저장소 처리 방식과 변경 내역](docs/UPSTREAM_PIPELINE_KO.md)을 확인하십시오.

새 연결 방식 `logagent-matched-llm-v2`의 실제 모델 실행은 **0회**, 정답률은 **미측정**입니다. API 키·고정 GreptimeDB release build·Docker·가격 스냅샷이 필요합니다. 아래 HF 결과는 이전의 요약문 단일 응답 실험이며 새 방식의 점수가 아닙니다.

## 이전 Hugging Face 요약문 실험 결과

공개 **Qwen3-1.7B Q8** 가중치로 같은 14개 사례를 2조건·2반복, 총 **56회 실제 추론**했습니다. 아래 분모는 모델 실행 수입니다.

| 데이터셋 | 관측 요약 + LLM | LogAgent 후보 + LLM |
|---|---:|---:|
| OpenRCA2, 10개 사례 | 0/20, **0.00%** | 6/20, **30.00%** |
| RCA100, 4개 사례 | 0/8, **0.00%** | 2/8, **25.00%** |
| 전체, 14개 사례 | 0/28, **0.00%** | 8/28, **28.57%** |

**해석에 필요한 제한:** 원본 진단 구조 검증에서 관측 요약 조건 28/28개, LogAgent 조건 19/28개 출력이 거부됐고 모두 오답에 포함했습니다. 컴포넌트와 간선 위치 필드를 함께 채운 답변 등으로, JSON 문법이 맞는 것과 원본 진단 계약을 지키는 것은 다릅니다. 모델 답변을 사후 보정하지 않았습니다. 이 결과는 출력 계약 실패가 많이 포함된 단일 경량 모델 실험이며, 원본 6개 모델 합산 점수와 같은 실험으로 해석하지 않습니다.

[실측 JSON](results/hf-actions-39402033849/results.json) · [출력 계약 감사](results/hf-actions-39402033849/contract_audit.json) · [한국어 측정 설명](docs/MEASUREMENT_HF_KO.md) · [추론 실행](https://github.com/dooyoung94/openrca_logagent/actions/runs/39402033849) · [원본 채점기 집계](https://github.com/dooyoung94/openrca_logagent/actions/runs/39403123956)

## Python 측정 결과 (LLM 미사용)

| 대상 | 원인 위치·기전 모두 정답 | 정답률 | 위치 정답률 |
|---|---:|---:|---:|
| OpenRCA2 선정 사례 | 9/10 | **90.00%** | 10/10, 100.00% |
| RCA100 선정 사례 | 2/4 | **50.00%** | 2/4, 50.00% |
| 전체 | 11/14 | **78.57%** | 12/14, 85.71% |

각 사례 2회, 총 28회 실행에서 예측이 일치했습니다. 실행 오류는 0회이며, 기권한 1개 사례(반복 실행 2회)도 오답에 포함했습니다. 자세한 실패 사례와 한계는 [측정 설명](docs/MEASUREMENT_KO.md), 원본 구조화 집계는 [results/v1/results.json](results/v1/results.json)에 있습니다. **전체 OpenRCA2 공식 리더보드 성능이나 Capability 점수가 아닙니다.**

원저장소 공식 scorer로 다시 채점해도 11/14입니다. [공식 채점 재검증](results/v1/upstream_scorer_validation.json)에는 허용 대체 기전과 source identity 별칭을 반영한 결과가 있습니다.

## 논문용 LLM 비교

- [원저장소 모델별 OpenRCA2·RCA100 정답률](docs/BASELINE_RESULTS.md): 원본 공개 JSON에서 계산한 Split·Raw·Graph의 과거 측정치.
- [LLM 실험 조건·멀티 답변 처리·실행 방법](docs/PAPER_PROTOCOL.md): 같은 6개 모델·원래 조사 지침·48회 도구·58턴·16,384 출력 상한·같은 공식 scorer에 LogAgent 후보 선별 조건을 추가합니다. LogAgent 입력에는 후보 문맥이 더해집니다.
- 원래 6개 모델 실험은 14사례 × 6모델 × 4조건 × 2회 = **672개 cell** 계획입니다. 이 6개 모델 설정의 실제 호출은 **0회**입니다. API 키·고정 GreptimeDB build·Docker·가격 스냅샷이 없어 실행 전 점검에서 중단됐습니다.
- 별도로 [Hugging Face 로컬 LLM 실험](docs/HF_LOCAL_KO.md)을 완료했습니다. 공개 Qwen3-1.7B Q8 가중치를 실제로 내려받아 사용했으며, 같은 14개 사례의 관측 요약 조건과 LogAgent 후보 추가 조건을 비교했습니다. 원래 Qwen API 모델이나 6개 모델 합산 실험과는 별개입니다.
- 원래의 허용 대체 정답과 별칭은 보존하고, 여러 후보를 내놓았다는 이유로 Top-1을 정답 처리하지 않습니다.

```bash
python -m pip install -e '.[llm]'
logagent-llm plan
logagent-llm doctor --output experiments/environment_check.json
```

`doctor`는 모델을 호출하지 않습니다. 미실행 정확도는 `null`로 보관합니다. Python의 90%를 LLM 결과로 사용하지 않습니다.

## 실행

```bash
git clone https://github.com/dooyoung94/openrca_logagent.git
cd openrca_logagent
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
logagent-bench fetch
logagent-bench run --run-root .runs/my-measurement --output results/my-measurement --repetitions 2
```

Windows PowerShell에서는 활성화 명령을 `.venv\Scripts\Activate.ps1`로 바꿉니다. 기존 측정 디렉터리는 덮어쓰지 않으므로 재실행 시 새 `--run-root`를 사용합니다.

## 평가 대상

사례 수는 **개**, 모델 실행 수는 **회**, 파일 수는 **개**로 구분합니다. 원저장소의 전체 평가 사례 22개와 최종 RCA 사례 14개는 범위가 다릅니다.

| 집계 대상 | 원저장소 공개 측정 | 이 저장소 |
|---|---:|---|
| OpenRCA2 최종 RCA 선정 사례 | 10개 | 같은 10개 |
| RCA100 최종 RCA 선정 사례 | 4개 | 같은 4개 |
| Discovery / Graph retrieval 보조 사례 | 6개 / 2개 | 현재 평가 범위에 미포함 |
| 최종 RCA 모델 실행 | 504회 = 14×6모델×3조건×2반복 | 672회 계획 = 14×6모델×4조건×2반복; 아래 Python 실행과 별도 |
| 보조 micro 모델 실행 | 192회 = 8×6모델×2조건×2반복 | 미실행 |
| 전체 공개 모델 실행 | 696회 = 504+192 | 같은 전체 실험을 완료한 상태가 아님 |
| Python 구조화 진단 실행 | 위 LLM 집계와 별개 | 28회 = 14개 사례×2반복 |

원저장소는 `REPORT.md`의 **Measurement scope**와 `DATASETS.md`의 **Release cohort**를 기준으로 확인했습니다. 원저장소와 맞춘 최종 RCA 합산 분모는 조건당 OpenRCA2 **120회**, RCA100 **48회**입니다. 현재 Python 결과의 9/10·2/4는 독립 사례 기준이며, 원저장소 6개 모델의 실행별 합산 결과와 같은 분모가 아닙니다. 사례가 14개라는 이유로 모델 실행을 14회로 집계하거나, 반복·모델 수를 곱해 독립 사례 수를 늘리지 않습니다.

- Agent RCA Bench v34의 동일 end-to-end cohort: OpenRCA2 ops-lite 10개, RCA100 v1.1 4개.
- 독립 사례는 14개입니다. 2회 반복은 결정성 검증이며 표본 수를 28개로 부풀리지 않습니다.
- 데이터셋과 benchmark commit은 고정합니다. 내려받은 158개 파일을 공개 fixture의 SHA256과 대조합니다.
- 정상·이상 구간 전체를 시간순 T1~T4로 나누며, 정상 구간은 기준 비교에 사용합니다. 10분 데이터를 60분으로 늘리거나 없는 SQL Profile을 만들지 않습니다.
- CPU의 core 사용량, 노드 CPU의 %, 메모리 bytes와 %를 별도 규칙으로 처리합니다.
- 전체 OpenRCA2 공식 리더보드 점수나 원본 LogAgent 운영 코드의 성능을 뜻하지 않습니다.

## 정답률과 근거

`causal_scope`, 실제 원인 위치(컴포넌트·방향 있는 호출 간선·노드), `fault_category`, `mechanism_code`가 모두 맞아야 정답입니다. 근거 부족에 따른 기권과 실행 실패도 전체 분모에 포함합니다. 위치 정답률과 장애 유형 정답률은 별도 집계합니다.

상위 후보의 Thread 점수는 근거 지지 점수이며 정답 확률이 아닙니다. 위 Python 단독 결과는 공개 보고서의 Capability 점수나 유료 LLM 도구 루프의 결과가 아니므로 그 점수와 직접 비교하지 않습니다. 현재 LLM 연결 방식은 원래 도구 루프와 SQL 인용 검증기를 재사용하지만 실제 모델 실행 전입니다.

## 정답 유출 방지

1. `fetch`: 정답을 포함할 수 있는 메타데이터는 `metadata`에 격리합니다.
2. `run`: 분석 입력에는 불투명 사례 ID, 정상·이상 시간창, 허용된 원본 telemetry만 전달합니다.
3. `worker`: `fixtures`, `metadata`, `injection.json`, `causal_graph.json`, `task.json`, `topology.json` 등을 여는 시도를 차단합니다.
4. 호출 관계는 실제 Client/Server span의 trace ID·parent span ID로 재구성합니다. 서비스-노드 관계도 실제 resource 필드만 사용합니다.
5. 코드·설정 해시를 분석 전에 고정하고, 모든 예측을 저장·봉인한 뒤 독립 채점합니다.

이는 프로세스 내부 파일 접근 가드와 코드 구조상의 분리입니다. 악성 코드에 대한 OS 보안 샌드박스를 의미하지 않습니다. 공개 데이터의 스키마와 장애 분류를 알고 설계한 소규모 평가이므로 새로운 비공개 데이터에 대한 일반화 성능은 별도 검증이 필요합니다.

## 파일

| 위치 | 역할 |
|---|---|
| `src/logagent_bench/adapter.py` | Parquet 입력·정확한 시간 단위·관측 identity 결합 |
| `src/logagent_bench/engine.py` | 가설·온톨로지·T1~T4·Thread·Top-1 |
| `configs/hypothesis.yaml` | 지표 의미·임계치·가중치 |
| `src/logagent_bench/worker.py` | 사례별 분석과 정답 파일 접근 차단 |
| `src/logagent_bench/candidates.py` | 격리된 분석 프로세스에서 상위 5개 후보 선별 |
| `src/logagent_bench/upstream_bridge.py` | 후보 전달 후 원래 LLM 도구 루프·진단 제출 |
| `src/logagent_bench/scoring.py` | 분석 종료 후 구조화 정답 비교 |
| `src/logagent_bench/runner.py` | 코드 고정·반복 실행·실패 보존·결과 생성 |
| `results/v1/` | 실제 측정 결과와 프로토콜·다운로드 검증 |
| `tests/test_contracts.py` | 시간·근거·정답 격리·채점 경계 테스트 |

## GitHub 저장소

사용자가 지정한 저장소: https://github.com/dooyoung94/openrca_logagent

## 출처와 데이터 이용 조건

- Benchmark: https://github.com/GreptimeTeam/agent-rca-bench
- 고정 benchmark commit: `fdfbca65c87c36c6b06bddfa6d611544f13bfa34`
- OpenRCA2: https://huggingface.co/datasets/anon-ops/ops-lite (`9ac09981c08ab02a0b923eab7830d778934851a8`)
- RCA100: AgenticOpsEval v1.1 (`69cf36430b43024d02530c610b1a4738b5c9a7fb`)

동일 cohort의 선택 fixture는 Agent RCA Bench에서 가져왔습니다. 해당 코드·fixture의 Apache-2.0 라이선스는 `third_party/agent-rca-bench/LICENSE`에 보관합니다. OpenRCA2의 데이터 카드와 논문은 라이선스 표기가 서로 다르며, RCA100은 CC BY-NC-SA 4.0 조건을 유지합니다. 원본 telemetry·배포 topology·ground-truth 파일은 저장소에 포함하지 않습니다. 상세 출처는 `third_party/NOTICE.md`를 확인하십시오.
