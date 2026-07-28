#!/usr/bin/env python3
"""Grader for comfyui_graph_repair.

Binary reward. A ComfyUI API-format graph is correct when it satisfies every
structural invariant the executor relies on, and then actually executes.

Deliberately NOT pixel comparison against a golden image: a legitimate repair
can produce different pixels (a different but valid sampler wiring, a rebuilt
node with a fresh id). Grading pixels would punish correct answers, which is
the classic way a creative-tool grader goes wrong.

Exit 0 with reward 1.0 on pass, reward 0.0 on fail, always with a reason.
"""
import json, os, sys, argparse, urllib.request, urllib.error, time

# Node types whose output is a finished image leaving the graph.
SINK_TYPES = {"SaveImage", "PreviewImage", "SaveAnimatedWEBP", "VHS_VideoCombine"}


def fail(reason):
    print(json.dumps({"reward": 0.0, "reason": reason}))
    sys.exit(0)


def ok(reason="all checks passed"):
    print(json.dumps({"reward": 1.0, "reason": reason}))
    sys.exit(0)


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"no submission at {path}")
    except json.JSONDecodeError as e:
        fail(f"submission is not valid JSON: {e}")


def check_structure(g, spec):
    """The invariants ComfyUI's executor assumes. Each one is a real failure
    mode seen in practice, not a synthetic rule."""
    if not isinstance(g, dict) or not g:
        fail("graph is empty or not an object")

    for nid, node in g.items():
        if not isinstance(node, dict):
            fail(f"node {nid} is not an object")
        if "class_type" not in node:
            fail(f"node {nid} has no class_type")
        if "inputs" not in node or not isinstance(node["inputs"], dict):
            fail(f"node {nid} has no inputs object")

    # 1. every link points at a node that exists, and at a plausible slot
    for nid, node in g.items():
        for name, val in node["inputs"].items():
            if isinstance(val, list) and len(val) == 2:
                src, slot = val
                if str(src) not in g:
                    fail(f"node {nid} input '{name}' links to missing node {src}")
                if not isinstance(slot, int) or slot < 0:
                    fail(f"node {nid} input '{name}' has bad output slot {slot!r}")

    # 2. at least one sink, or nothing ever leaves the graph
    sinks = [n for n, nd in g.items() if nd["class_type"] in SINK_TYPES]
    if not sinks:
        fail("graph has no output node, so nothing is ever saved")

    # 3. no cycles: ComfyUI's executor deadlocks rather than erroring cleanly
    colour = {}

    def visit(n):
        colour[n] = 1
        for val in g[n]["inputs"].values():
            if isinstance(val, list) and len(val) == 2:
                s = str(val[0])
                if colour.get(s) == 1:
                    fail(f"cycle in graph through node {s}")
                if s in g and colour.get(s, 0) == 0:
                    visit(s)
        colour[n] = 2

    for n in g:
        if colour.get(n, 0) == 0:
            visit(n)

    # 4. every sink is reachable from a real source, not floating
    def upstream(n, seen):
        seen.add(n)
        for val in g[n]["inputs"].values():
            if isinstance(val, list) and len(val) == 2:
                s = str(val[0])
                if s in g and s not in seen:
                    upstream(s, seen)
        return seen

    for s in sinks:
        if len(upstream(s, set())) < 2:
            fail(f"output node {s} has no upstream graph")

    # 5. task-specific requirements, declared per instance
    for req in spec.get("required_class_types", []):
        if not any(nd["class_type"] == req for nd in g.values()):
            fail(f"graph is missing a required node of type {req}")

    for nid, name, want in spec.get("required_input_values", []):
        node = g.get(str(nid))
        if node is None:
            fail(f"expected node {nid} to exist")
        got = node["inputs"].get(name)
        if got != want:
            fail(f"node {nid} input '{name}' is {got!r}, expected {want!r}")

    return sinks


def check_executes(g, comfy_url, timeout):
    """Optional live check. Structure can be valid and the graph still refuse
    to run (a real node type that does not exist in this install, a tensor
    shape mismatch). If ComfyUI is not reachable, skip rather than fail: the
    structural pass is still a meaningful reward signal."""
    try:
        req = urllib.request.Request(
            comfy_url.rstrip("/") + "/prompt",
            data=json.dumps({"prompt": g}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
        if body.get("node_errors"):
            fail(f"ComfyUI rejected the graph: {json.dumps(body['node_errors'])[:300]}")
        return True, "accepted by ComfyUI"
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        fail(f"ComfyUI returned {e.code}: {detail}")
    except Exception:
        return False, "ComfyUI not reachable, structural grading only"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default="/env/submission.json")
    ap.add_argument("--task", default="/env/task_instance.json")
    ap.add_argument("--comfy-url", default=os.environ.get("COMFY_URL", ""))
    ap.add_argument("--timeout", type=int, default=30)
    a = ap.parse_args()

    spec = load(a.task)
    g = load(a.submission)

    sinks = check_structure(g, spec)

    note = "structure valid"
    if a.comfy_url:
        ran, why = check_executes(g, a.comfy_url, a.timeout)
        note = f"structure valid, {why}"

    ok(f"{note}; {len(g)} nodes, {len(sinks)} output node(s)")


if __name__ == "__main__":
    main()
