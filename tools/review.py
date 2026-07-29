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
       "exr_render_repair": ".exr"}


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
                    f"ACTUAL RANGE {z.min():.3f} to {z.max():.3f}"))
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
:root{--bg:#000;--fg:#ececec;--muted:#8a8a8a;--dim:#5f5f5f;--accent:#9aa1a8;
--bad:#b06a6a;--good:#7f9a7f;--line:rgba(255,255,255,.11);--soft:rgba(255,255,255,.055);
--card:rgba(255,255,255,.022);--sans:'Sohne','Helvetica Neue',Arial,sans-serif;
--serif:'Canela',Georgia,serif;--mono:ui-monospace,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;
line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:60px 34px 110px}
h1{font-family:var(--serif);font-weight:400;font-size:34px;margin:0 0 6px}
.sub{color:var(--muted);max-width:64ch;margin:0 0 34px}
h2{font-family:var(--serif);font-weight:400;font-size:25px;margin:52px 0 4px}
.envline{font-family:var(--mono);font-size:11px;color:var(--dim);letter-spacing:.1em;
margin-bottom:18px}
.task{border:1px solid var(--soft);background:var(--card);margin:0 0 16px}
.task .hd{display:flex;justify-content:space-between;align-items:baseline;gap:18px;
padding:17px 22px;border-bottom:1px solid var(--soft);flex-wrap:wrap}
.task h3{font-family:var(--serif);font-weight:400;font-size:19px;margin:0}
.verdict{font-family:var(--mono);font-size:10.5px;letter-spacing:.12em}
.sound{color:var(--good)}.flag{color:var(--bad)}
.bd{padding:18px 22px 22px}
.sym{color:var(--muted);font-size:14px;margin:0 0 16px;max-width:74ch}
.sym b{color:var(--accent);font-weight:400;font-family:var(--mono);font-size:10.5px;
letter-spacing:.12em;display:block;margin-bottom:5px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:6px 0 4px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.col h4{font-family:var(--mono);font-size:9.5px;letter-spacing:.15em;color:var(--accent);
font-weight:400;margin:0 0 10px}
.panel{margin:0 0 14px}
.panel img{width:100%;display:block;border:1px solid var(--soft);background:#050505}
.panel .lab{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;color:var(--dim);
margin:6px 0 2px}
.panel .num{font-family:var(--mono);font-size:11px;color:var(--muted)}
.reason{font-family:var(--mono);font-size:11.5px;line-height:1.65;padding:12px 14px;
border-left:2px solid var(--soft);color:var(--muted);margin:14px 0 0;white-space:pre-wrap;
overflow-x:auto}
.reason.r0{border-left-color:var(--bad)}
.reason.r1{border-left-color:var(--good)}
.reason b{color:var(--accent);font-weight:400;display:block;margin-bottom:5px;
font-size:9.5px;letter-spacing:.15em}
pre.diff{font-family:var(--mono);font-size:11px;line-height:1.55;color:var(--muted);
background:rgba(255,255,255,.015);border:1px solid var(--soft);padding:13px 15px;margin:12px 0 0;
overflow-x:auto;max-height:340px}
pre.diff .a{color:var(--good)}pre.diff .d{color:var(--bad)}
.alarm{border:1px solid var(--bad);padding:18px 22px;margin:0 0 34px;color:var(--fg)}
.alarm h3{font-family:var(--serif);font-weight:400;font-size:19px;margin:0 0 8px}
.alarm ul{margin:0;padding-left:18px}.alarm li{color:var(--muted);font-size:14px}
footer{margin-top:70px;padding-top:20px;border-top:1px solid var(--line);
font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:.1em}
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
        ref = os.path.join(tdir, "_reference_good" + ext)
        tasks = sorted(f for f in os.listdir(tdir)
                       if f.endswith(".json") and not f.startswith("_"))
        body.append(f"<h2>{esc(env)}</h2>")
        body.append(f'<div class="envline">{len(tasks)} TASKS &nbsp;·&nbsp; '
                    f'GRADED IN BOTH DIRECTIONS</div>')
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

            v = ('<span class="verdict sound">SOUND</span>' if sound
                 else '<span class="verdict flag">FLAGGED</span>')
            h = [f'<div class="task"><div class="hd"><h3>{esc(tid)}</h3>{v}</div><div class="bd">']
            if spec.get("symptom"):
                h.append(f'<p class="sym"><b>WHAT THE ARTIST SAID</b>{esc(spec["symptom"])}</p>')

            if ev_broken or ev_good:
                h.append('<div class="grid">')
                for label, panels in (("BROKEN", ev_broken), ("KNOWN GOOD", ev_good)):
                    h.append(f'<div class="col"><h4>{label}</h4>')
                    for name, uri, num in panels:
                        h.append(f'<div class="panel"><img src="{uri}" alt="{esc(name)}">'
                                 f'<div class="lab">{esc(name)}</div>'
                                 f'<div class="num">{esc(num)}</div></div>')
                    h.append("</div>")
                h.append("</div>")

            if diff:
                lines = []
                for ln in diff.splitlines()[:160]:
                    cls = "a" if ln.startswith("+") else "d" if ln.startswith("-") else ""
                    lines.append(f'<span class="{cls}">{esc(ln)}</span>' if cls else esc(ln))
                h.append('<pre class="diff">' + "\n".join(lines) + "</pre>")

            for lab, res in (("ON THE BROKEN FILE", on_broken), ("ON THE KNOWN-GOOD FILE", on_good)):
                r = res.get("reward")
                cls = "r1" if r == 1.0 else "r0" if r == 0.0 else ""
                h.append(f'<div class="reason {cls}"><b>{lab} &nbsp; REWARD {r}</b>'
                         f'{esc(res.get("reason", ""))}</div>')
            h.append("</div></div>")
            body.append("".join(h))

    head = [f"<h1>Grader review</h1>",
            f'<p class="sub">Every task graded twice. The broken file must fail with a reason '
            f'that names the real fault, and the known-good file must pass. A task is sound only '
            f'when both hold. Read the reasons and decide whether the machine was right; that '
            f'judgement is the thing this page exists for.</p>']
    if alarms:
        head.append('<div class="alarm"><h3>Not fit to distribute</h3><ul>'
                    + "".join(f"<li>{esc(x)}</li>" for x in alarms) + "</ul></div>")
    head.append(f'<div class="envline">{counts[0]} SOUND &nbsp;·&nbsp; {counts[1]} FLAGGED</div>')

    html = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>Grader review</title><style>{CSS}</style></head><body>"
            f'<div class="wrap">{"".join(head)}{"".join(body)}'
            f"<footer>ALABO CREATIVE ENVS &nbsp;·&nbsp; GRADER REVIEW</footer>"
            f"</div></body></html>")
    open(a.out, "w", encoding="utf-8").write(html)
    print(f"{a.out}  {counts[0]} sound, {counts[1]} flagged")
    return 1 if alarms else 0


if __name__ == "__main__":
    sys.exit(main())
