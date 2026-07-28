#!/usr/bin/env python3
"""Generate task instances by breaking a known-good graph deterministically.

Every task therefore has a known-good solution and the break is reproducible
from its name, which is what lets the grader assert requirements rather than
guess. Authored from a working graph; nothing scraped.

    python3 tools/break_graph.py --out environments/comfyui_graph_repair/tasks
"""
import json, os, copy, argparse

# A minimal, real SDXL text-to-image graph in ComfyUI API format.
GOOD = {
    "4": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": "RealVisXL_V4.0.safetensors"}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "a portrait, studio light, 85mm", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "blurry, low quality", "clip": ["4", 1]}},
    "3": {"class_type": "KSampler",
          "inputs": {"seed": 42, "steps": 30, "cfg": 5.5,
                     "sampler_name": "dpmpp_2m", "scheduler": "karras",
                     "denoise": 1.0,
                     "model": ["4", 0], "positive": ["6", 0],
                     "negative": ["7", 0], "latent_image": ["5", 0]}},
    "8": {"class_type": "VAEDecode",
          "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage",
          "inputs": {"filename_prefix": "repair", "images": ["8", 0]}},
}


def sdxl_dangling_latent(g):
    """The commonest real fault: a link left pointing at a node that was deleted."""
    g["3"]["inputs"]["latent_image"] = ["99", 0]
    return g, "Error occurred when executing KSampler: required input is missing: latent_image"


def missing_vae_decode(g):
    """A sampler emits LATENT; SaveImage needs IMAGE. Removing the decode makes
    the graph structurally connected but type-nonsense, which is the fault that
    catches people who pattern-match on connectivity alone."""
    del g["8"]
    g["9"]["inputs"]["images"] = ["3", 0]
    return g, "Error occurred when executing SaveImage: expected IMAGE, got LATENT"


def feedback_cycle(g):
    """Produces no error at all, only a hang. The agent has to reason about the
    executor rather than read the message."""
    g["5"]["inputs"]["latent_from"] = ["3", 0]
    return g, "(no error; the queue accepted the prompt and never completed)"


def orphaned_conditioning(g):
    """Both conditioning inputs wired to the positive encoder. The graph runs
    happily and the output is quietly wrong, which is the hardest class of fault
    to grade and the one an artist spots instantly."""
    g["3"]["inputs"]["negative"] = ["6", 0]
    g["7"]["inputs"]["text"] = "blurry, low quality"
    return g, "(no error; the graph executes but the negative prompt has no effect)"


BREAKS = {
    "sdxl_dangling_latent": (sdxl_dangling_latent, {
        "required_class_types": ["KSampler", "VAEDecode", "SaveImage", "EmptyLatentImage"],
        "required_input_values": [["5", "width", 832], ["5", "height", 1216],
                                  ["3", "steps", 30], ["3", "seed", 42]]}),
    "missing_vae_decode": (missing_vae_decode, {
        "required_class_types": ["VAEDecode", "SaveImage"],
        "required_input_values": [["3", "steps", 30]]}),
    "feedback_cycle": (feedback_cycle, {
        "required_class_types": ["KSampler", "VAEDecode", "SaveImage"],
        "required_input_values": [["5", "width", 832]]}),
    "orphaned_conditioning": (orphaned_conditioning, {
        "required_class_types": ["CLIPTextEncode", "KSampler"],
        # the fix is to point negative back at node 7, so assert the wiring
        "required_input_values": [["3", "negative", ["7", 0]],
                                  ["3", "positive", ["6", 0]]]}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="environments/comfyui_graph_repair/tasks")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for name, (fn, spec) in BREAKS.items():
        broken, err = fn(copy.deepcopy(GOOD))
        inst = {
            "id": name,
            "application": "ComfyUI",
            "broken_graph": broken,
            "error": err,
            "required_class_types": spec["required_class_types"],
            "required_input_values": spec["required_input_values"],
        }
        p = os.path.join(a.out, f"{name}.json")
        with open(p, "w") as f:
            json.dump(inst, f, indent=2)
        print(f"wrote {p}")
    with open(os.path.join(a.out, "_reference_good.json"), "w") as f:
        json.dump(GOOD, f, indent=2)
    print("wrote reference solution")


if __name__ == "__main__":
    main()
