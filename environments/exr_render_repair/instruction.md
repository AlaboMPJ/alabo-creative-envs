# Repair the EXR render handoff

You are given a multi-channel OpenEXR file that a render handed to a comp. It
opens. It reads. It renders. It delivers. It is wrong.

Nothing in this task will raise an error, and that is the point. The EXR handoff
is the widest silent-wrongness surface in a pipeline: the file passes every
technical check a QC vendor runs, and the shot is still broken in a way only a
compositor notices, usually three days later.

Read `task_instance.json` for the symptom, which is what an artist said, and is
a description of what they saw rather than of the cause. Read `broken.exr`.

Write the repaired file to `submission.exr`.

## What you are given

`task_instance.json` holds the symptom and the requirements for this instance.
The keys that appear are:

- `symptom` — what the artist reported. Treat it as a lead, not a diagnosis.
- `require_channels` — channel names that must be present by the end.
- `require_scene_depth` and `depth_range` — depth must be in scene units, and
  the camera near and far for the shot are given.
- `require_unpremultiplied` — alpha must not be baked into colour twice.
- `require_unit_normals` — normals must be unit length.
- `min_levels` — the colour channels must carry genuine float information.
- `may_change` — the only channels you are permitted to alter.

## What the grader checks

Every check is arithmetic over the pixels, not a read of the header. The header
will tell you the file is a 32-bit float EXR whether or not it carries any float
information.

Channels are looked up by their standard names, because a conform template finds
passes by name and a rename breaks it with no error.

Depth is checked in scene units against the stated camera range. A 0-1 depth is
the most common silent fault in any handoff out of a DCC or a generative tool,
and it puts every defocus, fog and atmospheric node at the wrong distance.
Rescaling a normalised depth so it exceeds 1.0 does not restore the distances
and will not pass.

Alpha is checked by un-premultiplying and seeing whether the recovered colour
still tracks alpha. EXR alpha is associated. If the render was multiplied a
second time, every edge goes dark over any background and nothing anywhere
errors.

Normals are checked for unit length. Renormalising random values will clear the
length test and fail the correlation test below, because that is replacement
rather than repair.

Bit depth is checked two ways: the count of distinct values, and whether those
values sit on the 8-bit lattice at multiples of 1/255. Adding small noise raises
the count without restoring any information.

## The rule that matters most

Every channel outside `may_change` is compared against a known-good reference and
must match. Every channel inside `may_change` must still correlate with the
original.

So you cannot pass by flattening depth to a constant, zeroing a pass, writing
fresh normals, or dithering an 8-bit image. Satisfying the rules while destroying
the data is not a repair, and it is graded as a failure rather than as a clever
answer.

## Reward

Binary. 1.0 if every check passes, 0.0 otherwise, with the specific reason
either way. There is no partial credit, because a handoff is either correct for
the department downstream or it is not.
