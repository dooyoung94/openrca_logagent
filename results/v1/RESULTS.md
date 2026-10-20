# LogAgent architecture port — measured results

This is an OpenRCA-specific implementation of the uploaded architecture, not a rerun of its production binary.

Protocol SHA256: `1b0daa5ece77e915a3ac579e73b65c807394efc5fa16805e6169ebfeb37a62bd`

Independent cases: 14; executions: 28; deterministic repeats: True.

| Cohort / mechanism | Correct | Cases | Strict diagnosis accuracy | Location correct |
|---|---:|---:|---:|---:|
| all | 11 | 14 | 78.57% | 12 |
| openrca2 | 9 | 10 | 90.00% | 10 |
| rca100 | 2 | 4 | 50.00% | 2 |
| call_path_delay | 3 | 3 | 100.00% | 3 |
| cpu_saturation | 3 | 3 | 100.00% | 3 |
| disk_io_degradation | 0 | 1 | 0.00% | 0 |
| host_unavailable | 0 | 1 | 0.00% | 0 |
| memory_pressure | 2 | 2 | 100.00% | 2 |
| workload_restart | 3 | 4 | 75.00% | 4 |

Wilson 95% interval on the 14 independent cases: 52.41%–92.43%.

## Case-level results

| Case | Expected mechanism | Predicted mechanism | Correct |
|---|---|---|---|
| semantic-rca-transfer-001 | workload_restart | workload_restart | True |
| semantic-rca-transfer-002 | workload_restart | dependency_unavailable | False |
| semantic-rca-transfer-003 | workload_restart | workload_restart | True |
| semantic-rca-transfer-004 | workload_restart | workload_restart | True |
| semantic-rca-transfer-005 | call_path_delay | call_path_delay | True |
| semantic-rca-transfer-006 | call_path_delay | call_path_delay | True |
| semantic-rca-transfer-007 | call_path_delay | call_path_delay | True |
| semantic-rca-transfer-008 | cpu_saturation | cpu_saturation | True |
| semantic-rca-transfer-009 | cpu_saturation | cpu_saturation | True |
| semantic-rca-transfer-010 | memory_pressure | memory_pressure | True |
| semantic-rca-transfer-011 | cpu_saturation | cpu_saturation | True |
| semantic-rca-transfer-012 | memory_pressure | memory_pressure | True |
| semantic-rca-transfer-013 | disk_io_degradation | ABSTAIN | False |
| semantic-rca-transfer-014 | host_unavailable | memory_pressure | False |

## Interpretation limits

- 14 selected cases, not the complete OpenRCA2 dataset
- new architecture port, not the original production binary
- rules fixed before scoring, but adapted with knowledge of public dataset schema and fault taxonomy
- no upstream provider loop, SQL citation verifier, or Capability score reproduced
- source-native telemetry availability limits which mechanisms can be established
