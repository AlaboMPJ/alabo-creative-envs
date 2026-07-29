# exr_render_repair

Repair a render handoff that opens cleanly and is wrong.

Depth normalised to 0-1 so every defocus sits at the wrong distance. Alpha premultiplied twice so every edge darkens. A 32-bit float file carrying eight bits of information. Nothing errors.

Every fault here is in one class: the artifact runs, raises nothing, delivers,
and is wrong. Faults that throw are already caught by the software and are not
worth grading.

## Reward

Binary, 1.0 or 0.0, with a specific reason either way. No partial credit: a
handoff is either correct for the department downstream or it is not, and
rewarding "nearly right" teaches the wrong thing efficiently.

Shape checks alone are gameable, so every channel or field the repair was not
meant to touch is compared against a known-good reference and must match, and
everything it was allowed to touch must still correlate with the original.
Satisfying the rules while destroying the data is graded as a failure. On the
first adversarial pass across these environments, seven of twelve attacks
scored full reward without fixing anything; those holes are closed and the
attacks are kept in `tools/reward_hack.py` upstream.

## Source

https://github.com/AlaboMPJ/alabo-creative-envs
