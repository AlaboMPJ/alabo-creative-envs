#!/usr/bin/env python3
"""Build a review page so a human can judge the graders instead of trusting them.

A CSV of ones and zeros is not a basis for deciding whether an environment is fit
to distribute. This runs every task in both directions and shows the evidence.

Both directions is the point. A grader that fails everything scores the same on a
broken file as a good one, and a grader that passes everything looks identical on
a spreadsheet. So each task is graded twice:

    the BROKEN file      must score 0.0, and the reason must name the real fault
    the REFERENCE file   must score 1.0, or the grader is simply hostile

A task only earns "sound" when both hold. Anything else is flagged, in red, at the
top, before you read another word.

    .venv-vf/bin/python tools/review.py --out review.html

Design rule taken from the environments themselves: never show a picture without
the number beside it. A normalised depth pass and a scene-unit depth pass look
identical once either is stretched for display, so the image alone would hide the
exact fault the task exists to teach. The range is printed under every thumbnail.
"""
import argparse, base64, collections, difflib, io, json, os, subprocess, sys, tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVS = os.path.join(ROOT, "environments")
EXT = {"comfyui_graph_repair": ".json",
       "ocio_config_repair": ".ocio",
       "exr_render_repair": ".exr",
       "video_conform_repair": ".mp4"}

# Plain English for the page. An identifier like depth_normalised tells a
# compositor nothing and tells a hiring lead less. These belong in the task specs
# eventually; they live here until the specs carry a title field.
AREAS = {"comfyui_graph_repair": "ComfyUI workflows",
         "ocio_config_repair": "Colour management",
         "exr_render_repair": "Render handoff",
         "video_conform_repair": "Video conform"}

# Five files make an environment distributable. Anything missing means it runs on
# this machine and nowhere else, which is how exr_render_repair sat in the README
# as finished while having no instruction, no manifest and no container.
REQUIRED = ["task.toml", "instruction.md", "environment/Dockerfile",
            "tests/test.sh", "tests/grader.py"]

# What is not here yet. A bench that only shows finished work looks complete and
# tells you nothing about the shape of the job. Keep this in step with the README.
PLANNED = [
    ("Nuke script repair", "Graded statically from the .nk text, with check frames "
                           "rendered locally so no licence has to travel."),
    ("Audio delivery", "Polarity inverted on one mic, sample-rate laundering, a "
                       "crossfade discontinuity, an over-limited master."),
    ("Resolve conform", "Reads the project through Resolve's Python API. Feasible, "
                        "unverified."),
]
TITLES = {
    "feedback_cycle": "A loop that hangs forever",
    "missing_vae_decode": "A workflow that saves nothing",
    "orphaned_conditioning": "The negative prompt wired to the positive",
    "sdxl_dangling_latent": "A link pointing at a node that is not there",
    "ambiguous_reference": "Two colourspaces both claiming to be the reference",
    "dangling_role": "A role pointing at a colourspace that does not exist",
    "data_space_transformed": "Depth and mattes being colour managed",
    "inverted_direction": "A colour transform running backwards",
    "missing_data_role": "No data role, so depth gets graded like colour",
    "aov_naming": "Passes renamed so the comp cannot find them",
    "eight_bit_upconvert": "A float file carrying only 8-bit information",
    "normals_not_unit": "Normals that are not unit length",
    "alpha_double_premult": "Alpha multiplied in twice",
    "depth_normalised": "Depth squashed to 0 and 1",
}


# ---------------------------------------------------------------- grading

def grade(env, task_json, submission):
    """Run the real grader as a subprocess, exactly as a runner would."""
    grader = os.path.join(ENVS, env, "tests", "grader.py")
    cmd = [sys.executable, grader, "--submission", submission, "--task", task_json]
    if env == "exr_render_repair":
        cmd += ["--env-dir", os.path.join(ENVS, env)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    for stream in (p.stdout, p.stderr):
        for line in stream.strip().splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    d = json.loads(line)
                    d["exit"] = p.returncode
                    return d
                except json.JSONDecodeError:
                    pass
    return {"reward": None, "reason": f"no JSON from grader (exit {p.returncode}): "
                                      f"{(p.stderr or p.stdout)[:200]}", "exit": p.returncode}


# ---------------------------------------------------------------- imaging

def png_uri(arr, mode="L"):
    from PIL import Image
    im = Image.fromarray(arr, mode)
    im.thumbnail((360, 360))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def read_exr(path):
    import OpenEXR
    with OpenEXR.File(path) as f:
        chans = f.parts[0].channels
        if callable(chans):
            chans = chans()
        out = {}
        for name, c in chans.items():
            px = np.asarray(c.pixels if hasattr(c, "pixels") else c, dtype=np.float32)
            if px.ndim == 3 and len(name) == px.shape[-1] and name.isalpha():
                for i, letter in enumerate(name):
                    out[letter] = np.ascontiguousarray(px[..., i])
            else:
                out[name] = px
        return out


def tone(rgb):
    """Display transform for a linear float image. Gamma only, no grade."""
    v = np.clip(rgb, 0, None) ** (1 / 2.2)
    return (np.clip(v, 0, 1) * 255).astype(np.uint8)


def exr_panels(ch):
    """Return [(label, data-uri, number-line)] for whatever this file carries."""
    out = []
    if all(c in ch for c in "RGB"):
        rgb = np.stack([ch["R"], ch["G"], ch["B"]], -1)
        levels = min(len(np.unique(ch[c])) for c in "RGB")
        out.append(("RGB", png_uri(tone(rgb), "RGB"),
                    f"min {rgb.min():.4f}  max {rgb.max():.4f}  "
                    f"distinct levels {levels}"))
    if "A" in ch:
        a = ch["A"]
        out.append(("Alpha", png_uri((np.clip(a, 0, 1) * 255).astype(np.uint8)),
                    f"min {a.min():.3f}  max {a.max():.3f}  "
                    f"edge pixels {int(((a > 0.05) & (a < 0.95)).sum())}"))
    if "Z" in ch:
        z = ch["Z"]
        # Stretched for display on purpose, with the true range printed beneath,
        # because a stretched normalised depth and a stretched scene depth are
        # the same picture. The number is the evidence, the image is orientation.
        span = max(float(z.max() - z.min()), 1e-9)
        out.append(("Depth (stretched)", png_uri(((z - z.min()) / span * 255).astype(np.uint8)),
                    f"Actual range {z.min():.3f} to {z.max():.3f}"))
    if all(c in ch for c in ("N.X", "N.Y", "N.Z")):
        n = np.stack([ch["N.X"], ch["N.Y"], ch["N.Z"]], -1)
        length = np.linalg.norm(n, axis=-1)
        out.append(("Normals", png_uri(((np.clip(n, -1, 1) * 0.5 + 0.5) * 255).astype(np.uint8), "RGB"),
                    f"median length {np.median(length):.4f}  (must be 1.0000)"))
    return out


# ---------------------------------------------------------------- text evidence

def text_diff(a_path, b_path, a_label, b_label):
    a = open(a_path, encoding="utf-8", errors="replace").read().splitlines()
    b = open(b_path, encoding="utf-8", errors="replace").read().splitlines()
    if a_path.endswith(".json"):
        a = json.dumps(json.load(open(a_path)), indent=2, sort_keys=True).splitlines()
        b = json.dumps(json.load(open(b_path)), indent=2, sort_keys=True).splitlines()
    return "\n".join(difflib.unified_diff(b, a, b_label, a_label, lineterm="", n=2)) \
        or "(identical)"


# ---------------------------------------------------------------- page

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


CSS = """
:root{--bg:#000;--fg:#ececec;--muted:#8a8a8a;--dim:#585858;--accent:#9aa1a8;
--bad:#b8695f;--good:#7d9c86;--line:rgba(255,255,255,.10);--soft:rgba(255,255,255,.05);
--sans:'Sohne',-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
--serif:'Canela','Iowan Old Style','Palatino Linotype',Georgia,serif;
--mono:'Sohne Mono',ui-monospace,'SF Mono',Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;
line-height:1.6;-webkit-font-smoothing:antialiased;hyphens:none}
.wrap{max-width:900px;margin:0 auto;padding:76px 36px 120px}

/* Header. The whole verdict in one number, before anything else. */
h1{font-family:var(--serif);font-weight:400;font-size:38px;margin:0 0 14px;letter-spacing:-.01em}
.score{font-family:var(--serif);font-size:56px;line-height:1;margin:0 0 8px}
.score .n{color:var(--good)}.score .n.bad{color:var(--bad)}
.score small{font-family:var(--sans);font-size:14px;letter-spacing:0;color:var(--muted);
display:block;margin-top:12px}
.sub{color:var(--muted);max-width:58ch;margin:26px 0 0;font-size:15px}
.rule{border:0;border-top:1px solid var(--line);margin:44px 0 0}

/* The board. One line per fault, in the words an artist would use. */
h2{font-family:var(--serif);font-size:26px;font-weight:400;color:var(--fg);
margin:60px 0 2px;letter-spacing:-.01em}
.count{font-family:var(--mono);font-size:11px;letter-spacing:.04em;color:var(--dim);
padding-bottom:12px;border-bottom:1px solid var(--soft);margin-bottom:2px}
.ready{font-size:13.5px;margin:14px 0 6px;display:flex;align-items:center;gap:9px}
.ready i{width:9px;height:9px;flex:0 0 9px;border-radius:50%;background:var(--bad)}
.ready.on i{background:var(--good)}
.ready.on{color:var(--muted)}.ready{color:var(--bad)}
.later{margin:64px 0 0;padding-top:26px;border-top:1px solid var(--line)}
.later h3{font-family:var(--serif);font-size:22px;font-weight:400;margin:0 0 6px}
.later p.i{color:var(--dim);font-size:14px;margin:0 0 26px;max-width:66ch}
.later .row{padding:16px 0;border-bottom:1px solid var(--soft)}
.later .row b{font-family:var(--serif);font-size:18px;font-weight:400;color:var(--muted);
display:block;margin-bottom:5px}
.later .row span{font-size:13.5px;color:var(--dim)}
details.task{border-bottom:1px solid var(--soft)}
details.task > summary{list-style:none;cursor:pointer;display:grid;
grid-template-columns:1fr 210px;gap:24px;align-items:center;padding:20px 2px;
transition:background .12s}
details.task > summary::-webkit-details-marker{display:none}
details.task > summary:hover{background:rgba(255,255,255,.025)}
details.task[open] > summary{background:rgba(255,255,255,.025)}
.tname{font-family:var(--serif);font-size:20px;color:var(--fg);line-height:1.35}
.tname .said{font-family:var(--sans);font-size:13.5px;color:var(--dim);display:block;
margin-top:6px;font-style:italic}
.status{display:flex;flex-direction:column;gap:7px;justify-self:end}
.st{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:9px;
white-space:nowrap}
.st i{width:9px;height:9px;flex:0 0 9px;background:var(--bad);border-radius:50%}
.st.on i{background:var(--good)}
.st.on{color:var(--fg)}
@media(max-width:640px){details.task > summary{grid-template-columns:1fr}
.status{justify-self:start;flex-direction:row;gap:18px}}

/* Opened detail. Reasons first, because the reasons are the judgement. */
.bd{padding:6px 2px 34px}
.sym{color:var(--muted);font-size:15px;margin:0 0 22px;max-width:70ch;font-style:italic}
.reason{font-family:var(--mono);font-size:12px;line-height:1.7;padding:0 0 0 16px;
border-left:2px solid var(--soft);color:var(--muted);margin:0 0 16px;white-space:pre-wrap;
overflow-x:auto}
.reason.r0{border-left-color:var(--bad)}
.reason.r1{border-left-color:var(--good)}
.reason b{color:var(--accent);font-weight:400;display:block;margin-bottom:6px;
font-family:var(--sans);font-size:12.5px;letter-spacing:0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:26px;margin:24px 0 0}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
.col h4{font-family:var(--sans);font-size:13px;letter-spacing:0;color:var(--accent);
font-weight:400;margin:0 0 12px}
.panel{margin:0 0 18px}
.panel img{width:100%;display:block;background:#050505}
.panel .lab{font-family:var(--sans);font-size:12.5px;letter-spacing:0;color:var(--dim);
margin:8px 0 3px}
.panel .num{font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.panel .num.key{color:var(--fg)}
details.eq{margin:20px 0 0}
details.eq summary{list-style:none;cursor:pointer;font-family:var(--sans);font-size:13px;
letter-spacing:0;color:var(--dim);padding:8px 0}
details.eq summary::-webkit-details-marker{display:none}
details.eq summary:hover{color:var(--accent)}
pre.diff{font-family:var(--mono);font-size:11.5px;line-height:1.6;color:var(--muted);
border-left:2px solid var(--soft);padding:2px 0 2px 16px;margin:6px 0 0;
overflow-x:auto;max-height:360px}
pre.diff .a{color:var(--good)}pre.diff .d{color:var(--bad)}

.alarm{border-left:2px solid var(--bad);padding:2px 0 2px 18px;margin:34px 0 0}
.alarm h3{font-family:var(--serif);font-weight:400;font-size:21px;margin:0 0 10px}
.alarm p{color:var(--muted);font-size:14px;margin:0 0 6px}
footer{margin-top:80px;padding-top:22px;border-top:1px solid var(--line);
font-family:var(--sans);font-size:12px;color:var(--dim);letter-spacing:0}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "review.html"))
    ap.add_argument("--env", action="append",
                    help="limit to one environment, repeatable")
    a = ap.parse_args()

    envs = a.env or sorted(d for d in os.listdir(ENVS)
                           if os.path.isdir(os.path.join(ENVS, d)))
    tmp = tempfile.mkdtemp(prefix="envreview-")
    body, alarms, counts = [], [], [0, 0]

    for env in envs:
        tdir = os.path.join(ENVS, env, "tasks")
        if not os.path.isdir(tdir):
            continue
        ext = EXT.get(env, "")
        tasks = sorted(f for f in os.listdir(tdir)
                       if f.endswith(".json") and not f.startswith("_"))
        body.append(f'<h2>{esc(AREAS.get(env, env))}</h2>')
        body.append(f'<div class="count">{len(tasks)} faults &nbsp;·&nbsp; {esc(env)}</div>')
        # Sound graders in an environment nobody else can run is a bench with no
        # door. Five files make it distributable; say which are missing.
        gone = [f for f in REQUIRED
                if not os.path.exists(os.path.join(ENVS, env, f))]
        if gone:
            body.append(f'<div class="ready"><i></i>Cannot be sent out. Missing '
                        f'{esc(", ".join(gone))}.</div>')
        else:
            body.append('<div class="ready on"><i></i>Complete. Anyone can run this '
                        'in a container.</div>')
        # A grader can score 0.0 on every broken file for one generic reason and
        # look perfect on a spreadsheet. If several tasks in an environment fail
        # with the identical sentence, it is not diagnosing, it is refusing.
        seen_reasons = collections.Counter()

        for tf in tasks:
            tpath = os.path.join(tdir, tf)
            spec = json.load(open(tpath))
            tid = spec.get("id", tf[:-5])
            # Two shapes exist in the wild. EXR and OCIO tasks name a sibling
            # file; ComfyUI tasks embed the graph in the spec itself. Grading the
            # spec as though it were the submission produced "node id is not an
            # object" on all four ComfyUI tasks, which is a 0.0 for the wrong
            # reason, and a 0.0 for the wrong reason is the thing this page is
            # supposed to catch rather than commit.
            broken = os.path.join(tdir, spec.get("broken_file", tid + ext))
            if "broken_graph" in spec:
                broken = os.path.join(tmp, f"{env}_{tid}_broken.json")
                json.dump(spec["broken_graph"], open(broken, "w"))
            elif not os.path.exists(broken):
                broken = os.path.join(tdir, tid + ext)

            # Two reference conventions exist: one shared _reference_good per
            # environment, and one per task named <task>_reference. Assuming the
            # first made three sound video tasks look broken, which is the page
            # telling a lie in the direction that costs a day.
            ref = next((c for c in (
                os.path.join(tdir, spec["reference"]) if spec.get("reference") else "",
                os.path.join(tdir, f"{tid}_reference{ext}"),
                os.path.join(tdir, "_reference_good" + ext),
            ) if c and os.path.exists(c)), "")

            on_broken = grade(env, tpath, broken)
            on_good = grade(env, tpath, ref) if os.path.exists(ref) else \
                {"reward": None, "reason": "no reference file for this environment"}

            catches = on_broken.get("reward") == 0.0
            accepts = on_good.get("reward") == 1.0
            reason = (on_broken.get("reason") or "").strip()
            seen_reasons[reason] += 1
            distinct = seen_reasons[reason] == 1
            sound = catches and accepts and distinct
            counts[0 if sound else 1] += 1
            if not sound:
                why = []
                if not catches:
                    why.append("does not fail the broken file")
                if not accepts:
                    why.append("does not pass the known-good file")
                if not distinct:
                    why.append("fails with a reason another task in this "
                               "environment already gave, so it is not diagnosing")
                alarms.append(f"{env} / {tid}: " + ", ".join(why))

            ev_broken, ev_good, diff = [], [], None
            if env == "exr_render_repair":
                try:
                    ev_broken = exr_panels(read_exr(broken))
                    ev_good = exr_panels(read_exr(ref))
                except Exception as e:                          # noqa: BLE001
                    diff = f"could not render EXR evidence: {e}"
            elif os.path.exists(ref) and os.path.exists(broken):
                diff = text_diff(broken, ref, f"broken/{tid}{ext}",
                                 f"reference{ext}")

            # The summary line has to answer the only question that matters
            # without being opened: did it catch the fault, did it accept good
            # work. Two bars and a clipped reason. Everything else is behind the
            # disclosure, default closed, so fourteen tasks read as one page
            # instead of one scroll.
            title = TITLES.get(tid, tid.replace("_", " ").capitalize())
            said = spec.get("symptom", "")
            said_clip = said if len(said) < 92 else said[:89] + "..."
            status = (
                f'<div class="status">'
                f'<span class="st{" on" if catches else ""}"><i></i>'
                f'{"Caught the mistake" if catches else "Missed the mistake"}</span>'
                f'<span class="st{" on" if accepts else ""}"><i></i>'
                f'{"Passed good work" if accepts else "Failed good work"}</span></div>')
            h = [f'<details class="task"><summary>'
                 f'<span class="tname">{esc(title)}'
                 f'<span class="said">{esc(said_clip)}</span></span>'
                 f'{status}</summary><div class="bd">']

            # Reasons before pictures. The reason is the thing being judged, and
            # it is written to be read by the person who would have said the
            # sentence above it rather than by the runner.
            for lab, res, want in (("What it said about the broken file", on_broken, 0.0),
                                   ("What it said about the correct file", on_good, 1.0)):
                r = res.get("reward")
                cls = "r1" if r == 1.0 else "r0" if r == 0.0 else ""
                right = "the right call" if r == want else "wrong, look at this"
                h.append(f'<div class="reason {cls}"><b>{esc(lab)} &nbsp;·&nbsp; {right}</b>'
                         f'{esc(res.get("reason", ""))}</div>')

            if ev_broken or ev_good:
                h.append('<div class="grid">')
                for label, panels in (("Broken", ev_broken), ("Correct", ev_good)):
                    h.append(f'<div class="col"><h4>{label}</h4>')
                    for name, uri, num in panels:
                        # The number that distinguishes the two files gets the
                        # bright treatment, because on a stretched depth pass the
                        # picture is identical and the number is the whole story.
                        key = " key" if ("Actual range" in num or "must be" in num) else ""
                        h.append(f'<div class="panel"><img src="{uri}" alt="{esc(name)}">'
                                 f'<div class="lab">{esc(name)}</div>'
                                 f'<div class="num{key}">{esc(num)}</div></div>')
                    h.append("</div>")
                h.append("</div>")

            if diff:
                lines = []
                for ln in diff.splitlines()[:160]:
                    cls = "a" if ln.startswith("+") else "d" if ln.startswith("-") else ""
                    lines.append(f'<span class="{cls}">{esc(ln)}</span>' if cls else esc(ln))
                h.append('<details class="eq"><summary>Show the fault that was put in</summary>'
                         '<pre class="diff">' + "\n".join(lines) + "</pre></details>")

            h.append("</div></details>")
            body.append("".join(h))

    body.append('<div class="later"><h3>Not built yet</h3>'
                '<p class="i">A bench showing only finished work looks complete and '
                'tells you nothing about the shape of the job. These are the faults '
                'with a buyer and no environment.</p>')
    for name, why in PLANNED:
        body.append(f'<div class="row"><b>{esc(name)}</b><span>{esc(why)}</span></div>')
    body.append('</div>')

    total = counts[0] + counts[1]
    bad = " bad" if counts[1] else ""
    verdict = ("Every check is working." if not counts[1]
               else f"{counts[1]} of {total} need looking at.")
    head = ["<h1>Touchstone</h1>",
            f'<p class="score"><span class="n{bad}">{counts[0]}</span>'
            f'<span style="color:var(--dim)"> of {total}</span>'
            f"<small>{esc(verdict)}</small></p>",
            '<p class="sub">A touchstone is the stone you streak a metal against to test its '
            'purity against a known standard. This is the same move on the checkers. Everything '
            'that grades a creative file belongs on this page before it is sent anywhere.</p>',
            '<p class="sub">Each fault below was put into a file on purpose. The checker has to '
            'do two things and it has to do both. Notice the mistake, and say what it is in words '
            'a compositor would recognise. And leave correct work alone, because a checker that '
            'fails everything is no use to anyone.</p>',
            '<p class="sub">The two dots on each line are those two things. Open a line to read '
            'what the checker actually said and decide whether you agree with it. That decision '
            'is yours; this page only puts it in front of you.</p>']
    if alarms:
        head.append('<div class="alarm"><h3>Do not send this out yet</h3>'
                    + "".join(f"<p>{esc(x)}</p>" for x in alarms) + "</div>")
    head.append('<hr class="rule">')

    html = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>Touchstone</title><style>{CSS}</style></head><body>"
            f'<div class="wrap">{"".join(head)}{"".join(body)}'
            f"<footer>Touchstone &nbsp;·&nbsp; proving the checkers before they leave</footer>"
            f"</div></body></html>")
    open(a.out, "w", encoding="utf-8").write(html)
    print(f"{a.out}  {counts[0]} sound, {counts[1]} flagged")
    return 1 if alarms else 0


if __name__ == "__main__":
    sys.exit(main())
