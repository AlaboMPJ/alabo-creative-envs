#!/usr/bin/env python3
"""Grader for exr_render_repair.

The EXR is where a render hands off to a comp, and it is the widest silent-
wrongness surface in the pipeline. Nothing here raises an error. The file opens,
the comp renders, the shot delivers, and the defocus is at the wrong distance or
the edges are dark or the float file is an 8-bit upconvert.

Every check below is a statement about craft expressed as arithmetic. That is
the whole product: an ML engineer can write the container, and cannot write
these.

Binary reward, with a reason either way.
"""
import json, sys, argparse
import numpy as np

try:
    import OpenEXR
except ImportError:
    print(json.dumps({"reward": 0.0, "reason": "environment error: OpenEXR missing"}),
          file=sys.stderr)
    sys.exit(2)


def fail(reason):
    print(json.dumps({"reward": 0.0, "reason": reason}))
    sys.exit(0)


def ok(reason):
    print(json.dumps({"reward": 1.0, "reason": reason}))
    sys.exit(0)


def read(path):
    try:
        with OpenEXR.File(path) as f:
            part = f.parts[0]
            # part.channels is a dict attribute, not a method. Probed against
            # OpenEXR 3.4.13; assuming it was callable cost the fourth API
            # mistake of the day.
            chans = part.channels
            if callable(chans):
                chans = chans()
            # OpenEXR groups R,G,B,A into one "RGBA" array on read. Splitting
            # it back out is mandatory: without it every per-channel check finds
            # no channel named R and silently SKIPS, which is worse than failing.
            out = {}
            for name, c in chans.items():
                px = np.asarray(c.pixels if hasattr(c, "pixels") else c,
                                dtype=np.float32)
                if px.ndim == 3 and len(name) == px.shape[-1] and name.isalpha():
                    for i, letter in enumerate(name):
                        out[letter] = np.ascontiguousarray(px[..., i])
                else:
                    out[name] = px
            return out
    except FileNotFoundError:
        fail(f"no submission at {path}")
    except Exception as e:
        fail(f"not a readable EXR: {str(e)[:180]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default="/env/submission.exr")
    ap.add_argument("--task", default="/env/task_instance.json")
    a = ap.parse_args()

    spec = json.load(open(a.task))
    ch = read(a.submission)

    # 1. required channels, by their standard names. A conform template looks
    #    these up by name, so a rename is a break even though nothing errors.
    for want in spec.get("require_channels", []):
        if want not in ch:
            fail(f"channel '{want}' is missing. Present: {sorted(ch)[:10]}. "
                 "Standard AOV names exist so a conform can find them.")

    # 2. depth must be in scene units, not normalised. A 0-1 depth is the single
    #    most common silent fault in an AI or DCC handoff, and every defocus and
    #    atmospheric node downstream is then wrong.
    if spec.get("require_scene_depth"):
        z = ch.get("Z")
        if z is None:
            fail("no Z channel, so depth cannot be checked")
        zmax, zmin = float(z.max()), float(z.min())
        if zmax <= 1.0 + 1e-6:
            fail(f"depth range is {zmin:.3f} to {zmax:.3f}, which is normalised. "
                 "Z must be in scene units; a 0-1 depth silently breaks defocus and fog.")
        if zmin < 0:
            fail(f"depth minimum is {zmin:.3f}; distance cannot be negative")

    # 3. alpha must not be baked into colour twice. Double premultiplication
    #    darkens every edge and there is no error to read.
    if spec.get("require_unpremultiplied"):
        a_ch, r = ch.get("A"), ch.get("R")
        if a_ch is None or r is None:
            fail("need A and R to test premultiplication")
        edge = (a_ch > 0.05) & (a_ch < 0.95)
        if edge.sum() > 16:
            # EXR RGBA is associated alpha, so dividing by alpha should recover a
            # flat straight colour. If the recovered colour still tracks alpha,
            # the render was multiplied a second time and every edge will go
            # dark over any background, with no error anywhere.
            straight = r[edge] / np.maximum(a_ch[edge], 1e-4)
            spread = float(straight.max() - straight.min())
            corr = float(np.corrcoef(straight, a_ch[edge])[0, 1])
            if corr > 0.9 and spread > 0.1:
                fail(f"un-premultiplying leaves colour still tracking alpha "
                     f"(correlation {corr:.2f}, spread {spread:.2f}), so the render "
                     "is premultiplied twice. Edges go dark over any background.")

    # 4. normals must be unit length, or relighting is subtly wrong everywhere.
    if spec.get("require_unit_normals"):
        try:
            n = np.stack([ch["N.X"], ch["N.Y"], ch["N.Z"]], -1)
        except KeyError:
            fail("normals must be N.X, N.Y, N.Z")
        length = np.linalg.norm(n, axis=-1)
        m = float(np.median(length))
        if abs(m - 1.0) > 0.02:
            fail(f"normals have median length {m:.3f}, not 1.0. "
                 "Non-unit normals break relighting without erroring.")

    # 5. a float file that carries no more information than an 8-bit image.
    #    Counting distinct values is the only reliable test; the header will
    #    happily say 32-bit float either way.
    floor = spec.get("min_levels")
    if floor:
        missing = [c for c in "RGB" if c not in ch]
        if missing:
            fail(f"cannot test bit depth: colour channels {missing} not found. "
                 f"Present: {sorted(ch)[:10]}")
        for c in "RGB":
            levels = len(np.unique(ch[c]))
            if levels < floor:
                fail(f"channel {c} holds only {levels} distinct values. "
                     "This is a float file carrying 8-bit information, which "
                     "banks in gradients and cannot be graded.")

    ok(f"{len(ch)} channels; all craft checks passed")


if __name__ == "__main__":
    main()
