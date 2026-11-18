# Creative-tool RL environments

Verifiable agent environments for professional creative software.

Agents are now good at code and weak at the tools working artists actually use.
The reason is not model capability, it is verification: there is no programmatic
way to say whether an agent repaired a Nuke script, wired a ComfyUI graph, or
built a Max patch correctly. Coding tasks have unit tests. A node graph has an
artist looking at it.

This repo builds the missing half. Each environment ships a container, a task,
and a grader that returns a binary reward without a human in the loop.

![17 tasks, every reference 1.0, every planted fault 0.0](docs/verification-card.png)

## Why these are hard to author

Not because the harness is hard. Because writing the grader requires knowing
what correct looks like in the application, and that knowledge sits with senior
artists rather than with ML engineers. A grader for "is this comp correct" is a
statement about craft, expressed as code.

## Environments

| id | application | task | licence needed |
|---|---|---|---|
| `comfyui_graph_repair` | ComfyUI | repair a broken API-format workflow until it validates and executes | none |
| `ocio_config_repair` | OpenColorIO | repair a colour config that loads, renders, and is wrong | none |
| `exr_render_repair` | OpenEXR | repair a render handoff that opens cleanly and is wrong | none |
| `video_conform_repair` | FFmpeg | repair a clip that plays perfectly and is wrong | none |


`video_conform_repair` grades editorial craft on files that are never invalid: a
camera's auto-exposure ramp shipped in the cut, a portrait source squashed onto a
landscape canvas, and a cross-fade chain whose offsets were measured against the
raw timeline instead of the assembly, which drops a whole clip while ffmpeg
reports success. All three faults were met on real hardware on 2026-07-29 driving
a DJI Osmo Pocket 3 into a headless capture tool, rather than invented for the
environment. Its graders measure the picture: a disc must stay round, edges must
be black where material was fitted rather than cropped, and the midpoint of a
dissolve must be a genuine blend. Nine adversarial attacks are held in
`tools/hack_video.py` and all nine score zero.

`exr_render_repair` grades the render-to-comp handoff, which is the widest
silent-wrongness surface in a pipeline: depth normalised to 0-1 so every defocus
is at the wrong distance, colour premultiplied twice so edges go dark, normals
that are not unit length, AOVs renamed so a conform cannot find them, and a
32-bit float file carrying only 8-bit information. None of them raise an error.

`ocio_config_repair` grades the hardest and most valuable class: silent
wrongness. Four of its five faults produce no error at all. The fifth,
`inverted_direction`, passes every structural check and is only caught
numerically, by encoding a value into a colourspace and decoding it back.

Planned, not built: a Nuke script-repair environment. It needs a Nuke licence
inside the container and a running instance to render the check frame, which is
the licence gate that keeps this space empty and is exactly why it is worth
building. It is not listed above until it exists.

`comfyui_graph_repair` is first deliberately: ComfyUI is free, so anyone can run
and reproduce it. The Nuke environment needs a licence in the container, which
is precisely why almost nobody else can build it.

## Spec

Each environment follows the now-conventional layout:

    environments/<id>/
      task.toml              # metadata, reward shape, task list
      instruction.md         # what the agent is told
      environment/Dockerfile # the sandbox
      tests/test.sh          # entrypoint the runner calls
      tests/grader.py        # returns 1.0 or 0.0, and a reason
      tasks/*.json           # task instances

## Adversarial testing

    python3 tools/reward_hack.py --python-ocio <venv>/bin/python \
                                 --python-exr  <venv>/bin/python

Twelve attacks that try to score full reward while leaving the fault in place.
The first run breached seven of them, and the pattern was consistent: the
graders checked shape and not content, so an agent could satisfy every rule and
destroy the data. A flat constant depth cleared a range check. Random normals
renormalised to unit length cleared a length check. Adding noise at 1e-7 cleared
a distinct-value count. A second save node fed by a stub cleared "has an output".

All twelve now hold, and the exit code is the breach count so it can gate a
release.

The graph-repair attacks live in a NAMED library per domain rather than in the
runner, because every gate in the estate already carries planted known-bads and
the list is the reusable half:

    python3 tools/mutants.py --domain graph_repair
    python3 tools/mutants.py --list
    python3 tools/mutants.py --selftest

`mutants/graph_repair.json` holds five mutants, each with a name, the lazy path
it takes, and the check it must be refused by. The runner judges both
directions: the reference must score 1.0 or the grader is hostile, and every
mutant must score 0.0 with a reason naming the declared check, so a refusal is
earned rather than incidental. `tools/reward_hack.py` reads the same files, so
the two passes cannot drift. The selftest validates the runner itself, including
that an accepted mutant IS reported.

One attack also exposed a flaw in the task design rather than the grader:
normalising depth destroys the original range, so no agent could have recovered
scene units. The task now states the camera near and far, which makes it
solvable and the hack impossible.

## Reward design

Binary, and deliberately strict. Partial credit teaches an agent that a graph
which nearly runs is nearly right, which is false: a comp either renders or it
does not. Each grader returns a reason string so failures are debuggable rather
than mysterious.

Graders check structure and execution, never pixel similarity against a golden
image, because a correct repair can legitimately produce different pixels.

## Run

    cd environments/comfyui_graph_repair
    docker build -t comfyui-graph-repair -f environment/Dockerfile .
    docker run --rm -v "$PWD:/env" comfyui-graph-repair /env/tests/test.sh

The build context is the ENVIRONMENT directory and the Dockerfile is passed with
-f. Every Dockerfile here copies `tests/`, `tasks/`, `instruction.md` and
`task.toml`, and none of those live inside `environment/`, so building with
`environment/` as the context fails on the first COPY.

On a machine with no container runtime, `tools/cleanroom.sh` runs the same
entrypoint in a clean mount and network namespace, with only the environment
directory visible and no site packages:

    tools/cleanroom.sh environments/comfyui_graph_repair \
        environments/comfyui_graph_repair/tasks/_reference_good.json \
        environments/comfyui_graph_repair/tasks/sdxl_dangling_latent.json

It is not a substitute for the image build on a machine that has Docker. On
2026-09-22 it caught a packaging bug the local runs could not: the grader
resolved the known-good reference beside the TASK file, and a runner copies
`task_instance.json` into a scratch directory, so inside the sandbox the
reference was out of reach and every intent check silently skipped.

## Trajectories

`ala-traj` logs an agent's trajectory through an environment and audits it
against the reference repair: the prompt, the raw reply, the submitted graph,
the exact edits from the broken graph, the grader's verdict, the agent's stated
confidence, and an audit verdict (optimal, sufficient, wasteful, stuck). It runs
a local model over the ollama HTTP API with no SDK, and it accepts external
submissions with `ala-traj log --from submission.json`, so any harness can feed
the same corpus.

    ala-traj run --task sdxl_dangling_latent --model qwen2.5-coder:14b --seed 1
    ala-traj audit --dir trajectories/comfyui_graph_repair
    ala-traj mine  --dir trajectories/comfyui_graph_repair

The first ten trajectories, and the audit of them, are in
`environments/comfyui_graph_repair/AUDIT.md`.

## Provenance

Task instances are authored from working graphs, then broken deterministically
by `tools/break_graph.py`, so every task has a known-good solution and the
break is reproducible from a seed. No scraped workflows, no third-party assets.

## Author

Alabo. Compositor and pipeline engineer. These are built from working bridges
into Nuke, Houdini, TouchDesigner, Max, Unreal, CLO3D and ComfyUI.

## Running under the verifiers spec

The graders are the source of truth and run standalone with no ML dependency.
`creative_envs` is a thin adapter so the same graders load under the verifiers
runtime and can be pushed to an environments hub.

    pip install -e ".[all]"
    python -c "import creative_envs; print(creative_envs.load_environment('exr_render_repair'))"

Each grader needs its own heavy dependency, so point the adapter at the
interpreter that has it:

    export CREATIVE_ENVS_PY_OCIO_CONFIG_REPAIR=/path/to/venv-with-opencolorio/bin/python
    export CREATIVE_ENVS_PY_EXR_RENDER_REPAIR=/path/to/venv-with-openexr/bin/python

This matters more than it looks. Run the OCIO grader on an interpreter without
PyOpenColorIO and it degrades to structural checks only, which silently PASSES
the inverted-transform task because that fault is structurally invisible. A
reward function that quietly degrades will train a model on a broken config.
Tasks that require numeric grading now exit with an environment error instead,
and the adapter raises rather than returning zero.

## Verification, 2026-11-19

The packages were executed against `verifiers==0.4.1` in an isolated venv, installed from the
built package rather than run from the source directory, so the test also proves `tasks/` and
`tests/` are packaged.

    env            SingleAgentEnv (verifiers v1)
    taskset        comfyui_graph_repair
    tasks          4: feedback_cycle, missing_vae_decode, orphaned_conditioning, sdxl_dangling_latent
    good graph     1.0 on every task
    planted fault  0.0 on every task, each with its own reason

The four faults are a dangling latent link, a missing VAEDecode upstream of the save node, a cycle
the executor deadlocks on, and a negative prompt wired to the same conditioning as the positive.

The previous entrypoint used `vf.SingleTurnEnv` and `vf.Rubric`, which no longer exist in verifiers
0.4.1: `load_environment()` fails with `AttributeError: module 'verifiers' has no attribute
'SingleTurnEnv'`. The v1 rewrite is therefore a requirement rather than a preference.

All four packages were then installed into one venv from their wheels and executed through the v1
`Task.score` path: 17 task instances, 1.0 on every good reference and 0.0 on every planted fault
(comfyui 4, OCIO 5, EXR 5, video 3). The run found and fixed two packaging faults: binary artefacts
had no path through the reward, and four packages installed together merged their top-level
`tasks/` and `tests/` directories, so each module read all four task sets. Data now ships as
`<env_id>_tasks`, `<env_id>_tests` and `<env_id>_instruction.md`.
