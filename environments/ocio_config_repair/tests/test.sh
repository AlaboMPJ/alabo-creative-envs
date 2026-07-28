#!/usr/bin/env sh
set -eu
ENV_DIR="${ENV_DIR:-/env}"
[ -f "${TASK:-$ENV_DIR/task_instance.json}" ] || {
  echo '{"reward": 0.0, "reason": "environment error: no task_instance.json mounted"}' >&2; exit 2; }
exec python3 "$ENV_DIR/tests/grader.py" \
  --submission "${SUBMISSION:-$ENV_DIR/submission.ocio}" \
  --task "${TASK:-$ENV_DIR/task_instance.json}"
