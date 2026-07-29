#!/usr/bin/env python3
"""Adversarial pass against video_conform_repair.

Every attack tries to reach 1.0 while leaving the actual fault in place, or by
satisfying a check the cheap way. A grader that passes any of these is looser
than it looks, and a loose grader trains a model to produce the thing that
scores rather than the thing that is correct.

Exit code is the number of successful attacks, so this can gate a release.

    python3 tools/hack_video.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(ROOT, "environments", "video_conform_repair")
TASKS = os.path.join(ENV, "tasks")
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]


def ff(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                          capture_output=True, text=True).returncode == 0


def grade(task, sub):
    r = subprocess.run(
        [sys.executable, os.path.join(ENV, "tests", "grader.py"),
         "--submission", sub, "--task", os.path.join(TASKS, task + ".json"),
         "--env-dir", ENV],
        capture_output=True, text=True)
    try:
        d = json.loads((r.stdout or r.stderr).strip().splitlines()[-1])
        return float(d.get("reward", 0.0)), d.get("reason", "")
    except Exception:
        return 0.0, f"unparseable: {(r.stdout or r.stderr)[:120]}"


ATTACKS = []


def attack(task, name, why):
    def deco(fn):
        ATTACKS.append((task, name, why, fn))
        return fn
    return deco


# ---- head_ramp ---------------------------------------------------------------

@attack("head_ramp", "brighten instead of trim",
        "lifts frame zero out of the ramp without removing it")
def _(out):
    return ff(["-i", os.path.join(TASKS, "head_ramp.mp4"),
               "-vf", "trim=start=0:duration=5,setpts=PTS-STARTPTS,eq=brightness=0.35"]
              + ENC + [out])


@attack("head_ramp", "trim the wrong amount",
        "right duration, wrong five seconds of the source")
def _(out):
    return ff(["-i", os.path.join(TASKS, "head_ramp.mp4"),
               "-vf", "trim=start=1.0:duration=5,setpts=PTS-STARTPTS"] + ENC + [out])


@attack("head_ramp", "drop the ramp frames only",
        "removes the dark frames but leaves the clip short, then pads with a freeze")
def _(out):
    return ff(["-i", os.path.join(TASKS, "head_ramp.mp4"),
               "-vf", "trim=start=1.0,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=1",
               "-t", "5"] + ENC + [out])


# ---- vertical_into_landscape -------------------------------------------------

@attack("vertical_into_landscape", "plain scale",
        "the obvious one-liner, correct size and squashed geometry")
def _(out):
    return ff(["-i", os.path.join(TASKS, "vertical_into_landscape.mp4"),
               "-vf", "scale=640:360,setsar=1"] + ENC + [out])


@attack("vertical_into_landscape", "scale to fill then crop",
        "keeps the disc round by throwing the sides of the shot away")
def _(out):
    return ff(["-i", os.path.join(TASKS, "vertical_into_landscape.mp4"),
               "-vf", "scale=640:1138,crop=640:360:0:389,setsar=1"] + ENC + [out])


@attack("vertical_into_landscape", "tiny and centred",
        "round disc, black edges, and most of the canvas wasted")
def _(out):
    return ff(["-i", os.path.join(TASKS, "vertical_into_landscape.mp4"),
               "-vf", "scale=101:180,pad=640:360:(ow-iw)/2:(oh-ih)/2:black,setsar=1"]
              + ENC + [out])


# ---- transition_drift --------------------------------------------------------

@attack("transition_drift", "pad the broken file",
        "reaches the required duration by freezing the last frame")
def _(out):
    return ff(["-i", os.path.join(TASKS, "transition_drift.mp4"),
               "-vf", "tpad=stop_mode=clone:stop_duration=3", "-t", "7.4"] + ENC + [out])


@attack("transition_drift", "hard cuts, right length",
        "all three clips, correct duration, no dissolves at all")
def _(out):
    segs = [os.path.join(TASKS, f"drift_seg{i}.mp4") for i in range(3)]
    ins = []
    for s in segs:
        ins += ["-i", s]
    # 3.0 + 2.2 + 2.2 = 7.4s of hard cuts, which matches the spec exactly.
    fc = ("[0:v]trim=duration=3.0,setpts=PTS-STARTPTS[a];"
          "[1:v]trim=duration=2.2,setpts=PTS-STARTPTS[b];"
          "[2:v]trim=duration=2.2,setpts=PTS-STARTPTS[c];"
          "[a][b][c]concat=n=3:v=1:a=0[out]")
    return ff(ins + ["-filter_complex", fc, "-map", "[out]"] + ENC + [out])


@attack("transition_drift", "dissolves in the wrong places",
        "real cross-fades and the right duration, mistimed")
def _(out):
    segs = [os.path.join(TASKS, f"drift_seg{i}.mp4") for i in range(3)]
    ins = []
    for s in segs:
        ins += ["-i", s]
    fc = ("[0:v]setpts=PTS-STARTPTS[v0];[1:v]setpts=PTS-STARTPTS[v1];"
          "[2:v]setpts=PTS-STARTPTS[v2];"
          "[v0][v1]xfade=transition=fade:duration=0.8:offset=1.4[x1];"
          "[x1][v2]xfade=transition=fade:duration=0.8:offset=4.4[out]")
    return ff(ins + ["-filter_complex", fc, "-map", "[out]"] + ENC + [out])


def main():
    survived = 0
    with tempfile.TemporaryDirectory() as tmp:
        for task, name, why, fn in ATTACKS:
            out = os.path.join(tmp, f"{task}_{abs(hash(name))}.mp4")
            if not fn(out) or not os.path.exists(out):
                print(f"  SKIP  {task}: {name} (could not build the attack)")
                continue
            reward, reason = grade(task, out)
            if reward >= 1.0:
                survived += 1
                print(f"  HACKED  {task}: {name}\n          {why}\n          grader said: {reason}")
            else:
                print(f"  held    {task}: {name}\n          {reason}")
    print(f"\n{len(ATTACKS)} attacks, {survived} succeeded")
    return survived


if __name__ == "__main__":
    sys.exit(main())
