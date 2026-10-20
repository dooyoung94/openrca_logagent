# Hugging Face 로컬 LLM 실험

사용자의 Hugging Face 사용 요청에 따라, API 키 없이 공개 모델을 내려받아 실제 추론하는 **별도 소규모 실험**을 추가했습니다. 원저장소의 6개 모델 설정은 그대로 두며, 이 모델을 원래 Qwen API 모델의 동일 모델로 취급하지 않습니다.

## 고정 조건

| 항목 | 설정 |
|---|---|
| 모델 | `Qwen/Qwen3-1.7B-GGUF` |
| 모델 revision | `90862c4b9d2787eaed51d12237eafdfe7c5f6077` |
| 가중치 | 공식 `Qwen3-1.7B-Q8_0.gguf`, 1,834,426,016 bytes |
| 가중치 SHA256 | `061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a` |
| 추론 | `llama-cpp-python==0.3.36`, CPU, 8 threads |
| 사례 | 원저장소의 OpenRCA2 선정 10개 + RCA100 선정 4개 |
| 조건 | 관측 요약 + LLM / 같은 관측 요약 + LogAgent 후보 Thread + LLM |
| 반복 | 각 사례·조건 2회, seed 17·29 |
| 전체 실행 | 14×2조건×2반복 = 56회 |
| 데이터셋별 분모 | 각 조건의 OpenRCA2 20회, RCA100 8회 |
| sampling | temperature 0.7, top_p 0.8, top_k 20, min_p 0 |
| 상한 | context 8,192 tokens, 출력 384 tokens |
| 생성 | non-thinking ChatML, 고정 JSON grammar, 셀별 재시도 0회 |
| 채점 | 고정 원저장소 `evaluate_transfer_run`의 진단 필드 판정 |

모든 코드·가설 설정과 모델 해시를 첫 추론 전에 고정합니다. 관측 요약과 모든 예측도 해시로 봉인합니다. 실제 정답과의 비교는 56개 예측이 모두 저장된 뒤에 수행하며, 실패 답변도 분모에 포함합니다. 정답을 보고 가중치나 프롬프트를 조정한 재실행은 하지 않습니다.

## 입력과 비교 범위

두 조건에 같은 관측 요약을 제공합니다. 요약은 원본 정상·이상 구간의 지표 통계, 실제 parent-span으로 연결한 간선의 시작 시각 차이, 서비스 span 통계, 오류 로그 템플릿으로 구성합니다. 지표는 사례별 변화 순으로 최대 24개 그룹, 간선 10개, 서비스 6개, 오류 템플릿 10개입니다. 정답·주입 메타데이터·publisher topology·reference causal graph는 분석 입력에서 제외합니다.

LogAgent 조건에는 기존 Python 구조가 생성한 최대 6개 Thread 후보를 추가합니다. 후보는 오답일 수 있으며 근거 지지 점수는 확률이 아닙니다. LLM이 최종 위치·기전·분류를 직접 생성하며, 후보를 그대로 정답으로 대입하거나 모델이 생성한 이름과 간선 방향을 사후 보정하지 않습니다. 기권·형식 오류·출력 상한 초과도 기록합니다.

후보 생성기는 제한된 공통 요약에 생략된 관측까지 분석할 수 있습니다. 따라서 비교 대상은 추가 아키텍처 인터페이스의 전체 효과이며, 같은 정보량에서 LLM 추론 능력만 분리한 실험이 아닙니다. 입력 토큰 사용량을 결과와 함께 공개합니다.

선정 14개 사례는 단일 컴포넌트·단일 방향 간선·단일 인프라 노드를 평가합니다. 대체 기전과 identity 별칭은 원래 scorer 규칙을 따릅니다. 여러 후보 중 하나만 맞으면 정답으로 세는 방식으로 바꾸지 않습니다.

이 실험은 원본 Raw·Graph 도구 루프를 재현하지 않습니다. LLM은 사전 집계된 관측 요약을 한 번 읽으며 SQL/PromQL 도구를 호출하지 않습니다. 요약의 `evidence_id`는 원본 SQL 인용이 아니므로 원본 근거 적격성·효율성·Capability 점수를 주장하지 않습니다. 역사적 6개 모델 합산 정확도와 이 1개 소형 모델 실험을 같은 실험으로 합치지 않습니다.

## 재실행

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu 'llama-cpp-python==0.3.36'
python -m pip install -e '.[llm,hf]'
logagent-bench fetch
HF_HUB_DISABLE_XET=1 logagent-hf download-model
logagent-hf run --run-root .runs/hf-new --output results/hf-new
```

모델 다운로드와 데이터 다운로드에는 인터넷이 필요합니다. 공개 모델 다운로드와 로컬 추론에는 HF API 토큰이 필요하지 않습니다. 사용한 모델의 공식 카드: https://huggingface.co/Qwen/Qwen3-1.7B-GGUF

`results/hf-local-v2/`에 실제 결과와 고정 프로토콜을 저장합니다. 원본 관측 행·요약 패킷·LLM 원문·가중치는 GitHub에 올리지 않습니다. CPU 비용과 전력 비용은 측정하지 않았으며, API 사용료가 없다는 것을 전체 실행 비용이 0이라는 의미로 해석하지 않습니다.

공개된 소규모 선정 사례이며 미사용 holdout이 아닙니다. 모델의 학습 데이터에 해당 공개 자료가 포함됐는지 검증할 수 없으므로 오염이 없다고 주장하지 않습니다. 추가 비공개 사례와 더 큰 모델에서의 재현이 논문의 일반화 주장에 필요합니다.

초기 시도의 CPU 처리 지연과 중단 이력은 `experiments/hf_execution_history.json`에 남겼습니다. 새 시도는 같은 관측 패킷을 표 머리글·행 형식으로 표현하고, 사례 안에서 같은 프롬프트 token prefix만 재사용합니다. 입력 통계가 모두 보존됐다는 검증은 `experiments/hf_serialization_audit.json`에 있습니다. 중단한 시도는 새 완료 실험의 정확도에 포함하지 않으며, 그 시도의 정확도를 채점하거나 답변 내용을 보고 조건을 조정하지 않았습니다. 초기 두 모델 프로세스의 자원 경합이 있었으므로 이번 실행의 벽시계 시간을 원저장소의 효율 지표와 비교하지 않습니다.
