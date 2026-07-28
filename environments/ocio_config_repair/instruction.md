# Repair the OCIO config

You are given an OpenColorIO config that is wrong.

It probably loads. Colour faults rarely announce themselves: the config parses,
the comp renders, the shot delivers, and the colour is wrong. Read
`symptom.txt` for what the artist noticed, which is a description of the
symptom and not of the cause.

Write the repaired config to `submission.ocio`.

## What the grader checks

- every role points at a colorspace that exists
- the roles a pipeline looks up are present: scene_linear, color_picking, data, default
- exactly one reference colorspace, meaning exactly one space declaring no transform
- no space marked `isdata` carries a colour transform
- the `data` role points at a space actually marked `isdata`
- the colorspaces and roles this task requires
- where the task declares round trips, a value encoded into a space and decoded
  back returns the input, and encoding is not a no-op

## What you must not do

Do not write a minimal config that satisfies the checks. The repair must
preserve the pipeline: same working space, same texture and display spaces,
same role targets. A rebuilt config will fail the task requirements.

## Scoring

Binary, with a reason either way.
