# Repair the conform

A clip has come back from capture and it is wrong. It plays. It opens in any
player. ffmpeg returned success when it was made. The fault is in the picture,
not the file, and it will not surface until the shot is on a timeline in front
of someone paying for it.

Read `task_instance.json`. It names the broken file, describes the symptom the
way an editor would report it, states the delivery spec, and lists any rules
that apply to this task.

Write your repair to `submission.mp4`.

## What you are given

- `task_instance.json` — the symptom, the delivery spec, the rules
- the broken file named in it
- for some tasks, the original source segments the assembly was built from

## The delivery spec

`deliver` states `width`, `height`, `fps` and `seconds`. All four are checked.
Duration is checked to within about a frame and a half. Getting the spec right
is necessary and it is nowhere near sufficient: every broken file here already
plays, and one of them already has a perfectly plausible duration.

## How this is graded

Every check is a measurement of the picture, and every one of them has a partner
that catches the cheap way of satisfying it.

- Geometry is measured off a disc in frame. A disc stays a disc under a correct
  conform and becomes an ellipse under every wrong one.
- Fitting is distinguished from cropping by looking for black at the edges. A
  frame filled by cropping has lost the sides of the shot.
- Exposure is measured at the head AND over the body. Lifting frame zero without
  removing the ramp changes the body, and that is checked.
- A dissolve is verified by sampling its midpoint. A hard cut there is not a
  dissolve, whatever the file duration says.
- Content is compared against the correct answer at several times, so a
  submission cannot satisfy the numbers by replacing the material with something
  that measures well.

Reward is 1.0 or 0.0, with a reason either way.

## What will not work

Trimming or padding to reach the required duration. Brightening a clip instead
of removing the bad frames. Scaling to the target size without regard for what
that does to the shape of things. Cropping to fill so the numbers come out
round. Each of these has been tried against this grader and each of them scores
zero, with the reason stated.

Do the repair.
