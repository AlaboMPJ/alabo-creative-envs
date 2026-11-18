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


def check_structure(g, spec, ref=None):
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

    reachable = set()
    for s in sinks:
        u = upstream(s, set())
        if len(u) < 2:
            fail(f"output node {s} has no upstream graph")
        reachable |= u

    # A decoy sink fed by a stub satisfies "has an output" while the real graph
    # stays broken. So every required node type must sit upstream of some sink,
    # and the required types must all reach the SAME sink, which is what makes
    # it one working graph rather than two fragments.
    req = spec.get("required_class_types", [])
    if req:
        for sink in sinks:
            chain = upstream(sink, set())
            types_in_chain = {g[n]["class_type"] for n in chain}
            missing = [w for w in req if w not in types_in_chain]
            if missing:
                fail(f"output node {sink} does not have {missing} upstream. Every "
                     "output must be fed by the real graph; bolting on a second "
                     "save node fed by a stub is not a repair.")

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

    if ref:
        check_intent(g, ref)

    return sinks


def check_intent(g, ref):
    """Author intent survives the repair.

    The lazy rewrite is the standing adversary: delete the graph, submit a
    minimal one that satisfies every shape rule, and throw the author's work
    away. Shape checks cannot see it, because a stripped graph has the same
    shape as a repaired one. So every check here is against the KNOWN-GOOD
    REFERENCE, and every check is ID-AGNOSTIC: a node rebuilt with a fresh id is
    a legitimate repair, so the comparison is by class_type and by value, never
    by node id. A repair that renumbers the whole graph but keeps its wiring and
    its values passes, which is correct.
    """
    by_class = {}
    for node in g.values():
        by_class.setdefault(node["class_type"], []).append(node)

    # 1. every literal the author wrote survives somewhere on a node of its class
    for rnode in ref.values():
        cls = rnode["class_type"]
        for name, val in rnode["inputs"].items():
            if isinstance(val, list) and len(val) == 2:
                continue
            if not any(n["inputs"].get(name) == val for n in by_class.get(cls, [])):
                fail(f"author value lost: {cls} input '{name}' = {val!r} is in the "
                     "reference and nowhere in the submission. Rebuilding the graph "
                     "from scratch is not a repair.")

    # 2. every link the author made survives as a link between the same classes
    for rnode in ref.values():
        cls = rnode["class_type"]
        for name, val in rnode["inputs"].items():
            if not (isinstance(val, list) and len(val) == 2):
                continue
            want = ref[str(val[0])]["class_type"]
            ok = False
            for n in by_class.get(cls, []):
                link = n["inputs"].get(name)
                if (isinstance(link, list) and len(link) == 2
                        and str(link[0]) in g
                        and g[str(link[0])]["class_type"] == want):
                    ok = True
                    break
            if not ok:
                fail(f"author link lost: {cls} input '{name}' no longer comes "
                     f"from a {want}")

    # 3. the two conditionings stay two, and stay themselves. The positive and
    #    the negative must come from different encoders carrying the author's
    #    own texts. A direct link is assumed; going through a combine node is
    #    not a repair any of these faults asks for.
    rk = next((n for n in ref.values() if n["class_type"] == "KSampler"), None)
    if rk:
        pos_src = ref[str(rk["inputs"]["positive"][0])]
        neg_src = ref[str(rk["inputs"]["negative"][0])]
        for node in by_class.get("KSampler", []):
            pos, neg = node["inputs"].get("positive"), node["inputs"].get("negative")
            if not (isinstance(pos, list) and len(pos) == 2
                    and isinstance(neg, list) and len(neg) == 2):
                fail("KSampler is missing a positive or a negative conditioning")
            if str(pos[0]) == str(neg[0]):
                fail("positive and negative conditionings come from the same node, "
                     "so the negative prompt has no effect")
            for label, link, src in (("positive", pos, pos_src), ("negative", neg, neg_src)):
                srcn = g.get(str(link[0]))
                if srcn is None or srcn["class_type"] != src["class_type"]:
                    fail(f"KSampler {label} conditioning no longer comes from a "
                         f"{src['class_type']}")
                if srcn["inputs"].get("text") != src["inputs"].get("text"):
                    fail(f"KSampler {label} text is {srcn['inputs'].get('text')!r}, "
                         f"expected the author's {label} text "
                         f"{src['inputs'].get('text')!r}")


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

    # The known-good reference lives in the environment's own tasks/ directory and
    # travels with it into the container. It is resolved from THIS file's package
    # first, because a runner copies task_instance.json into a scratch working
    # directory and the reference is not beside that copy. Found by running the
    # container entrypoint in a clean namespace: beside-the-task resolution missed
    # and every intent check silently skipped, so the lazy rewrite scored 1.0
    # inside the sandbox while it was refused outside it.
    here = os.path.dirname(os.path.abspath(__file__))
    ref = None
    for cand in (os.path.join(here, "..", "tasks", "_reference_good.json"),
                 os.path.join(os.path.dirname(os.path.abspath(a.task)),
                              "_reference_good.json")):
        if os.path.exists(cand):
            ref = load(cand)
            break
    if ref is None:
        # A packaging fault, not a failed repair: exit non-zero so the runner
        # reports a broken environment rather than a zero score for the agent.
        print(json.dumps({"reward": None,
                          "reason": "environment error: no _reference_good.json beside "
                                    "the grader or the task, so author intent cannot be "
                                    "checked"}), file=sys.stderr)
        sys.exit(2)

    sinks = check_structure(g, spec, ref)

    note = "structure valid"
    if a.comfy_url:
        ran, why = check_executes(g, a.comfy_url, a.timeout)
        note = f"structure valid, {why}"

    ok(f"{note}; {len(g)} nodes, {len(sinks)} output node(s)")


if __name__ == "__main__":
    main()
