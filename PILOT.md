# Pilot brief

For a training provider, post house or studio who wants to try the environments
on real people before deciding anything.

Free. The terms are at the bottom and they are short.

## What this is

Containerised assessments for professional creative software. Each one gives a
person a broken artifact, asks them to repair it, and grades the result in code
with no human in the loop. Currently three: a ComfyUI workflow, an OpenColorIO
config, and an OpenEXR render handoff.

They test the class of fault that has no error message. A colour config that
loads, renders, delivers and is wrong. A depth pass normalised to 0-1 so every
defocus sits at the wrong distance. Output that runs and is incorrect is the
hardest thing to catch in an interview and the easiest thing to catch in code.

## What you get

An assessment you can run on a cohort or a candidate shortlist, in about thirty
seconds per person.

A report per person, per task, with the exact reason for every failure. Not a
score. The reason, so your tutor or hiring lead can check whether the machine
was right rather than take its word.

A failure rate per task across the group, which is usually the more useful
number: it tells you which idea the cohort does not hold.

Set-up help from me, and a call at the end to go through what it found.

## What you do

Nominate one module or one shortlist. Colour management is the best first
choice because the faults are unambiguous.

Collect submissions as files, one per person, named after them.

Run one command:

    python3 tools/assess.py --env ocio_config_repair --submissions ./cohort --csv report.csv

Spend twenty minutes afterwards telling me what it caught, what it missed, and
what it got wrong. That last one is the most valuable and I would rather have it
than a compliment.

## What I ask in return

Permission to describe what happened, in the terms below.

That is the whole fee. I am buying a case study and you are getting the
assessment free, and I would rather say that plainly than dress it up.

## Terms

Short, and written so a lawyer does not need to be involved.

1. No fee, in either direction. This is a pilot.

2. Your material stays yours. Submissions, student work, candidate work and
   anything else you send remain your property and your responsibility. I do not
   keep it, do not use it to train anything, and do not put it into any corpus,
   model or dataset of mine. It is deleted when the pilot ends.

3. I never see identifiable work unless you choose to send it. The assessment
   runs on your machine. If you would rather I never touch a submission at all,
   that is the default and it works fine.

4. Right to reference. I may describe, in writing and in conversation, that your
   organisation ran the assessment, on what module or shortlist, at what scale,
   and what it found in aggregate. I may quote you if you approve the quote in
   writing first.

5. Named or unnamed, your choice. If you prefer, I will describe you generically,
   for example "a London VFX school" or "a post house in Soho", and everything in
   clause 4 still applies. Tell me at the end rather than the beginning; you will
   know better then.

6. No individual is ever identified. No student, candidate or employee is named,
   described identifiably, or quoted. Results are reported in aggregate.

7. Withdraw any time. If you change your mind about being named, tell me and I
   will remove the reference from anything I control within seven days. This
   survives the pilot indefinitely.

8. No warranty. These are new assessments and they may be wrong. Do not use them
   as the only basis for a decision about a person during the pilot. If the
   grader marks someone down, check it. That is the point of the pilot.

9. The tools stay mine. The environments and graders are open source under the
   repository's licence. You keep every result they produce.

10. Either of us can stop at any point, for any reason, with no consequence.

## Who to contact

Alabo. github.com/AlaboMPJ/alabo-creative-envs
