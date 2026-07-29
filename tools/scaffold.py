#!/usr/bin/env python3
"""Create a new environment with all five files present from the first minute.

What this generates is the boring half: the manifest, the instruction, the
container, the entrypoint and a grader skeleton. That half is why
exr_render_repair sat in the README as finished while having no instruction, no
task.toml and no Dockerfile. Somebody wrote the interesting part and stopped.

What it deliberately does NOT generate is the fault list or the checks. A model
asked to invent audio faults produces "the file is corrupted" and "wrong sample
rate", which are the faults that throw errors and are therefore worthless. The
whole product is the class that runs, errors nowhere, and is wrong: a negative
prompt wired to the positive encoder, depth normalised to 0-1, one mic inverted
in a stem set. That knowledge comes from standing in a room where it shipped, and
it is the only scarce thing here.

So this scaffolds. You supply the judgement.

    python3 tools/scaffold.py nuke_script_repair --app Nuke --ext .nk \\
        --area "Nuke scripts"

The generated grader refuses to score rather than returning 1.0, so a half-built
environment can never quietly pass. Touchstone will list it as incomplete until
its tasks exist, which is the correct state for it to be in.
"""
import argparse, os, sys, textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


TASK_TOML = '''[environment]
id = "{id}"
version = "0.1.0"
application = "{app}"
licence_required = {lic}
author = "Alabo"

[reward]
type = "binary"
pass = 1.0
fail = 0.0
# No partial credit. The deliverable is either correct for the department
# downstream or it is not.

[grading]
entrypoint = "tests/test.sh"
grader = "tests/grader.py"

[agent]
reads = ["task_instance.json", "broken{ext}"]
writes = ["submission{ext}"]
max_turns = 25

# One block per fault. Every one must be a fault that RUNS: no error, no warning,
# delivers cleanly, and is wrong. If it raises an exception it does not belong
# here, because the tooling already catches those.
#
# [[tasks]]
# id = ""
# file = "tasks/.json"
# difficulty = "easy"       # easy, medium, hard
# skill = "what a person has to know, said as a sentence"
'''

INSTRUCTION = '''# Repair the {app} file

You are given a {app} file that opens, reads and delivers, and is wrong.

Nothing in this task will raise an error, and that is the point.

Read `task_instance.json` for the symptom, which is what an artist said and is a
description of what they saw rather than of the cause. Read `broken{ext}`.

Write the repaired file to `submission{ext}`.

## What you are given

<!-- List the keys that appear in task_instance.json and what each one means. -->

## What the grader checks

<!-- Each check as a statement about craft, then the arithmetic behind it. Write
     these so a practitioner reads them and agrees before seeing any code. -->

## The rule that matters most

Everything the repair was not supposed to touch is compared against a known-good
reference and must match, and everything it was allowed to touch must still
correlate with the original. Satisfying the rules while destroying the data is
not a repair and is graded as a failure.

## Reward

Binary. 1.0 if every check passes, 0.0 otherwise, with the specific reason
either way.
'''

DOCKERFILE = '''FROM python:3.12-slim
RUN pip install --no-cache-dir {pip} && useradd -m agent
WORKDIR /env
COPY tests/ /env/tests/
COPY tasks/ /env/tasks/
COPY instruction.md task.toml /env/
RUN chmod +x /env/tests/test.sh && chown -R agent:agent /env
USER agent
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["/env/tests/test.sh"]
'''

TEST_SH = '''#!/usr/bin/env sh
# Entrypoint the runner calls. Prints one JSON line: {{"reward": ..., "reason": ...}}
# A failed task is a 0.0 and exit 0. Exit non-zero only when the environment
# itself is broken, because a broken environment reported as a failed task is the
# same silent wrongness this grades.
set -eu

ENV_DIR="${{ENV_DIR:-/env}}"
SUBMISSION="${{SUBMISSION:-$ENV_DIR/submission{ext}}}"
TASK="${{TASK:-$ENV_DIR/task_instance.json}}"

if [ ! -f "$TASK" ]; then
  echo '{{"reward": 0.0, "reason": "environment error: no task_instance.json mounted"}}' >&2
  exit 2
fi

exec python3 "$ENV_DIR/tests/grader.py" \\
  --submission "$SUBMISSION" \\
  --task "$TASK" \\
  --env-dir "$ENV_DIR"
'''

GRADER = '''#!/usr/bin/env python3
"""Grader for {id}.

Every check below has to be a statement about craft expressed as arithmetic. That
is the whole product: anyone can write the container, and almost nobody can write
these.

Write the checks before writing the tasks. A check you cannot state as a sentence
a supervisor would say out loud is not ready to be code yet.
"""
import argparse, json, os, sys


def fail(reason):
    print(json.dumps({{"reward": 0.0, "reason": reason}}))
    sys.exit(0)


def ok(reason):
    print(json.dumps({{"reward": 1.0, "reason": reason}}))
    sys.exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default="/env/submission{ext}")
    ap.add_argument("--task", default="/env/task_instance.json")
    ap.add_argument("--env-dir", default="/env")
    a = ap.parse_args()

    spec = json.load(open(a.task))
    if not os.path.exists(a.submission):
        fail(f"no submission at {{a.submission}}")

    # An unfinished grader must never hand out a point. Returning 1.0 by default
    # is how a stub environment gets published looking finished, so this refuses
    # to score at all until the checks below exist.
    print(json.dumps({{
        "reward": 0.0,
        "reason": "environment error: {id} has no checks implemented yet",
    }}), file=sys.stderr)
    sys.exit(2)

    # ---- checks go here -------------------------------------------------
    #
    # 1. Structural: names and shapes a downstream department looks up.
    # 2. Numeric: the craft fault, expressed as arithmetic over the data.
    # 3. Reference: everything outside spec["may_change"] must match the known
    #    good file exactly, and everything inside it must still correlate with
    #    the original. Without this an agent satisfies every rule by writing a
    #    constant, and seven of twelve attacks did exactly that on the first
    #    environment.
    #
    # ok(f"all craft checks passed")


if __name__ == "__main__":
    main()
'''


def write(path, body, executable=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        print(f"  skip (exists)  {os.path.relpath(path, ROOT)}")
        return
    open(path, "w", encoding="utf-8").write(body)
    if executable:
        os.chmod(path, 0o755)
    print(f"  wrote          {os.path.relpath(path, ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id", help="environment id, snake_case, e.g. nuke_script_repair")
    ap.add_argument("--app", required=True, help="application name, e.g. Nuke")
    ap.add_argument("--ext", required=True, help="submission extension, e.g. .nk")
    ap.add_argument("--area", default="", help="plain-English area for Touchstone")
    ap.add_argument("--pip", default="numpy", help="pip packages the grader needs")
    ap.add_argument("--licence-required", action="store_true",
                    help="set when the app needs a licence inside the container")
    ap.add_argument("--root", default=os.path.join(ROOT, "environments"))
    a = ap.parse_args()

    if not a.id.replace("_", "").isalnum():
        sys.exit("  id must be snake_case alphanumeric")
    base = os.path.join(a.root, a.id)
    fmt = dict(id=a.id, app=a.app, ext=a.ext, pip=a.pip,
               lic="true" if a.licence_required else "false")

    print(f"\n  scaffolding {a.id}\n")
    write(os.path.join(base, "task.toml"), TASK_TOML.format(**fmt))
    write(os.path.join(base, "instruction.md"), INSTRUCTION.format(**fmt))
    write(os.path.join(base, "environment", "Dockerfile"), DOCKERFILE.format(**fmt))
    write(os.path.join(base, "tests", "test.sh"), TEST_SH.format(**fmt), True)
    write(os.path.join(base, "tests", "grader.py"), GRADER.format(**fmt))
    os.makedirs(os.path.join(base, "tasks"), exist_ok=True)
    print(f"  made           environments/{a.id}/tasks/")

    print(textwrap.dedent(f"""
      All five files exist, so it is structurally distributable from now on.

      What is left is the only part that cannot be generated:

        1. Name the faults. Each one must RUN, error nowhere, deliver, and be
           wrong. If it throws, the tooling already catches it and it is not a
           task.
        2. Write the checks in tests/grader.py, as arithmetic.
        3. Make a known-good reference and the broken files in tasks/.
        4. Add an attack to tools/reward_hack.py for every check, and expect
           roughly half to breach on the first run.

      Then: .venv-vf/bin/python tools/touchstone.py --out touchstone.html
      It will list {a.id} as incomplete until the tasks exist, which is correct.
    """))


if __name__ == "__main__":
    main()
