#!/usr/bin/env python3
"""Generate ocio_config_repair task instances.

The good config is BUILT WITH PyOpenColorIO rather than hand-written, so it is
valid by construction. An earlier version of this file emitted hand-rolled YAML
that parsed fine and that OCIO rejected outright, which is the same class of
mistake this environment exists to catch. Building with the real library is the
fix, and it is why generating tasks needs OCIO installed even though grading
does not.

Every fault below is one I have seen ship. Four of the five raise no error.

    pip install opencolorio pyyaml
    python3 tools/break_ocio.py --out environments/ocio_config_repair/tasks
"""
import os, json, argparse, re

try:
    import PyOpenColorIO as OCIO
except ImportError:
    raise SystemExit("needs PyOpenColorIO: pip install opencolorio")


def build_good():
    """A small, real, ACEScg-working-space config."""
    cfg = OCIO.Config()
    cfg.setVersion(2, 0)
    cfg.setSearchPath("luts")

    acescg = OCIO.ColorSpace(name="ACEScg", family="ACES", bitDepth=OCIO.BIT_DEPTH_F32)
    acescg.setDescription("Working space. Reference: declares no transform.")
    acescg.setAllocation(OCIO.ALLOCATION_LG2)
    acescg.setAllocationVars([-8.0, 5.0, 0.00390625])
    cfg.addColorSpace(acescg)

    raw = OCIO.ColorSpace(name="Raw", family="Utility", bitDepth=OCIO.BIT_DEPTH_F32)
    raw.setDescription("Data. Never colour managed.")
    raw.setIsData(True)
    cfg.addColorSpace(raw)

    # Directions verified numerically against the sRGB spec: with FORWARD on
    # to_scene_reference, linear 0.18 encodes to 0.4614 against a spec value of
    # 0.4613. INVERSE gives 0.0272, which is the classic fault this environment
    # exists to catch, and which an earlier version of this file shipped.
    srgb_tex = OCIO.ColorSpace(name="sRGB - Texture", family="Texture",
                               bitDepth=OCIO.BIT_DEPTH_F32)
    tex_t = OCIO.ExponentWithLinearTransform(
        gamma=[2.4, 2.4, 2.4, 1.0], offset=[0.055, 0.055, 0.055, 0.0],
        negativeStyle=OCIO.NEGATIVE_LINEAR, direction=OCIO.TRANSFORM_DIR_FORWARD)
    srgb_tex.setTransform(tex_t, OCIO.COLORSPACE_DIR_TO_REFERENCE)
    cfg.addColorSpace(srgb_tex)

    srgb_disp = OCIO.ColorSpace(name="sRGB - Display", family="Display",
                                bitDepth=OCIO.BIT_DEPTH_F32)
    disp_t = OCIO.ExponentWithLinearTransform(
        gamma=[2.4, 2.4, 2.4, 1.0], offset=[0.055, 0.055, 0.055, 0.0],
        negativeStyle=OCIO.NEGATIVE_LINEAR, direction=OCIO.TRANSFORM_DIR_INVERSE)
    srgb_disp.setTransform(disp_t, OCIO.COLORSPACE_DIR_FROM_REFERENCE)
    cfg.addColorSpace(srgb_disp)

    for role, space in [("default", "ACEScg"), ("reference", "ACEScg"),
                        ("scene_linear", "ACEScg"), ("color_picking", "sRGB - Texture"),
                        ("data", "Raw"), ("matte_paint", "sRGB - Texture"),
                        ("texture_paint", "sRGB - Texture")]:
        cfg.setRole(role, space)

    cfg.addDisplayView("sRGB", "Standard", "sRGB - Display", "")
    cfg.setActiveDisplays("sRGB")
    cfg.setActiveViews("Standard")
    cfg.validate()
    return cfg.serialize()


# Breaks operate on the serialised text, because several of these faults are
# things the API would refuse to construct, which is precisely why they are
# interesting: they arrive by hand-editing a config, which is how they arrive
# in real life.

def missing_data_role(t):
    return re.sub(r"^\s*data:\s*Raw\n", "", t, flags=re.M), \
        "The comp renders. Depth passes look wrong after a colourspace conversion."


def data_space_transformed(t):
    return t.replace(
        "    isdata: true\n    allocation: uniform",
        "    isdata: true\n    allocation: uniform\n"
        "    to_scene_reference: !<ExponentTransform> {value: 2.2}"), \
        "No error. Normals and mattes come back subtly shifted."


def inverted_direction(t):
    """Flip the texture transform direction. Config stays valid and loadable."""
    return t.replace(
        "to_scene_reference: !<ExponentWithLinearTransform> "
        "{gamma: 2.4, offset: 0.055}",
        "to_scene_reference: !<ExponentWithLinearTransform> "
        "{gamma: 2.4, offset: 0.055, direction: inverse}"), \
        "No error. Textures read washed out and nobody can say why."


def ambiguous_reference(t):
    return t + (
        "\n  - !<ColorSpace>\n    name: Linear Rec.709\n    family: Utility\n"
        "    equalitygroup: \"\"\n    bitdepth: 32f\n    isdata: false\n"
        "    allocation: lg2\n"), \
        "No error. Conversions resolve inconsistently between applications."


def dangling_role(t):
    return t.replace("color_picking: sRGB - Texture", "color_picking: sRGB"), \
        "Colour picking fails in the DCC with an unhelpful message."


BREAKS = {
    "dangling_role": (dangling_role, {
        "required_roles": {"color_picking": "sRGB - Texture"},
        "required_colorspaces": ["sRGB - Texture"]}),
    "missing_data_role": (missing_data_role, {
        "required_roles": {"data": "Raw", "scene_linear": "ACEScg"},
        "required_colorspaces": ["ACEScg", "Raw", "sRGB - Texture"]}),
    "data_space_transformed": (data_space_transformed, {
        "required_roles": {"data": "Raw"},
        "required_colorspaces": ["Raw"]}),
    "ambiguous_reference": (ambiguous_reference, {
        "required_roles": {"scene_linear": "ACEScg"},
        "required_colorspaces": ["ACEScg"]}),
    "inverted_direction": (inverted_direction, {
        "required_colorspaces": ["sRGB - Texture", "ACEScg"],
        "round_trips": [{"colorspace": "sRGB - Texture",
                         "value": [0.18, 0.18, 0.18],
                         "expect_encoded": [0.4614, 0.4614, 0.4614],
                         "tolerance": 1e-3}]}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="environments/ocio_config_repair/tasks")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    good = build_good()
    with open(os.path.join(a.out, "_reference_good.ocio"), "w") as f:
        f.write(good)
    print("built reference config with PyOpenColorIO, validated")

    for name, (fn, spec) in BREAKS.items():
        broken, symptom = fn(good)
        if broken == good:
            raise SystemExit(f"break '{name}' changed nothing; the text pattern has drifted")
        with open(os.path.join(a.out, f"{name}.ocio"), "w") as f:
            f.write(broken)
        inst = {"id": name, "application": "OpenColorIO",
                "broken_config": f"{name}.ocio", "symptom": symptom}
        inst.update(spec)
        with open(os.path.join(a.out, f"{name}.json"), "w") as f:
            json.dump(inst, f, indent=2)
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
