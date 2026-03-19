# Gate Rules

## Baseline Gate

Fail when the best non-dummy model does not beat the best dummy baseline by a meaningful margin.

## Stability Gate

Fail when fold variance suggests unstable performance.

## Feature Risk Gate

Fail when top-ranked features include:
- `hard_leakage`
- `post_outcome`

## Report Gate

Final report mode cannot exceed the maximum evidence grade allowed by the earlier gates.
