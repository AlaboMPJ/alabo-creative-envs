#!/usr/bin/env python3
"""Fixture generator for video_conform_repair.

Every fault here was met on real hardware on 2026-07-29, driving a DJI Osmo
Pocket 3 into a headless capture tool, and every one of them produced a file
that played perfectly and was wrong:

  head_ramp             the camera's auto-exposure settle shipped in the cut
  vertical_into_landscape   a portrait source squashed onto a landscape canvas
  transition_drift      xfade offsets measured against the raw timeline

Fixtures are synthetic on purpose. They stay small, they are byte-deterministic
so a grader can assert against them, and they carry no likeness, so the repo can
be public without anyone appearing in a test file.

    python3 tools/break_video.py
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TASKS = os.path.join(ROOT, "environments", "video_conform_repair", "tasks")

FPS = 30
# Small on purpose. These are graded on geometry and timing, and a 4K fixture
# would prove nothing a 640-wide one does not while bloating the repo.
LAND = (640, 360)
PORT = (360, 640)


def run(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr.strip()[:2000], file=sys.stderr)
        raise SystemExit(f"ffmpeg failed: {' '.join(args[:8])}...")


def enc(extra=None):
    # yuv420p and a fixed GOP so every frame is decodable and every grader gets
    # the same pixels. crf 18 because the graders measure geometry off these:
    # a fixture that is soft enough to argue with is a fixture that fails
    # correct submissions.
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-g", str(FPS)] + (extra or [])


def circle_src(w, h, seconds, radius, extra=None):
    """A white disc on grey at exactly w x h, optionally conformed further.

    The disc is the instrument. A disc stays a disc under any correct conform and
    turns into an ellipse under every wrong one, so roundness IS the craft check,
    expressed as arithmetic the grader can run.

    Extra filters are APPENDED to the chain rather than passed as a second -vf.
    ffmpeg keeps only the last -vf, so handing back a ready-made flag and adding
    another silently discarded the disc and produced a flat grey reference that
    failed its own grader. Composition here, not at the call site.
    """
    geq = (f"geq=lum='if(lte(hypot(X-{w}/2,Y-{h}/2),{radius}),235,60)'"
           f":cb=128:cr=128")
    chain = geq + ("," + extra if extra else "")
    # Nothing else in frame may be as bright as the disc: the grader finds it by
    # threshold, and any other white mark would land in the same mask and quietly
    # corrupt every measurement taken from it.
    return ["-f", "lavfi", "-i",
            f"color=c=gray:s={w}x{h}:r={FPS}:d={seconds}", "-vf", chain]


def make_head_ramp():
    """Six seconds of pattern whose first 0.8s fades up from black.

    That is exactly what a UVC camera hands you while auto-exposure and white
    balance settle. Nothing errors. The clip is simply unusable at the head, and
    it reaches the timeline that way.
    """
    out = os.path.join(TASKS, "head_ramp.mp4")
    ref = os.path.join(TASKS, "head_ramp_reference.mp4")
    w, h = LAND
    src = ["-f", "lavfi", "-i", f"testsrc2=size={w}x{h}:rate={FPS}:duration=6"]
    run(src + ["-vf", "fade=t=in:st=0:d=0.8"] + enc() + [out])
    # The reference is what a correct trim produces: the same pattern, starting
    # at 0.8s, running the required 5.0s. Generated from the same source so a
    # correct submission matches it frame for frame.
    run(src + ["-vf", "trim=start=0.8:duration=5,setpts=PTS-STARTPTS"] + enc() + [ref])
    return {
        "id": "head_ramp",
        "application": "FFmpeg",
        "broken_file": "head_ramp.mp4",
        "reference": "head_ramp_reference.mp4",
        "symptom": ("The head of the clip fades up from black over about a second. "
                    "It plays, it has the right frame size, nothing errors. The "
                    "camera's auto-exposure was still settling when recording started."),
        "deliver": {"seconds": 5.0, "fps": FPS, "width": w, "height": h},
        "rules": ["Do not brighten the clip. The exposure of the good picture is correct.",
                  "The delivered clip must be 5.00s, so trimming the head means the "
                  "material is there to trim from."],
    }


def make_vertical():
    """A portrait source that has to reach a landscape canvas.

    The Osmo offers 1080x1920 and 720x1280 vertical modes. Conform one to a
    landscape timeline with a plain scale and the subject is squashed, the file
    is valid, the duration is right, and every automated check passes.
    """
    out = os.path.join(TASKS, "vertical_into_landscape.mp4")
    ref = os.path.join(TASKS, "vertical_into_landscape_reference.mp4")
    pw, ph = PORT
    lw, lh = LAND
    radius = 120
    run(circle_src(pw, ph, 4, radius) + enc() + [out])
    # Correct conform: fit inside the canvas with aspect intact, then pillarbox.
    # Fit height, so the disc keeps its diameter ratio and black fills the sides.
    run(circle_src(pw, ph, 4, radius,
                   extra=(f"scale={lw}:{lh}:force_original_aspect_ratio=decrease,"
                          f"pad={lw}:{lh}:(ow-iw)/2:(oh-ih)/2:black,setsar=1"))
        + enc() + [ref])
    return {
        "id": "vertical_into_landscape",
        "application": "FFmpeg",
        "broken_file": "vertical_into_landscape.mp4",
        "reference": "vertical_into_landscape_reference.mp4",
        "symptom": ("A portrait capture has to go on a landscape timeline. The "
                    "source is 360x640 and the delivery is 640x360."),
        "deliver": {"seconds": 4.0, "fps": FPS, "width": lw, "height": lh},
        "rules": ["Nothing may be cropped. The whole source frame must remain visible.",
                  "Geometry must be preserved. Round things stay round.",
                  "Fill any unused canvas with black."],
    }


def make_transition_drift():
    """Three clips, two dissolves, offsets measured against the wrong clock.

    xfade EATS its overlap, so the chain gets shorter with every transition. Sum
    the raw durations instead and the second offset lands exactly at the end of
    the chain built so far, which makes xfade truncate: the THIRD CLIP NEVER
    APPEARS. ffmpeg returns 0, the file is valid, it plays, and a whole scene is
    gone. Measured rather than assumed: the broken assembly is 5.20s and still
    green at 5.00s, where the correct one is 7.40s and already dissolving to blue.
    """
    seg_secs, tdur = 3.0, 0.8
    colours = ["0x802828", "0x287028", "0x283878"]
    segs = []
    for i, c in enumerate(colours):
        p = os.path.join(TASKS, f"drift_seg{i}.mp4")
        w, h = LAND
        run(["-f", "lavfi", "-i", f"color=c={c}:s={w}x{h}:r={FPS}:d={seg_secs}",
             "-vf", f"drawbox=x='40+60*t':y=140:w=70:h=70:color=white:t=fill"]
            + enc() + [p])
        segs.append(p)

    def chain(offsets):
        f = ""
        for i in range(3):
            f += f"[{i}:v]setpts=PTS-STARTPTS,format=yuv420p[v{i}];"
        f += (f"[v0][v1]xfade=transition=fade:duration={tdur}:offset={offsets[0]}[x1];"
              f"[x1][v2]xfade=transition=fade:duration={tdur}:offset={offsets[1]}[out]")
        return f

    ins = []
    for p in segs:
        ins += ["-i", p]

    # WRONG: second offset measured against 3+3, ignoring the 0.8 the first
    # dissolve already consumed.
    bad = os.path.join(TASKS, "transition_drift.mp4")
    run(ins + ["-filter_complex", chain([seg_secs - tdur, seg_secs * 2 - tdur]),
               "-map", "[out]"] + enc() + [bad])

    # RIGHT: each offset measured against the chain built so far.
    acc = seg_secs
    o1 = acc - tdur
    acc = acc + seg_secs - tdur
    o2 = acc - tdur
    ref = os.path.join(TASKS, "transition_drift_reference.mp4")
    run(ins + ["-filter_complex", chain([o1, o2]), "-map", "[out]"] + enc() + [ref])

    total = seg_secs * 3 - tdur * 2
    return {
        "id": "transition_drift",
        "application": "FFmpeg",
        "broken_file": "transition_drift.mp4",
        "reference": "transition_drift_reference.mp4",
        "segments": [f"drift_seg{i}.mp4" for i in range(3)],
        "symptom": ("Three 3.00s clips were joined by two 0.80s dissolves. The "
                    "assembly plays without error and ffmpeg reported success, but "
                    "the third clip is nowhere in it and the file ends early."),
        "deliver": {"seconds": round(total, 3), "fps": FPS,
                    "width": LAND[0], "height": LAND[1]},
        "transitions": [{"at": round(o1 + tdur / 2, 3), "between": [0, 1]},
                        {"at": round(o2 + tdur / 2, 3), "between": [1, 2]}],
        "segment_duration": seg_secs,
        "transition_duration": tdur,
        "rules": ["Rebuild the assembly from the three segments provided.",
                  "Both dissolves must be real cross-fades, not cuts.",
                  "Trimming the existing file to the right length is not a repair."],
    }


def main():
    os.makedirs(TASKS, exist_ok=True)
    for build in (make_head_ramp, make_vertical, make_transition_drift):
        meta = build()
        with open(os.path.join(TASKS, meta["id"] + ".json"), "w") as f:
            json.dump(meta, f, indent=2)
        print("wrote", meta["id"])


if __name__ == "__main__":
    main()
