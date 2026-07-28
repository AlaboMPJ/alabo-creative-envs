#!/usr/bin/env sh
# Entrypoint the runner calls. Prints a single JSON line: {"reward": ..., "reason": ...}
# Never exits non-zero on a failed task; a failed task is a 0.0 reward, not a
# broken environment. Exit non-zero only when the environment itself is broken.
set -eu

ENV_DIR="${ENV_DIR:-/env}"
SUBMISSION="${SUBMISSION:-$ENV_DIR/submission.json}"
TASK="${TASK:-$ENV_DIR/task_instance.json}"

if [ ! -f "$TASK" ]; then
  echo '{"reward": 0.0, "reason": "environment error: no task_instance.json mounted"}' >&2
  exit 2
fi

exec python3 "$ENV_DIR/tests/grader.py" \
  --submission "$SUBMISSION" \
  --task "$TASK" \
  ${COMFY_URL:+--comfy-url "$COMFY_URL"}
