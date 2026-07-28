#!/usr/bin/env python3
"""Generate exr_render_repair task instances.

An EXR is where a render hands off to a comp, and every fault here passes
through that handoff without an error. The file opens, the comp renders, the
shot delivers, and something is quietly wrong. Each break below is one I have
hit in a real pipeline.

Built with the real OpenEXR library so the files are valid by construction,
which is the lesson from the OCIO environment: a hand-rolled artifact that only
satisfies your own schema proves nothing.

    pip install openexr numpy
    python3 tools/break_exr.py --out environments/exr_render_repair/tasks
"""
import os, json, argparse
import numpy as np

try:
    import OpenEXR
except ImportError:
    raise SystemExit("needs OpenEXR: pip install openexr")

W, H = 64, 48


def _base_channels():
    """A small, correct multi-AOV render: colour, alpha, depth, normals."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    # 2D so every pixel is distinct: a 1D gradient across 64 columns yields only
    # 64 levels and would fail its own bit-depth check, which is a fixture bug
    # rather than a grader bug and worth not shipping.
    grad = ((x + y * W) / float(W * H)).astype(np.float32)

    # Linear scene-referred colour, values sensibly above and below 0.18.
    alpha = np.clip((x - 8) / (W - 16), 0, 1).astype(np.float32)

    # Flat unpremultiplied colour under the alpha ramp, plus a fine 2D dither so
    # the file carries genuine float precision. EXR RGBA is associated alpha by
    # convention, so the reference is premultiplied ONCE and the fault is a
    # second multiply. With flat straight colour the signature is unambiguous:
    # correct gives R/A constant, double-premultiplied gives R/A tracking A.
    dither = (grad * 0.02).astype(np.float32)
    straight = np.stack([0.9 + dither, 0.45 + dither, 0.2 + dither], -1).astype(np.float32)
    rgb = (straight * alpha[..., None]).astype(np.float32)

    # Depth in SCENE UNITS, not 0-1. This is the distinction that gets lost.
    depth = (2.0 + grad * 48.0).astype(np.float32)

    # Unit normals, so a length check is meaningful.
    n = np.stack([grad - 0.5, (y / H) - 0.5, np.ones_like(grad)], -1).astype(np.float32)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)

    return {
        "R": np.ascontiguousarray(rgb[..., 0]),
        "G": np.ascontiguousarray(rgb[..., 1]),
        "B": np.ascontiguousarray(rgb[..., 2]),
        "A": alpha,
        "Z": depth,
        "N.X": np.ascontiguousarray(n[..., 0]),
        "N.Y": np.ascontiguousarray(n[..., 1]),
        "N.Z": np.ascontiguousarray(n[..., 2]),
    }


def write(path, channels, header_extra=None):
    header = {"compression": OpenEXR.ZIP_COMPRESSION,
              "type": OpenEXR.scanlineimage}
    if header_extra:
        header.update(header_extra)
    f = OpenEXR.File(header, channels)
    f.write(path)


# ---- the faults. none of these raise an error anywhere downstream ----

def depth_normalised(ch):
    """Depth rescaled to 0-1. The file looks fine, every defocus and fog node
    downstream is wrong, and there is no error to read."""
    z = ch["Z"]
    ch["Z"] = ((z - z.min()) / (z.max() - z.min())).astype(np.float32)
    return ch, ("Defocus looks flat. Fog sits at the wrong distance. No error "
                "anywhere. Camera near and far for this shot were 2.0 and 50.0.")


def alpha_double_premult(ch):
    """Colour premultiplied twice. Edges go dark against any background."""
    for c in "RGB":
        ch[c] = (ch[c] * ch["A"]).astype(np.float32)
    return ch, "Edges look dark and crunchy over the background. Nothing errors."


def normals_not_unit(ch):
    """Normals scaled, so relighting and normal-driven effects are subtly off."""
    for c in ("N.X", "N.Y", "N.Z"):
        ch[c] = (ch[c] * 0.6).astype(np.float32)
    return ch, "Relight looks wrong in a way nobody can name. Nothing errors."


def eight_bit_upconvert(ch):
    """A float file carrying no more information than an 8-bit PNG. This is the
    one ala-exr was written to catch, because a compositor spots it instantly
    and a pipeline never will."""
    for c in "RGB":
        ch[c] = (np.round(ch[c] * 255.0) / 255.0).astype(np.float32)
    return ch, "It is a 32-bit float EXR and it banks in the gradient."


def aov_naming(ch):
    """AOVs renamed so a conform cannot find them. Standard names exist for a
    reason and no error is raised when they are not used."""
    ch["depth_pass"] = ch.pop("Z")
    ch["normal_x"] = ch.pop("N.X")
    ch["normal_y"] = ch.pop("N.Y")
    ch["normal_z"] = ch.pop("N.Z")
    return ch, "The comp template cannot find the passes and an artist rewires by hand."


# `may_change` names the channels a correct repair is allowed to touch. Every
# other channel must come back byte-for-byte, which is what stops an agent
# satisfying the rule by replacing the data.
REF = "_reference_good.exr"
BREAKS = {
    # The camera range is stated so the repair is actually recoverable.
    # Normalising destroys the original distances, so without this the task
    # would be unsolvable and the grader would only be rewarding guesses.
    "depth_normalised":     (depth_normalised, {"require_scene_depth": True,
                                                "depth_range": [2.0, 50.0],
                                                "reference": REF, "may_change": ["Z"]}),
    "alpha_double_premult": (alpha_double_premult, {"require_unpremultiplied": True,
                                                    "reference": REF,
                                                    "may_change": ["R", "G", "B"]}),
    "normals_not_unit":     (normals_not_unit, {"require_unit_normals": True,
                                                "reference": REF,
                                                "may_change": ["N.X", "N.Y", "N.Z"]}),
    "eight_bit_upconvert":  (eight_bit_upconvert, {"min_levels": 512, "reference": REF,
                                                   "may_change": ["R", "G", "B"]}),
    "aov_naming":           (aov_naming, {"require_channels": ["Z", "N.X", "N.Y", "N.Z", "R", "G", "B", "A"],
                                          "reference": REF, "may_change": []}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="environments/exr_render_repair/tasks")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    write(os.path.join(a.out, "_reference_good.exr"), _base_channels())
    print("wrote reference render")

    for name, (fn, spec) in BREAKS.items():
        ch, symptom = fn(_base_channels())
        write(os.path.join(a.out, f"{name}.exr"), ch)
        inst = {"id": name, "application": "OpenEXR", "broken_file": f"{name}.exr",
                "symptom": symptom}
        inst.update(spec)
        with open(os.path.join(a.out, f"{name}.json"), "w") as f:
            json.dump(inst, f, indent=2)
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
