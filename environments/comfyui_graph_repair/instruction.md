# Repair the ComfyUI graph

You are given a ComfyUI workflow in API format that does not run.

Read `broken_graph.json`. The error ComfyUI produced is in `error.txt`, and it
may be misleading: ComfyUI often reports the symptom at a node downstream of the
actual fault, and a cycle produces no error at all, only a hang.

Write the repaired graph to `submission.json`.

## What the graph format is

An object keyed by node id. Each node has a `class_type` and an `inputs` object.
An input is either a literal value, or a link written as `[source_node_id, output_slot]`.

    {
      "3": {
        "class_type": "KSampler",
        "inputs": {
          "seed": 42,
          "steps": 20,
          "model":     ["4", 0],
          "positive":  ["6", 0],
          "negative":  ["7", 0],
          "latent_image": ["5", 0]
        }
      }
    }

## What counts as repaired

- every link points at a node that exists, at a valid output slot
- the graph has at least one output node, so the result leaves the graph
- there are no cycles
- every output node has real upstream work feeding it
- any node types and input values the task requires are present

## What you must not do

Do not delete the graph and write a minimal one that technically passes. The
repair must preserve the author's intent: same model, same prompt text, same
resolution, same sampler settings. The grader checks the requirements declared
in `task_instance.json`, and rebuilding from scratch will fail them.

Do not rename node ids that are referenced elsewhere unless you update every
reference.

## Scoring

Binary. The grader returns 1.0 only if every check passes, and a reason string
either way.
