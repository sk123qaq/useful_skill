# Failure Recovery

## Honest Failure

When the run is blocked or unsafe:
- write the blocker artifact
- preserve the current state
- state what is missing or unsafe

## Resume Pattern

Checkpointed runs should be restartable by reusing the existing run directory and continuing past the next explicit checkpoint.
For predictive work, the expected resume sequence is:

1. Run until `judgment_context_after_scout` is produced
2. Agent reviews that context and writes `data_processing_decision.json`
3. Re-run with the same run directory and `--continue-after-scout`
4. Run until `judgment_context_after_baseline` is produced
5. Agent reviews that context and writes `modeling_decision.json`
6. Re-run with the same run directory and both continue flags

## Priority

Prefer an honest `not_usable` outcome over a polished but misleading report.
