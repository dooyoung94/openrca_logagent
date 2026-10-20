# Hugging Face local pilot: actual LLM measurements

This is a separate Qwen3-1.7B Q8 summary-input experiment, not a replication of the six published model configurations.

Same 14 end-to-end cases, two arms and two seeded repetitions: **56 actual model invocations**.

| Dataset | Independent cases | Summary + LLM | LogAgent hints + LLM |
|---|---:|---:|---:|
| openrca2 | 10 | 0/20 (0.00%) | 6/20 (30.00%) |
| rca100 | 4 | 0/8 (0.00%) | 2/8 (25.00%) |
| all | 14 | 0/28 (0.00%) | 8/28 (28.57%) |

Accuracy uses all executions including invalid answers, abstentions, output-budget failures and runner errors. Repetitions do not increase the number of independent cases.

The original scorer evaluates diagnosis fields only. Summary evidence IDs are not original SQL citations and do not establish original grounding or efficiency eligibility.

Both arms receive identical common telemetry summaries; the LogAgent arm additionally receives fallible candidates from the fixed architecture port. Bounded summaries omit observations. The extra hints can contain analysis of those omitted observations, so this measures the complete added architecture interface rather than isolating LLM reasoning.

Model weights, source files, prompt/code/packet hashes, sampling parameters and per-run usage are recorded in results.json. Private telemetry packets and model response text are not published.

The 6-model historical denominators (120 OpenRCA2 / 48 RCA100 per arm) must not be substituted for this one-model pilot's 20 / 8 executions. No superiority or generalization inference is made from this public selected cohort.
