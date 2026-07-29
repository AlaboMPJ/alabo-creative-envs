"""Adapter from the standalone graders to the verifiers spec.

Design note worth keeping. The graders are subprocesses rather than imports.
That looks like the clumsier choice and it is the correct one here:

  - each grader needs a different heavy dependency (OpenEXR, PyOpenColorIO) and
    importing all of them into one process makes the environment unloadable if
    any single one is missing
  - a grader that crashes cannot take the training run with it
  - the exact same code path is exercised whether the grader is called by the
    container entrypoint, by a human at a terminal, or by the RL runtime, so
    there is one implementation and no drift

A reward function that behaves differently under training than it does at a
terminal is the worst failure mode available here, and this rules it out.
"""
import json
import os
import subprocess
import sys
import tempfile

import verifiers as vf
from datasets import Dataset

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ENV_DIR = os.path.join(ROOT, "environments")

ENVIRONMENTS = {
    "comfyui_graph_repair": {
        "artifact": "submission.json",
        "task_glob": "*.json",
        "exclude": ("_reference_good",),
        "summary": "Repair a ComfyUI API-format workflow until it validates and executes.",
    },
    "ocio_config_repair": {
        "artifact": "submission.ocio",
        "task_glob": "*.json",
        "exclude": ("_reference_good",),
        "summary": "Repair an OpenColorIO config that loads, renders, and is wrong.",
    },
    "exr_render_repair": {
        "artifact": "submission.exr",
        "task_glob": "*.json",
        "exclude": ("_reference_good",),
        "summary": "Repair a render handoff that opens cleanly and is wrong.",
    },
    # Added 2026-07-29. The environment existed and was not registered here, so
    # it graded fine at a terminal and did not exist at all under verifiers.
    # Its references are per-task (<id>_reference.mp4) rather than one shared
    # file, so the exclusion is by suffix.
    "video_conform_repair": {
        "artifact": "submission.mp4",
        "task_glob": "*.json",
        "exclude": ("_reference_good",),
        "summary": "Repair a conform that plays cleanly and is wrong.",
    },
}


def _tasks(env_id, cfg):
    import glob
    d = os.path.join(ENV_DIR, env_id, "tasks")
    out = []
    for p in sorted(glob.glob(os.path.join(d, cfg["task_glob"]))):
        name = os.path.basename(p)[:-5]
        if any(name.startswith(x) for x in cfg["exclude"]):
            continue
        with open(p) as f:
            spec = json.load(f)
        out.append((name, p, spec))
    return out


def _instruction(env_id):
    p = os.path.join(ENV_DIR, env_id, "instruction.md")
    return open(p).read() if os.path.exists(p) else ""


def _broken_payload(env_id, spec):
    """What the agent is shown. Text where the artifact is text, and a
    description where it is binary, because an EXR cannot go in a prompt."""
    if "broken_graph" in spec:
        return json.dumps(spec["broken_graph"], indent=2)
    for key in ("broken_config", "broken_file"):
        if key in spec:
            p = os.path.join(ENV_DIR, env_id, "tasks", spec[key])
            if p.endswith(".exr"):
                return (f"Binary render at {spec[key]}. Inspect it with OpenEXR; "
                        f"reported symptom: {spec.get('symptom', 'unknown')}")
            return open(p).read()
    return ""


def _grade(env_id, cfg, task_path, completion):
    """Run the real grader in its own process and return (reward, reason)."""
    grader = os.path.join(ENV_DIR, env_id, "tests", "grader.py")
    with tempfile.TemporaryDirectory() as tmp:
        sub = os.path.join(tmp, cfg["artifact"])
        text = completion if isinstance(completion, str) else str(completion)
        mode = "wb" if sub.endswith(".exr") else "w"
        data = text.encode("latin-1", "ignore") if mode == "wb" else text
        with open(sub, mode) as f:
            f.write(data)
        # Per-environment interpreter. A grader needs its own heavy dependency
        # and the runtime venv will not have it; running the wrong interpreter
        # made the OCIO grader silently degrade to structural-only and PASS a
        # broken config. Set CREATIVE_ENVS_PY_<ENV_ID> to the venv that has it.
        interp = os.environ.get(f"CREATIVE_ENVS_PY_{env_id.upper()}") or \
            os.environ.get("CREATIVE_ENVS_PY") or sys.executable
        try:
            r = subprocess.run([interp, grader, "--submission", sub,
                                "--task", task_path],
                               capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return 0.0, "grader timed out"
        if r.returncode == 2:
            # Environment error, not a failed attempt. Raising stops a training
            # run rather than silently feeding it zeros for every rollout.
            raise RuntimeError(
                f"{env_id} grader cannot run: "
                f"{(r.stderr or r.stdout or '').strip()[:200]}")
    line = (r.stdout or r.stderr or "").strip().splitlines()
    if not line:
        return 0.0, "grader produced no output"
    try:
        got = json.loads(line[-1])
        return float(got.get("reward", 0.0)), got.get("reason", "")
    except json.JSONDecodeError:
        return 0.0, f"grader output not JSON: {line[-1][:160]}"


def load_environment(env_id: str = "comfyui_graph_repair", **kwargs):
    """Entrypoint required by the verifiers spec."""
    if env_id not in ENVIRONMENTS:
        raise ValueError(f"unknown environment '{env_id}'. "
                         f"Available: {sorted(ENVIRONMENTS)}")
    cfg = ENVIRONMENTS[env_id]
    instruction = _instruction(env_id)
    tasks = _tasks(env_id, cfg)
    if not tasks:
        raise RuntimeError(f"no task instances for {env_id}; run the generator in tools/")

    rows, paths = [], {}
    for name, path, spec in tasks:
        prompt = (f"{instruction}\n\n## Task: {name}\n\n"
                  f"Reported symptom: {spec.get('symptom', spec.get('error', 'none'))}\n\n"
                  f"```\n{_broken_payload(env_id, spec)}\n```\n")
        rows.append({"question": prompt, "answer": "", "task": name})
        paths[name] = path

    dataset = Dataset.from_list(rows)

    def craft_correct(completion, answer="", **kw) -> float:
        """Binary. Partial credit would teach that a nearly-working comp is
        nearly right, which is false: it either renders correctly or it does not."""
        task = kw.get("task") or kw.get("info", {}).get("task")
        if task not in paths:
            return 0.0
        reward, _reason = _grade(env_id, cfg, paths[task], completion)
        return reward

    rubric = vf.Rubric(funcs=[craft_correct], weights=[1.0])
    return vf.SingleTurnEnv(dataset=dataset, rubric=rubric,
                            system_prompt=cfg["summary"], **kwargs)
