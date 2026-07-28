#!/usr/bin/env python3
"""Grader for ocio_config_repair.

Colour management is the purest case of silent wrongness in a post pipeline.
A broken OCIO config does not usually crash. It loads, the comp renders, the
shot delivers, and the colour is wrong. There is no error to read, so an agent
that pattern-matches on "did it run" learns nothing, and a grader that checks
"did it load" is worthless.

So this grades the thing that actually matters: does the config declare the
roles a pipeline depends on, do its transforms mean what they say, and does a
value survive a round trip through the working space.

Two grading levels. Structural always runs. Numeric runs when PyOpenColorIO is
importable, and that is where the subtle faults die: an inverted transform
direction produces a config that is valid, loadable, and quietly wrong.

Binary reward, with a reason either way.
"""
import json, os, sys, argparse

try:
    import yaml
except ImportError:
    print(json.dumps({"reward": 0.0,
                      "reason": "environment error: pyyaml missing"}), file=sys.stderr)
    sys.exit(2)

# Roles a compositing pipeline will look up by name. A config missing these
# loads fine and then fails at the point a DCC asks for them, which is late.
REQUIRED_ROLES = ["scene_linear", "color_picking", "data", "default"]


def fail(reason):
    print(json.dumps({"reward": 0.0, "reason": reason}))
    sys.exit(0)


def ok(reason):
    print(json.dumps({"reward": 1.0, "reason": reason}))
    sys.exit(0)


class _OCIOLoader(yaml.SafeLoader):
    """OCIO configs use custom YAML tags (!<ColorSpace>, !<ExponentTransform>).
    SafeLoader refuses them, so map every unknown tag to its plain value and
    keep the tag name, which is what the structural checks need."""


def _any_tag(loader, suffix, node):
    if isinstance(node, yaml.MappingNode):
        d = loader.construct_mapping(node, deep=True)
        d["_tag"] = suffix
        return d
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


_OCIOLoader.add_multi_constructor("", _any_tag)


def load_yaml(path, what):
    try:
        with open(path) as f:
            return yaml.load(f, Loader=_OCIOLoader)
    except FileNotFoundError:
        fail(f"no {what} at {path}")
    except yaml.YAMLError as e:
        fail(f"{what} is not valid YAML: {str(e)[:200]}")


def check_structure(cfg, spec):
    if not isinstance(cfg, dict):
        fail("config is not a mapping")

    for key in ("ocio_profile_version", "roles", "colorspaces"):
        if key not in cfg:
            fail(f"config has no '{key}' block")

    spaces = cfg["colorspaces"]
    if not isinstance(spaces, list) or not spaces:
        fail("colorspaces is empty")

    names = []
    for cs in spaces:
        if not isinstance(cs, dict) or "name" not in cs:
            fail("a colorspace entry has no name")
        names.append(cs["name"])
    if len(names) != len(set(names)):
        dupe = next(n for n in names if names.count(n) > 1)
        fail(f"duplicate colorspace name '{dupe}'; OCIO silently takes the last one")

    # 1. every role points at a colorspace that exists
    roles = cfg["roles"] or {}
    for role, target in roles.items():
        if target not in names:
            fail(f"role '{role}' points at colorspace '{target}', which does not exist")

    # 2. the roles a pipeline actually looks up
    for r in REQUIRED_ROLES:
        if r not in roles:
            fail(f"config is missing the required role '{r}'")

    # 3. exactly one reference space. OCIO defines the reference as the space
    #    with no transforms; two of them makes the graph ambiguous rather than
    #    invalid, which is the worst kind of fault.
    # OCIO v2 serialises to_scene_reference / from_scene_reference; v1 used
    # to_reference / from_reference. Read the real output before trusting either.
    def has_transform(cs):
        return any(cs.get(k) for k in ("to_reference", "from_reference",
                                       "to_scene_reference", "from_scene_reference"))

    refs = [cs["name"] for cs in spaces if not has_transform(cs) and not cs.get("isdata")]
    if len(refs) == 0:
        fail("no reference colorspace: every space declares a transform")
    if len(refs) > 1:
        fail(f"ambiguous reference space: {refs} all declare no transform")

    # 4. data spaces must not carry a colour transform. A data space that gets
    #    transformed corrupts depth, normals and mattes without any error.
    for cs in spaces:
        if cs.get("isdata") and has_transform(cs):
            fail(f"colorspace '{cs['name']}' is marked isdata but declares a transform, "
                 "which will corrupt depth and matte channels")

    # 5. the data role must point at a space actually marked isdata
    data_target = roles.get("data")
    data_cs = next((cs for cs in spaces if cs["name"] == data_target), None)
    if data_cs and not data_cs.get("isdata"):
        fail(f"role 'data' points at '{data_target}', which is not marked isdata")

    # 6. task-specific requirements
    for want in spec.get("required_colorspaces", []):
        if want not in names:
            fail(f"config is missing required colorspace '{want}'")
    for role, want in (spec.get("required_roles") or {}).items():
        if roles.get(role) != want:
            fail(f"role '{role}' is '{roles.get(role)}', expected '{want}'")

    return names, roles


def check_numeric(path, spec):
    """The subtle faults only die here. An inverted transform direction gives a
    config that loads, validates, and returns the wrong number."""
    try:
        import PyOpenColorIO as OCIO
    except ImportError:
        if spec.get("round_trips"):
            # This task cannot be graded without the numeric level, and its
            # fault is invisible structurally. Silently returning a pass would
            # reward a broken config in a training run, which is the worst
            # outcome available. Refuse instead.
            print(json.dumps({"reward": 0.0, "reason":
                "environment error: this task requires PyOpenColorIO for numeric "
                "grading and it is not installed. Refusing rather than passing "
                "a config whose fault is structurally invisible."}), file=sys.stderr)
            sys.exit(2)
        return None, "PyOpenColorIO not installed, structural grading only"

    try:
        cfg = OCIO.Config.CreateFromFile(path)
        cfg.validate()
    except Exception as e:
        fail(f"OCIO rejected the config: {str(e)[:220]}")

    scene_linear = cfg.getCanonicalName("scene_linear") or "scene_linear"
    for case in spec.get("round_trips", []):
        space, value, tol = case["colorspace"], case["value"], case.get("tolerance", 1e-4)
        expect = case.get("expect_encoded")
        try:
            fwd = cfg.getProcessor(scene_linear, space).getDefaultCPUProcessor()
            back = cfg.getProcessor(space, scene_linear).getDefaultCPUProcessor()
        except Exception as e:
            fail(f"no processor between scene_linear and '{space}': {str(e)[:180]}")
        # applyRGB returns a new list rather than mutating in place. Probed
        # against PyOpenColorIO 2.5.2 rather than assumed; assuming it cost an
        # hour and produced a grader that failed its own correct answer.
        encoded = fwd.applyRGB(list(value))
        decoded = back.applyRGB(list(encoded))
        for a, b in zip(decoded, value):
            if abs(a - b) > tol:
                fail(f"round trip through '{space}' does not return the input: "
                     f"{value} became {[round(v, 5) for v in decoded]}. "
                     "A transform direction is inverted.")
        # a transform that changes nothing is a transform that is not wired
        if all(abs(e - v) < 1e-9 for e, v in zip(encoded, value)) and not case.get("identity_ok"):
            fail(f"encoding into '{space}' returned the input unchanged, "
                 "so the transform is missing or a no-op")
        # Round-tripping passes even when BOTH directions are flipped, because
        # the inverse of an inverse still returns the input. So also assert the
        # encoded value against a known-correct number.
        if expect and any(abs(e - x) > tol for e, x in zip(encoded, expect)):
            fail(f"encoding {value} into '{space}' gave "
                 f"{[round(v, 4) for v in encoded]}, expected {expect}. "
                 "The transform direction is inverted.")

    return True, "round trips verified"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default="/env/submission.ocio")
    ap.add_argument("--task", default="/env/task_instance.json")
    a = ap.parse_args()

    with open(a.task) as f:
        spec = json.load(f)

    cfg = load_yaml(a.submission, "submission")
    names, roles = check_structure(cfg, spec)

    numeric, note = check_numeric(a.submission, spec)
    ok(f"{len(names)} colorspaces, {len(roles)} roles; {note}")


if __name__ == "__main__":
    main()
