# Hugging Face with the original investigation loop

Same Qwen3-1.7B Q8 model, real GreptimeDB telemetry queries, 14 independent cases, two arms and two repetitions.

| Dataset | Raw HF | LogAgent candidates + HF |
|---|---:|---:|
| openrca2 | 0/20 (0.00%) | 0/20 (0.00%) |
| rca100 | 0/8 (0.00%) | 0/8 (0.00%) |
| all | 0/28 (0.00%) | 0/28 (0.00%) |

Completed investigations: 56. Actual model forward calls: 1673.

The model, local JSON tool serialization, native context and GreptimeDB build differ from the historical six-model experiment. The original runner loop, Raw query tools, final schema, validation feedback and diagnosis scorer are reused.

Primary accuracy includes runner failures and does not imply grounded evidence. See results.json for citation validity, complete upstream success and actual query usage. Original source telemetry, model responses and private query results are not published.
