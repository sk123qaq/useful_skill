# Monitoring Protocol

Long-running jobs must write:
- heartbeat timestamps
- append-only event logs
- a final status file

## States

- `running`
- `stalled`
- `failed`
- `completed`

## Rules

- A monitored job should emit heartbeat on a regular interval while useful work is happening.
- If heartbeat goes stale beyond the configured threshold, mark the job `stalled`.
- Failures should write a traceback file path into the final status payload.
