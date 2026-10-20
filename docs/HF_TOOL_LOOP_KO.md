# Hugging Face + 원저장소 RCA 조사 루프

`hf-original-tool-loop-v1`은 공개 HF 모델을 실제로 실행하는 별도 실험입니다. 이전의 요약문 단일 응답 실험과 결과를 섞지 않습니다. 원래 6개 API 모델의 결과를 HF 모델의 결과로 대신 채우지 않습니다.

[Python·LogAgent+HF·원래 방식 비교표](THREE_WAY_COMPARISON_KO.md)에서 지정 실행의 집계 상태와 원저장소 공개 참고값을 확인할 수 있습니다. 논문 EM·PR·graph F1과 현재 진단 정답률의 정의 차이도 함께 기록합니다.

## 처리와 비교 조건

1. 같은 고정 원본 파일·시간창·14개 사례를 실제 GreptimeDB에 적재합니다. 원본 SDK의 데이터·식별자·시간창·적재량·관계·기전·SQL/PromQL 사전 검증을 통과한 사례만 모델을 호출합니다.
2. 기본 조건 `raw_hf`는 원래 Raw 도구로 조사합니다. `logagent_hf`는 같은 telemetry에서 LogAgent가 선별한 최대 5개 후보를 첫 입력에 추가한 뒤 같은 도구로 조사합니다. 후보는 기각할 수 있고, 후보 밖의 원인도 조사할 수 있습니다.
3. 원본 SDK의 `run_structured_api_agent` 루프를 사용합니다. HF 가중치의 생성 결과를 JSON 도구 호출로 직렬화하는 어댑터만 추가합니다. 실제 SQL·PromQL·schema 조회 결과와 제출 오류가 다음 모델 턴에 전달됩니다.
4. 원래 system prompt·Raw 도구 인자 schema·`submit_diagnosis`·위치 필드 및 인용 검증을 유지합니다. 최종 답을 사후 보정하지 않습니다. 형식/인용 오류는 원래 루프 안에서만 모델에 돌려줍니다.
5. 사례의 4개 실행이 끝나고 예측 해시를 봉인한 뒤 원래 전체 scorer를 실행합니다. 모든 56개 예측을 수집·검증한 뒤 진단 필드 정답률을 원래 scorer로 독립 재채점하며, 두 채점의 정답 여부가 다르면 집계를 중단합니다.

| 항목 | 고정 설정 |
|---|---|
| 모델 | `Qwen/Qwen3-1.7B-GGUF`, Q8_0 |
| 모델 revision | `90862c4b9d2787eaed51d12237eafdfe7c5f6077` |
| 모델 파일 SHA256 | `061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a` |
| 추론 | CPU, llama-cpp-python 0.3.36, 비사고 모드 |
| 조건·반복 | Raw HF / LogAgent+HF, seed 17·29, 사례별 순서 교대 |
| 조사 한도 | 도구 48회, 58턴, 응답당 출력 상한 16,384 tokens |
| context | 모델 native 32,768 tokens; 넘치면 transcript를 자르지 않고 실패로 보존 |
| sampling | temperature 0.7, top_p 0.8, top_k 20; 두 조건 동일 |
| KV cache | 매 cell 초기화, 한 cell 안에서 정확히 일치하는 prefix만 재사용 |
| benchmark SDK | `fdfbca65c87c36c6b06bddfa6d611544f13bfa34` |
| 실제 DB | 공식 checksum 고정 GreptimeDB `v1.3.0-beta.2` |
| API 키·유료 모델 API | 사용하지 않음; 공개 가중치 로컬 추론 |

OpenRCA2 분모는 조건당 **20회**(10개 사례×2반복), RCA100은 **8회**(4개×2반복), 전체는 **28회**입니다. 두 조건을 합치면 56개 진단 실행이며, 도구 루프가 있으므로 실제 모델 생성 호출 수는 이보다 많을 수 있습니다. 독립 사례 수는 14개입니다.

## 원래 공개 실험과 다른 점

- 모델·양자화·비사고 모드·sampling·seed·native context는 원래 6개 API 모델 설정과 다릅니다. 같은 HF 모델끼리 두 조건을 비교합니다.
- 로컬 모델은 한 턴에 하나의 도구를 JSON으로 선택합니다. 원래 SDK의 Anthropic 메시지 분기를 직렬화 통로로 재사용하며 Anthropic 모델이나 API를 호출한 것으로 표기하지 않습니다.
- DB는 원래 source build `15317a...`와 다른 공식 배포본입니다. 실제 버전·binary 해시를 기록하고 동일한 DB/telemetry에서 두 조건을 실행합니다. 원래 Split·Graph 조건은 실행하지 않습니다.
- 후보 전달 문맥과 Python 전처리 비용이 LogAgent 조건에 추가됩니다. 선별 시간은 전체 소요 시간과 별도 필드에 모두 기록합니다.
- 같은 공개 사례의 이전 실험을 확인한 뒤 진행하는 개발 실험입니다. 새로운 holdout이나 원래 6개 모델의 재현 성능으로 주장하지 않습니다.

## 정답률과 실제 근거 사용을 함께 확인

주 지표는 원래 scorer의 **최종 원인 위치·기전·유형 정답률**입니다. 실패와 한도 소진도 분모에서 빼지 않습니다. 정답률만으로 증거가 충분하다고 해석하지 않도록 실제 조회 도구 사용 여부·호출 수, 인용 검증, 전체 upstream success도 별도 보고합니다.

전체 scorer는 사례의 4개 예측 봉인 후 private 실행 기록으로 계산합니다. 공개 저장소에는 원본 telemetry, 모델 응답, query 결과 행, 자유 서술을 올리지 않습니다. 공개 JSON으로 독립 재현하는 범위는 진단 필드 채점이며, 전체 근거 감사는 private 기록이 필요합니다. 실패한 마지막 생성의 토큰도 관측된 경우 합산하며, usage를 확보하지 못한 생성 시도는 토큰 집계 불완전으로 표시합니다.

DB는 공식 opt-out인 `GREPTIMEDB_STANDALONE__ENABLE_TELEMETRY=false`를 시작 전에 적용합니다. 기본 통계 전송이 켜진 첫 환경 시도는 자동 승인 검토로 중단됐으며, 전송을 끈 후 효과를 로그에서 확인하고 새 환경에서 검증했습니다. 이 첫 시도에는 벤치마크 모델 호출이 없습니다.

## 실행과 보존

GitHub Actions의 **HF original RCA tool loop**가 14개 격리 작업을 실행하고 완료된 56개 예측만 집계합니다. 결과 위치는 `results/hf-tool-loop-<run-id>/`입니다. 이후 재실행에는 새 run ID를 사용하며 틀린 답을 골라 재시도하지 않습니다.

로컬 실행 예시(Python 3.11):

```bash
python -m pip install --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --only-binary=llama-cpp-python 'llama-cpp-python==0.3.36'
python -m pip install -e '.[hf,llm]'
python scripts/hf_loop_case.py --case-id 001 --preflight-only
```

실제 실행은 새 작업 디렉터리에서 `--preflight-only`를 빼고 실행합니다. 동일 디렉터리의 결과를 덮어쓰지 않습니다. 환경 오류는 모델 오답으로 섞지 않으며, 한 사례라도 환경 검증을 완료하지 못하면 전체 정답률을 보고하지 않습니다.
