#!/usr/bin/env sh
# Entrypoint the runner calls. Prints a single JSON line: {"reward": ..., "reason": ...}
# A failed task is a 0.0 reward and exit 0. Exit non-zero only when the
# environment itself is broken, because a broken environment reported as a
# failed task is the same silent wrongness this environment grades.
set -eu

ENV_DIR="${ENV_DIR:-/env}"
SUBMISSION="${SUBMISSION:-$ENV_DIR/submission.exr}"
TASK="${TASK:-$ENV_DIR/task_instance.json}"

if [ ! -f "$TASK" ]; then
  echo '{"reward": 0.0, "reason": "environment error: no task_instance.json mounted"}' >&2
  exit 2
fi

exec python3 "$ENV_DIR/tests/grader.py" \
  --submission "$SUBMISSION" \
  --task "$TASK" \
  --env-dir "$ENV_DIR"
