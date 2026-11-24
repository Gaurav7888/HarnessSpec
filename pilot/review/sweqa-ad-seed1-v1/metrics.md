# Benchmark metrics

Accuracy, first-pass validity and silent handoffs use attempted runs for applicable conditions.
Tokens per correct divides all consumed tokens by resolved runs.
Accepted-return rates require complete diagnostic coverage.

## sweqa

| Designer | attempted | resolved | accuracy | first pass validity | silent handoffs | silent handoff rate | accepted returns | accepted return coverage | silent given accepted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D | 10 | 0 | 0 | 0.4 | 0 | 0 | 0 | 10 | N/A |

| Designer | design tokens | subagent tokens | total tokens | mean tokens | tokens per correct | mean rounds | mean wall clock s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| D | 31839 | 31107 | 62946 | 6295 | N/A | 0.8 | 145.5 |

| Designer | budget violations | tool denials | hook failures |
| --- | --- | --- | --- |
| D | 4 | 48 | 0 |


| Comparison | Metric (D minus baseline) | Estimate | 95% CI | Matched tasks / pairs | Seeds | Unmatched D / baseline |
| --- | --- | --- | --- | --- | --- | --- |

Pending H2 comparisons with D: B, C.
The supplied runs do not meet the registered three-seed requirement.

H4 estimates are conditional on reuse. The analysis has no observed cache hits.

| Reuse group | Initial tokens | Savings/task | Status | Break-even tasks |
| --- | --- | --- | --- | --- |
| N/A | N/A | N/A | No eligible reuse group | N/A |


## SWE-QA execution-only metrics

Counts cover completed executions regardless of answer grading. A/D is preliminary.

| Designer | Executions | Accepted | Acceptance rate | Silent | Silent/attempt | Silent/accepted | Design tokens | Subagent tokens | Needs external grade |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 10 | 10 | 1 | 0 | 0 | 0 | 0 | 6026 | 10 |
| D | 10 | 0 | 0 | 0 | 0 | N/A | 31839 | 31107 | 0 |

| Designer | First-pass validity | Combined tokens | Mean tokens | Mean rounds | Mean wall time (s) | Budget violations | Tool denials | Hook failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 1 | 6026 | 602.6 | 0 | 25.47 | 0 | 0 | 0 |
| D | 0.4 | 62946 | 6295 | 0.8 | 145.5 | 4 | 48 | 0 |

| Contrast | Difference (pp) | 95% CI | Matched tasks / pairs | Seeds | Unmatched D / baseline |
| --- | --- | --- | --- | --- | --- |
| D_vs_A | 0 | [0, 0] | 10 / 10 | [1] | 0 / 0 |

Matched subagent token savings per attempted task (A minus D): -2508.1. At this marginal cost: no_finite_break_even. Cache reuse was not measured.

H2 contrasts pending for D versus B and C.
