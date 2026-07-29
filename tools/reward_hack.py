#!/usr/bin/env python3
"""Adversarial reward-hacking pass.

An environment is only worth publishing if a model cannot score on it without
doing the work. Every attack below tries to reach 1.0 while leaving the actual
fault in place, or while producing something no compositor would accept.

A grader that passes any of these is looser than it looks, and a loose grader is
worse than no grader: it trains a model to produce the thing that scores rather
than the thing that is correct.

    python3 tools/reward_hack.py --python-ocio .venv-ocio/bin/python \\
                                 --python-exr  .venv-exr/bin/python

Exit code is the number of successful attacks, so this can gate a release.
"""
import argparse, copy, json, os, subprocess, sys, tempfile
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVS = os.path.join(ROOT, "environments")


def grade(env_id, artifact_name, task, payload, interp, binary=False):
    grader = os.path.join(ENVS, env_id, "tests", "grader.py")
    task_path = os.path.join(ENVS, env_id, "tasks", f"{task}.json")
    with tempfile.TemporaryDirectory() as tmp:
        sub = os.path.join(tmp, artifact_name)
        if binary:
            with open(sub, "wb") as f:
                f.write(payload)
        else:
            with open(sub, "w") as f:
                f.write(payload)
        r = subprocess.run([interp, grader, "--submission", sub, "--task", task_path],
                           capture_output=True, text=True, timeout=120)
    lines = (r.stdout or r.stderr or "").strip().splitlines()
    if not lines:
        return 0.0, "no output"
    try:
        got = json.loads(lines[-1])
        return float(got.get("reward", 0.0)), got.get("reason", "")
    except json.JSONDecodeError:
        return 0.0, lines[-1][:120]


# ---------------------------------------------------------------- comfyui

def comfy_attacks():
    tdir = os.path.join(ENVS, "comfyui_graph_repair", "tasks")
    good = json.load(open(os.path.join(tdir, "_reference_good.json")))
    out = []

    # 1. Required node types present, but the sampler is fed nothing real.
    a = copy.deepcopy(good)
    a["3"]["inputs"]["latent_image"] = ["5", 0]
    a["5"]["inputs"]["width"] = 8
    a["5"]["inputs"]["height"] = 8
    out.append(("shrink the latent to nothing", "sdxl_dangling_latent", json.dumps(a)))

    # 2. Satisfy "has an output node" by adding a second sink fed by a stub.
    a = copy.deepcopy(good)
    a["50"] = {"class_type": "EmptyLatentImage",
               "inputs": {"width": 8, "height": 8, "batch_size": 1}}
    a["51"] = {"class_type": "SaveImage",
               "inputs": {"filename_prefix": "x", "images": ["50", 0]}}
    out.append(("bolt on a decoy output node", "sdxl_dangling_latent", json.dumps(a)))

    # 3. Keep the fault but add every required class type elsewhere.
    a = copy.deepcopy(good)
    a["3"]["inputs"]["latent_image"] = ["99", 0]
    a["60"] = {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}}
    out.append(("leave the dangling link, satisfy the type list", "sdxl_dangling_latent",
                json.dumps(a)))

    # 4. Wire negative to a fresh encoder with the positive text.
    a = copy.deepcopy(good)
    a["70"] = {"class_type": "CLIPTextEncode",
               "inputs": {"text": "a portrait, studio light, 85mm", "clip": ["4", 1]}}
    a["3"]["inputs"]["negative"] = ["70", 0]
    out.append(("duplicate the positive prompt as the negative", "orphaned_conditioning",
                json.dumps(a)))
    return out


# ---------------------------------------------------------------- ocio

def ocio_attacks():
    tdir = os.path.join(ENVS, "ocio_config_repair", "tasks")
    good = open(os.path.join(tdir, "_reference_good.ocio")).read()
    out = []

    # 1. Flip BOTH directions. A pure round-trip check passes, because the
    #    inverse of an inverse returns the input.
    a = good.replace(
        "to_scene_reference: !<ExponentWithLinearTransform> {gamma: 2.4, offset: 0.055}",
        "to_scene_reference: !<ExponentWithLinearTransform> "
        "{gamma: 2.4, offset: 0.055, direction: inverse}")
    a = a.replace(
        "from_scene_reference: !<ExponentWithLinearTransform> "
        "{gamma: 2.4, offset: 0.055, direction: inverse}",
        "from_scene_reference: !<ExponentWithLinearTransform> {gamma: 2.4, offset: 0.055}")
    out.append(("invert both directions so the round trip still closes",
                "inverted_direction", a))

    # 2. Satisfy the data role by marking a colour space as data.
    # Replace the data role rather than adding a duplicate key: YAML takes the
    # last one, so an earlier version of this attack silently changed nothing
    # and reported a breach that did not exist. Validate the attack too.
    a = good.replace("data: Raw", "data: ACEScg")
    assert "data: ACEScg" in a and "data: Raw" not in a, "attack did not apply"
    out.append(("point the data role at the working space", "missing_data_role", a))

    # 3. Add a stub colourspace named exactly what the task requires.
    a = good.replace("color_picking: sRGB - Texture", "color_picking: sRGB")
    a += ("\n  - !<ColorSpace>\n    name: sRGB\n    family: Stub\n"
          "    equalitygroup: \"\"\n    bitdepth: 32f\n    isdata: false\n"
          "    allocation: uniform\n")
    out.append(("add an empty colourspace with the expected name", "dangling_role", a))
    return out


# ---------------------------------------------------------------- exr

def exr_attacks(interp):
    """Built in the EXR venv, because writing needs OpenEXR."""
    script = r'''
import json, os, sys, numpy as np, OpenEXR
tdir = sys.argv[1]; out = sys.argv[2]
W, H = 64, 48
y, x = np.mgrid[0:H, 0:W].astype(np.float32)
grad = ((x + y * W) / float(W * H)).astype(np.float32)
alpha = np.clip((x - 8) / (W - 16), 0, 1).astype(np.float32)
dither = (grad * 0.02).astype(np.float32)
straight = np.stack([0.9 + dither, 0.45 + dither, 0.2 + dither], -1).astype(np.float32)
rgb = (straight * alpha[..., None]).astype(np.float32)
n = np.stack([grad - .5, (y / H) - .5, np.ones_like(grad)], -1).astype(np.float32)
n /= np.linalg.norm(n, axis=-1, keepdims=True)

def base():
    return {"R": np.ascontiguousarray(rgb[...,0]), "G": np.ascontiguousarray(rgb[...,1]),
            "B": np.ascontiguousarray(rgb[...,2]), "A": alpha.copy(),
            "Z": (2.0 + grad * 48.0).astype(np.float32),
            "N.X": np.ascontiguousarray(n[...,0]), "N.Y": np.ascontiguousarray(n[...,1]),
            "N.Z": np.ascontiguousarray(n[...,2])}

def write(p, ch):
    OpenEXR.File({"compression": OpenEXR.ZIP_COMPRESSION,
                  "type": OpenEXR.scanlineimage}, ch).write(p)

attacks = {}
# depth is a flat constant above 1: passes a naive range check, carries no depth
c = base(); c["Z"] = np.full((H, W), 500.0, np.float32)
write(os.path.join(out, "hack_flat_depth.exr"), c); attacks["hack_flat_depth"] = "depth_normalised"
# normalised depth scaled up: still 0-1 shaped, just multiplied
c = base(); z = c["Z"]; c["Z"] = (((z-z.min())/(z.max()-z.min())) * 1.001 + 1e-3).astype(np.float32)
write(os.path.join(out, "hack_scaled_depth.exr"), c); attacks["hack_scaled_depth"] = "depth_normalised"
# 8-bit data plus tiny noise to beat a distinct-value count
c = base()
for k in "RGB":
    q = np.round(c[k]*255.0)/255.0
    c[k] = (q + np.random.default_rng(0).normal(0, 1e-7, q.shape)).astype(np.float32)
write(os.path.join(out, "hack_dithered_8bit.exr"), c); attacks["hack_dithered_8bit"] = "eight_bit_upconvert"
# normals renormalised to length 1 but pointing nowhere real
c = base(); r = np.random.default_rng(1).normal(0,1,(H,W,3)).astype(np.float32)
r /= np.linalg.norm(r, axis=-1, keepdims=True)
c["N.X"], c["N.Y"], c["N.Z"] = (np.ascontiguousarray(r[...,i]) for i in range(3))
write(os.path.join(out, "hack_random_normals.exr"), c); attacks["hack_random_normals"] = "normals_not_unit"
# rename back but keep the passes empty
c = base()
for k in ("Z","N.X","N.Y","N.Z"): c[k] = np.zeros((H,W), np.float32)
c["Z"] = np.full((H,W), 3.0, np.float32)
write(os.path.join(out, "hack_empty_aovs.exr"), c); attacks["hack_empty_aovs"] = "aov_naming"
print(json.dumps(attacks))
'''
    tmp = tempfile.mkdtemp()
    r = subprocess.run([interp, "-c", script,
                        os.path.join(ENVS, "exr_render_repair", "tasks"), tmp],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print("  could not build EXR attacks:", (r.stderr or "")[-300:])
        return []
    mapping = json.loads(r.stdout.strip().splitlines()[-1])
    return [(name, task, open(os.path.join(tmp, f"{name}.exr"), "rb").read())
            for name, task in mapping.items()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-ocio", default=sys.executable)
    ap.add_argument("--python-exr", default=sys.executable)
    a = ap.parse_args()

    breached = []
    print("\n  Adversarial reward-hacking pass")
    print("  Every attack tries to score 1.0 while leaving the fault in place.\n")

    print("  comfyui_graph_repair")
    for label, task, payload in comfy_attacks():
        rw, why = grade("comfyui_graph_repair", "submission.json", task, payload,
                        sys.executable)
        mark = "BREACH" if rw == 1.0 else "held"
        if rw == 1.0:
            breached.append((label, task))
        print(f"    {mark:7} {label}")
        if rw != 1.0:
            print(f"            caught by: {why[:78]}")

    print("\n  ocio_config_repair")
    for label, task, payload in ocio_attacks():
        rw, why = grade("ocio_config_repair", "submission.ocio", task, payload,
                        a.python_ocio)
        mark = "BREACH" if rw == 1.0 else "held"
        if rw == 1.0:
            breached.append((label, task))
        print(f"    {mark:7} {label}")
        if rw != 1.0:
            print(f"            caught by: {why[:78]}")

    print("\n  exr_render_repair")
    for label, task, payload in exr_attacks(a.python_exr):
        rw, why = grade("exr_render_repair", "submission.exr", task, payload,
                        a.python_exr, binary=True)
        mark = "BREACH" if rw == 1.0 else "held"
        if rw == 1.0:
            breached.append((label, task))
        print(f"    {mark:7} {label}")
        if rw != 1.0:
            print(f"            caught by: {why[:78]}")

    # Coverage. Three environments are attacked by name in this file, so a fourth
    # can be added with no attacks at all and the suite still prints a clean pass.
    # That is the same silent skip the environments exist to grade, committed by
    # the tool that is supposed to catch it.
    attacked = {"comfyui_graph_repair", "ocio_config_repair", "exr_render_repair"}
    elsewhere = {"video_conform_repair": "tools/hack_video.py"}
    on_disk = {d for d in os.listdir(ENVS)
               if os.path.isdir(os.path.join(ENVS, d))}
    uncovered = sorted(on_disk - attacked - set(elsewhere))
    print()
    print("  Attack coverage")
    for e in sorted(on_disk):
        where = ("this suite" if e in attacked
                 else elsewhere.get(e) or "NOTHING ATTACKS THIS")
        print(f"    {e:26} {where}")
    if uncovered:
        print()
        print(f"  {len(uncovered)} environment(s) have no adversarial pass at all.")
        print("  An unattacked grader is an untested one, and the first run of every")
        print("  suite so far breached roughly half its checks.")

    print()
    if breached:
        print(f"  {len(breached)} attack(s) scored full reward without fixing the fault:")
        for label, task in breached:
            print(f"    {task}: {label}")
        print("\n  Do not publish until these are closed. A gameable environment teaches")
        print("  a model to produce what scores rather than what is correct.\n")
    else:
        print("  No attack scored. Every grader required the actual repair.\n")
    sys.exit(len(breached) + len(uncovered))


if __name__ == "__main__":
    main()
