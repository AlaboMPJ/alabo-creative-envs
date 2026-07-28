#!/usr/bin/env python3
"""Batch assessment runner.

For someone who is not going to run Docker. Point it at a folder of
submissions, get a report. One row per person, pass or fail per task, and the
exact reason for every failure so a tutor or a hiring lead can check the
grader's judgement rather than trust it.

    python3 tools/assess.py --env ocio_config_repair --submissions ./cohort
    python3 tools/assess.py --env ocio_config_repair --submissions ./cohort \
        --task inverted_direction --csv report.csv

Expected layout, with one file per person named after them:

    cohort/
      ada-lovelace.ocio
      grace-hopper.ocio

If a submission covers several tasks, put it in a folder per person instead and
the runner will look for <task>.<ext> inside it.

Design note: the report always prints the reason, never just a score. A grader
you cannot argue with is a grader nobody will trust with a real decision, and
the first thing a good tutor does is check whether the machine was right.
"""
import argparse, csv, glob, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVS = os.path.join(ROOT, "environments")
EXT = {"comfyui_graph_repair": ".json",
       "ocio_config_repair": ".ocio",
       "exr_render_repair": ".exr"}


def tasks_for(env):
    d = os.path.join(ENVS, env, "tasks")
    out = []
    for p in sorted(glob.glob(os.path.join(d, "*.json"))):
        name = os.path.basename(p)[:-5]
        if not name.startswith("_reference"):
            out.append(name)
    return out


def grade(env, submission, task, interp):
    r = subprocess.run(
        [interp, os.path.join(ENVS, env, "tests", "grader.py"),
         "--submission", submission,
         "--task", os.path.join(ENVS, env, "tasks", f"{task}.json")],
        capture_output=True, text=True, timeout=180)
    if r.returncode == 2:
        return None, f"environment error: {(r.stderr or '').strip()[:120]}"
    lines = (r.stdout or r.stderr or "").strip().splitlines()
    if not lines:
        return 0.0, "grader produced no output"
    try:
        got = json.loads(lines[-1])
        return float(got.get("reward", 0.0)), got.get("reason", "")
    except json.JSONDecodeError:
        return 0.0, lines[-1][:120]


def find_submissions(folder, env):
    ext = EXT[env]
    found = {}
    for p in sorted(glob.glob(os.path.join(folder, "*"))):
        name = os.path.basename(p)
        if os.path.isdir(p):
            found[name] = {os.path.basename(f)[: -len(ext)]: f
                           for f in glob.glob(os.path.join(p, f"*{ext}"))}
        elif name.endswith(ext):
            found[name[: -len(ext)]] = {"*": p}
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True, choices=sorted(EXT))
    ap.add_argument("--submissions", required=True)
    ap.add_argument("--task", help="grade one task only")
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter with the grader's dependency installed")
    ap.add_argument("--csv", help="also write a CSV")
    a = ap.parse_args()

    tasks = [a.task] if a.task else tasks_for(a.env)
    people = find_submissions(a.submissions, a.env)
    if not people:
        print(f"no {EXT[a.env]} submissions found in {a.submissions}")
        sys.exit(1)

    print(f"\n  {a.env}  ·  {len(people)} submissions  ·  {len(tasks)} task(s)\n")
    rows, env_errors = [], 0
    for person in sorted(people):
        files = people[person]
        passed = 0
        print(f"  {person}")
        for t in tasks:
            path = files.get(t) or files.get("*")
            if not path:
                print(f"      {'-':<7} {t}  (no submission)")
                rows.append({"person": person, "task": t, "result": "missing",
                             "reason": ""})
                continue
            reward, reason = grade(a.env, path, t, a.python)
            if reward is None:
                env_errors += 1
                print(f"      ERROR   {t}  {reason}")
                rows.append({"person": person, "task": t, "result": "error",
                             "reason": reason})
                continue
            mark = "pass" if reward == 1.0 else "FAIL"
            passed += int(reward == 1.0)
            print(f"      {mark:<7} {t}")
            if reward != 1.0:
                print(f"              {reason}")
            rows.append({"person": person, "task": t,
                         "result": "pass" if reward == 1.0 else "fail",
                         "reason": reason})
        print(f"      {passed}/{len(tasks)}\n")

    if env_errors:
        print(f"  {env_errors} task(s) could not be graded. Install the grader's "
              f"dependency and pass --python. Results are not complete.\n")

    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["person", "task", "result", "reason"])
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {a.csv}\n")

    # A per-task failure rate is the most useful line for whoever ran this: it
    # says which idea the cohort does not hold, which is a teaching finding
    # rather than a grading one.
    print("  failure rate by task, which is the interesting number:\n")
    for t in tasks:
        rs = [r for r in rows if r["task"] == t and r["result"] in ("pass", "fail")]
        if not rs:
            continue
        failed = sum(1 for r in rs if r["result"] == "fail")
        print(f"    {failed}/{len(rs)}  {t}")
    print()


if __name__ == "__main__":
    main()
