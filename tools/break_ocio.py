#!/usr/bin/env python3
"""Generate ocio_config_repair task instances from a known-good config.

Every fault here is one I have seen ship. None of them raise an error. The
config loads, the comp renders, the shot goes out, and the colour is wrong.
That is the point: this environment grades the class of failure that has no
error message.

    python3 tools/break_ocio.py --out environments/ocio_config_repair/tasks
"""
import os, copy, json, argparse

try:
    import yaml
except ImportError:
    raise SystemExit("pip install pyyaml")

GOOD = {
    "ocio_profile_version": 2,
    "search_path": "luts",
    "roles": {
        "default": "ACEScg",
        "reference": "ACEScg",
        "scene_linear": "ACEScg",
        "color_picking": "sRGB - Texture",
        "data": "Raw",
        "matte_paint": "sRGB - Texture",
        "texture_paint": "sRGB - Texture",
    },
    "displays": {
        "sRGB": [{"!<View>": None, "name": "Standard", "colorspace": "sRGB - Display"}],
    },
    "active_displays": ["sRGB"],
    "active_views": ["Standard"],
    "colorspaces": [
        {"name": "ACEScg", "family": "ACES", "bitdepth": "32f",
         "description": "The working space. Reference: no transform.",
         "isdata": False, "allocation": "lg2", "allocationvars": [-8, 5, 0.00390625]},
        {"name": "Raw", "family": "Utility", "bitdepth": "32f",
         "description": "Data. Never colour managed.",
         "isdata": True, "allocation": "uniform"},
        {"name": "sRGB - Texture", "family": "Texture", "bitdepth": "32f",
         "isdata": False, "allocation": "uniform",
         "to_reference": {"!<ExponentWithLinearTransform>": None,
                          "gamma": [2.4, 2.4, 2.4, 1.0],
                          "offset": [0.055, 0.055, 0.055, 0.0],
                          "direction": "inverse"}},
        {"name": "sRGB - Display", "family": "Display", "bitdepth": "32f",
         "isdata": False, "allocation": "uniform",
         "from_reference": {"!<ExponentWithLinearTransform>": None,
                            "gamma": [2.4, 2.4, 2.4, 1.0],
                            "offset": [0.055, 0.055, 0.055, 0.0],
                            "direction": "forward"}},
    ],
}


def missing_data_role(c):
    """The data role is dropped. Everything renders; depth and matte channels
    get colour managed and are quietly destroyed."""
    del c["roles"]["data"]
    return c, "The comp renders. Depth passes look wrong after a colourspace conversion."


def data_space_transformed(c):
    """Raw keeps isdata but gains a transform. OCIO will not complain."""
    for cs in c["colorspaces"]:
        if cs["name"] == "Raw":
            cs["to_reference"] = {"!<ExponentTransform>": None, "value": [2.2, 2.2, 2.2, 1.0]}
    return c, "No error. Normals and mattes come back subtly shifted."


def inverted_direction(c):
    """The classic. Direction flipped on the texture transform, so textures
    are double-gamma'd. Config validates and loads."""
    for cs in c["colorspaces"]:
        if cs["name"] == "sRGB - Texture":
            cs["to_reference"]["direction"] = "forward"
    return c, "No error. Textures read washed out and nobody can say why."


def ambiguous_reference(c):
    """A second space declares no transform, so the reference is ambiguous."""
    c["colorspaces"].append({"name": "Linear Rec.709", "family": "Utility",
                             "bitdepth": "32f", "isdata": False,
                             "allocation": "lg2"})
    return c, "No error. Conversions resolve inconsistently between applications."


def dangling_role(c):
    """A role points at a colourspace that was renamed."""
    c["roles"]["color_picking"] = "sRGB"
    return c, "Colour picking fails in the DCC with an unhelpful message."


BREAKS = {
    "missing_data_role": (missing_data_role, {
        "required_roles": {"data": "Raw", "scene_linear": "ACEScg"},
        "required_colorspaces": ["ACEScg", "Raw", "sRGB - Texture"]}),
    "data_space_transformed": (data_space_transformed, {
        "required_roles": {"data": "Raw"},
        "required_colorspaces": ["Raw"]}),
    "inverted_direction": (inverted_direction, {
        "required_colorspaces": ["sRGB - Texture", "ACEScg"],
        "round_trips": [{"colorspace": "sRGB - Texture",
                         "value": [0.18, 0.18, 0.18], "tolerance": 1e-4}]}),
    "ambiguous_reference": (ambiguous_reference, {
        "required_roles": {"scene_linear": "ACEScg"},
        "required_colorspaces": ["ACEScg"]}),
    "dangling_role": (dangling_role, {
        "required_roles": {"color_picking": "sRGB - Texture"},
        "required_colorspaces": ["sRGB - Texture"]}),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="environments/ocio_config_repair/tasks")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    with open(os.path.join(a.out, "_reference_good.ocio"), "w") as f:
        yaml.safe_dump(GOOD, f, sort_keys=False)

    for name, (fn, spec) in BREAKS.items():
        broken, symptom = fn(copy.deepcopy(GOOD))
        with open(os.path.join(a.out, f"{name}.ocio"), "w") as f:
            yaml.safe_dump(broken, f, sort_keys=False)
        inst = {"id": name, "application": "OpenColorIO",
                "broken_config": f"{name}.ocio", "symptom": symptom}
        inst.update(spec)
        with open(os.path.join(a.out, f"{name}.json"), "w") as f:
            json.dump(inst, f, indent=2)
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
