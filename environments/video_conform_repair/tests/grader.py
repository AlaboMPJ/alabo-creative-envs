#!/usr/bin/env python3
"""Grader for video_conform_repair.

Video is the widest silent-wrongness surface after the EXR handoff, because a
video file has no schema to violate. Drop a scene, squash a face, mistime a
dissolve, ship the auto-exposure ramp: the container stays valid, the player
stays happy, ffmpeg returns 0, and every automated check that only asks "did it
encode" passes. The fault surfaces on a timeline, in front of a client.

So nothing here asks whether the file is valid. Every check is a statement about
craft expressed as arithmetic:

  a disc stays a disc                    geometry survived the conform
  black at the edges                     the frame was fitted, not cropped
  a blend at the transition midpoint     the dissolve is real, not a trim
  luma at frame zero                     the exposure ramp is gone
  luma over the body unchanged           and it was TRIMMED, not brightened

The last pair matters most. Every check has a partner that fails the lazy way of
satisfying it, because a grader that only passes correct answers is half a
grader: it also has to fail the cheap rewrite that scores without doing the work.

Binary reward, with a reason either way.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

TOL_FRAMES = 1.5          # timing slack, in frames
DISC_ASPECT_TOL = 0.08    # a disc measured off a compressed frame is not exact
DISC_LUM = 200            # the disc is 235 on a 60 ground, so this is unambiguous


def emit(reward, reason):
    print(json.dumps({"reward": reward, "reason": reason}))
    sys.exit(0)


def fail(reason):
    emit(0.0, reason)


def ok(reason):
    emit(1.0, reason)


def envfail(reason):
    print(json.dumps({"reward": 0.0, "reason": f"environment error: {reason}"}),
          file=sys.stderr)
    sys.exit(2)


def probe(path):
    """Width, height, duration and frame rate, from the file's own record."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,avg_frame_rate,nb_read_packets", "-count_packets",
         "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        d = json.loads(r.stdout)
        s = d["streams"][0]
        num, den = s.get("avg_frame_rate", "0/1").split("/")
        fps = float(num) / float(den) if float(den) else 0.0
        return {"w": int(s["width"]), "h": int(s["height"]), "fps": fps,
                "packets": int(s.get("nb_read_packets", 0)),
                "duration": float(d["format"]["duration"])}
    except Exception:
        return None


def frame_at(path, t, w, h):
    """One decoded RGB frame at time t.

    Output seeking (-ss AFTER -i) decodes and discards rather than jumping to the
    nearest keyframe. It is slower and it is the only way to be sure the frame
    returned is the frame asked for, which matters when the whole check is
    "what is on screen at 5.00 seconds".
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ss", f"{t:.4f}", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True)
    need = w * h * 3
    if len(r.stdout) < need:
        return None
    return np.frombuffer(r.stdout[:need], dtype=np.uint8).reshape(h, w, 3).astype(np.float32)


def disc_bbox(img):
    """Bounding box of the bright disc, or None if it is not there."""
    lum = img.mean(axis=2)
    mask = lum >= DISC_LUM
    if int(mask.sum()) < 200:
        return None
    ys, xs = np.where(mask)
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


def check_delivery(sub, spec):
    """Frame size, duration and rate. Necessary, and nowhere near sufficient."""
    if sub["w"] != spec["width"] or sub["h"] != spec["height"]:
        fail(f"delivered {sub['w']}x{sub['h']}, spec is {spec['width']}x{spec['height']}")
    fps = float(spec["fps"])
    if abs(sub["fps"] - fps) > 0.5:
        fail(f"delivered {sub['fps']:.2f} fps, spec is {fps:.0f}")
    want = float(spec["seconds"])
    slack = TOL_FRAMES / fps
    if abs(sub["duration"] - want) > slack:
        fail(f"delivered {sub['duration']:.3f}s, spec is {want:.3f}s "
             f"(tolerance {slack:.3f}s)")


def grade_head_ramp(path, ref, spec, task):
    w, h, fps = spec["width"], spec["height"], float(spec["fps"])

    f0 = frame_at(path, 0.0, w, h)
    r0 = frame_at(ref, 0.0, w, h)
    if f0 is None or r0 is None:
        fail("could not decode the first frame")

    # The ramp itself. A submission still carrying the settle is dark at zero.
    sub_l, ref_l = float(f0.mean()), float(r0.mean())
    if sub_l < ref_l * 0.75:
        fail(f"first frame is still in the exposure ramp: mean luma {sub_l:.1f} "
             f"against {ref_l:.1f} for a correctly trimmed head")

    # ...and its partner. Brightening the clip also raises frame zero, so the
    # body has to be UNCHANGED or the fix was a grade rather than a trim.
    subs, refs = [], []
    for t in (1.0, 2.5, 4.0):
        a, b = frame_at(path, t, w, h), frame_at(ref, t, w, h)
        if a is None or b is None:
            fail(f"could not decode {t:.1f}s from both files")
        subs.append(a)
        refs.append(b)
    body_sub = float(np.mean([x.mean() for x in subs]))
    body_ref = float(np.mean([x.mean() for x in refs]))
    if abs(body_sub - body_ref) > 6.0:
        fail(f"the picture itself was altered: body mean luma {body_sub:.1f} "
             f"against {body_ref:.1f}. The exposure of the good frames was correct; "
             f"this needed a trim, not a grade")

    # And the content has to be the right content, from the right place in the
    # source, or "trim somewhere and brighten to taste" would satisfy the pair
    # above.
    diffs = [float(np.abs(a - b).mean()) for a, b in zip(subs, refs)]
    if max(diffs) > 12.0:
        fail(f"the frames do not match the source at those times "
             f"(mean abs difference up to {max(diffs):.1f}); the trim is at the "
             f"wrong point or the material was replaced")
    ok(f"head trimmed at the right point, exposure untouched, {spec['seconds']}s delivered")


def grade_vertical(path, ref, spec, task):
    w, h = spec["width"], spec["height"]
    f = frame_at(path, 1.0, w, h)
    r = frame_at(ref, 1.0, w, h)
    if f is None or r is None:
        fail("could not decode a frame at 1.0s")

    bb = disc_bbox(f)
    if bb is None:
        fail("the disc is not in the delivered frame at all")
    x0, x1, y0, y1 = bb
    dw, dh = x1 - x0 + 1, y1 - y0 + 1
    aspect = dw / float(dh)
    if abs(aspect - 1.0) > DISC_ASPECT_TOL:
        fail(f"geometry was not preserved: the disc measures {dw}x{dh}, aspect "
             f"{aspect:.2f}. A portrait source scaled straight onto a landscape "
             f"canvas squashes everything in it")

    # A disc can also be round because the frame was cropped to fill, which
    # silently throws away the sides of the shot. Fitted material leaves black.
    edge = np.concatenate([f[:, :4, :].ravel(), f[:, -4:, :].ravel()])
    if float(edge.mean()) > 24.0:
        fail(f"no black at the left and right edges (mean {edge.mean():.1f}): the "
             f"frame was filled by cropping rather than fitted, so the sides of "
             f"the source are gone")

    # And it has to be the whole source, at the size fitting produces, rather
    # than a small disc floating in a lot of black.
    rbb = disc_bbox(r)
    if rbb is None:
        envfail("reference has no disc")
    rdh = rbb[3] - rbb[2] + 1
    if abs(dh - rdh) > max(6, rdh * 0.08):
        fail(f"the disc is {dh}px tall where fitting the whole source gives {rdh}px: "
             f"the frame was scaled to the wrong size")
    ok(f"fitted to {w}x{h} with geometry intact and the full source visible")


def grade_transition_drift(path, ref, spec, task):
    w, h = spec["width"], spec["height"]
    seg_d = float(task["segment_duration"])
    tdur = float(task["transition_duration"])

    # Every segment has to be PRESENT. The fault being repaired is a clip that
    # vanished, so its absence is the first thing to look for. Sample the middle
    # of each clip in the corrected timeline.
    starts = []
    acc = 0.0
    for i in range(3):
        starts.append(acc)
        acc += seg_d - (tdur if i < 2 else 0)
    seg_colours = []
    for i, s in enumerate(starts):
        t = s + seg_d / 2.0 if i == 0 else s + (seg_d - tdur) / 2.0 + tdur
        t = min(t, float(spec["seconds"]) - 0.15)
        f = frame_at(path, t, w, h)
        g = frame_at(ref, t, w, h)
        if f is None:
            fail(f"nothing at {t:.2f}s: clip {i + 1} is missing from the assembly")
        if g is None:
            envfail(f"reference has nothing at {t:.2f}s")
        d = float(np.abs(f.mean(axis=(0, 1)) - g.mean(axis=(0, 1))).mean())
        if d > 14.0:
            fail(f"at {t:.2f}s the picture does not match clip {i + 1} "
                 f"(colour differs by {d:.1f}); the clips are in the wrong order, "
                 f"mistimed, or one of them is missing")
        seg_colours.append(g.mean(axis=(0, 1)))

    # And the dissolves have to be REAL. A submission trimmed or padded to the
    # right duration passes every timing check and has hard cuts where the
    # dissolves belong, so the midpoint of each transition must be a genuine
    # blend: unlike BOTH neighbours, and close to their average.
    for k, tr in enumerate(task["transitions"]):
        t = float(tr["at"])
        f = frame_at(path, t, w, h)
        if f is None:
            fail(f"nothing at {t:.2f}s, where transition {k + 1} belongs")
        c = f.mean(axis=(0, 1))
        a, b = seg_colours[tr["between"][0]], seg_colours[tr["between"][1]]
        da, db = float(np.abs(c - a).mean()), float(np.abs(c - b).mean())
        mid = float(np.abs(c - (a + b) / 2.0).mean())
        if min(da, db) < 8.0:
            fail(f"transition {k + 1} at {t:.2f}s is a cut, not a dissolve: the "
                 f"midpoint frame is still one of the two clips "
                 f"(difference {min(da, db):.1f})")
        if mid > 12.0:
            fail(f"transition {k + 1} at {t:.2f}s is mistimed: the midpoint frame "
                 f"is {mid:.1f} away from a half-and-half blend of the two clips")
    ok(f"all three clips present, both dissolves real and on time, "
       f"{spec['seconds']}s delivered")


GRADERS = {
    "head_ramp": grade_head_ramp,
    "vertical_into_landscape": grade_vertical,
    "transition_drift": grade_transition_drift,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--env-dir", default=None)
    a = ap.parse_args()

    if subprocess.run(["which", "ffprobe"], capture_output=True).returncode != 0:
        envfail("ffprobe not on PATH")
    try:
        with open(a.task) as f:
            task = json.load(f)
    except Exception as e:
        envfail(f"cannot read task: {e}")

    env_dir = a.env_dir or os.path.dirname(os.path.dirname(os.path.abspath(a.task)))
    ref = os.path.join(env_dir, "tasks", task["reference"])
    if not os.path.exists(ref):
        ref = os.path.join(os.path.dirname(os.path.abspath(a.task)), task["reference"])
    if not os.path.exists(ref):
        envfail(f"reference missing: {task['reference']}")

    if not os.path.exists(a.submission):
        fail(f"no submission at {a.submission}")
    sub = probe(a.submission)
    if sub is None:
        fail("the submission is not a readable video file")
    if sub["packets"] < 2:
        fail("the submission has fewer than two frames")

    check_delivery(sub, task["deliver"])

    g = GRADERS.get(task["id"])
    if g is None:
        envfail(f"no grader for task {task['id']}")
    g(a.submission, ref, task["deliver"], task)


if __name__ == "__main__":
    main()
