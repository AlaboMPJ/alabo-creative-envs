# Creative-tool RL environments

Verifiable agent environments for professional creative software.

Agents are now good at code and weak at the tools working artists actually use.
The reason is not model capability, it is verification: there is no programmatic
way to say whether an agent repaired a Nuke script, wired a ComfyUI graph, or
built a Max patch correctly. Coding tasks have unit tests. A node graph has an
artist looking at it.

This repo builds the missing half. Each environment ships a container, a task,
and a grader that returns a binary reward without a human in the loop.

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

## Reward design

Binary, and deliberately strict. Partial credit teaches an agent that a graph
which nearly runs is nearly right, which is false: a comp either renders or it
does not. Each grader returns a reason string so failures are debuggable rather
than mysterious.

Graders check structure and execution, never pixel similarity against a golden
image, because a correct repair can legitimately produce different pixels.

## Run

    cd environments/comfyui_graph_repair
    docker build -t comfyui-graph-repair environment/
    docker run --rm -v "$PWD:/env" comfyui-graph-repair /env/tests/test.sh

## Provenance

Task instances are authored from working graphs, then broken deterministically
by `tools/break_graph.py`, so every task has a known-good solution and the
break is reproducible from a seed. No scraped workflows, no third-party assets.

## Author

Alabo. Compositor and pipeline engineer. These are built from working bridges
into Nuke, Houdini, TouchDesigner, Max, Unreal, CLO3D and ComfyUI.
