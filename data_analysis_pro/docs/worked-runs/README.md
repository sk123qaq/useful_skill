# Worked runs

Public-data end-to-end runs used to validate the causal and experiment branches.

| run | data | method | headline | gate |
|---|---|---|---|---|
| `nsw_psm` | `causaldata.nsw_mixtape` (445) | PSM, ATT | 1863.01 (95% CI 372.02–3353.99), p=.0146 | report-ready |
| `nsw_dml` | `causaldata.nsw_mixtape` (445) | DML, ATE | 2110.14 (95% CI 636.54–3583.74), p=.0050 | report-ready |
| `black_exp` | `causaldata.black_politicians` (5593) | two-arm experiment | reply rate 55.51% → 28.90%, -26.61pp, p=3.06e-90 | report-ready |

These are validation runs, not business conclusions. NSW is observational; its causal interpretation depends on conditional exchangeability and overlap. The email experiment's negative effect is specific to the out-of-district manipulation.

Reproduce with `references/worked-examples.md`.
