#!/usr/bin/env python3
"""Propose candidate faults, put them in front of a practitioner, keep the verdicts.

The machine can draft a fault. It cannot know which faults matter, because that
comes from having been in a room where one shipped. So this does the typing and
you do the judging, and the judging is recorded, because a record of what you
chose is the only asset in this repository that cannot be rebuilt by somebody
reading the code.

Three steps.

    python3 tools/propose.py sheet  candidates/nuke.json  --out judge.html
    ... open judge.html, mark each one, press Copy verdicts ...
    python3 tools/propose.py apply  candidates/nuke.json  verdicts.json \\
        --env nuke_script_repair --app Nuke --ext .nk

`sheet` renders the candidates for judgement. `apply` scaffolds the environment
and writes a task stub for every fault you kept, with your reason attached.

Candidates can come from anywhere: this session, a local model, or your own head
written straight into the JSON. The generation is deliberately not wired to any
service, because the verdicts must never leave this machine.

The test every candidate has to pass, and the reason most drafts fail it: the
fault must RUN. No error, no warning, delivers cleanly, and is wrong. A fault
that throws is already caught by the software and is not worth grading.
"""
import argparse, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CSS = """
:root{--bg:#000;--fg:#ececec;--muted:#8a8a8a;--dim:#585858;--accent:#9aa1a8;
--bad:#b8695f;--good:#7d9c86;--line:rgba(255,255,255,.10);--soft:rgba(255,255,255,.05);
--sans:'Sohne',-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
--serif:'Canela','Iowan Old Style',Georgia,serif;--mono:ui-monospace,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;
line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:880px;margin:0 auto;padding:76px 36px 140px}
h1{font-family:var(--serif);font-weight:400;font-size:38px;margin:0 0 16px}
.sub{color:var(--muted);max-width:60ch;margin:0 0 10px}
hr{border:0;border-top:1px solid var(--line);margin:44px 0 0}
.c{border-bottom:1px solid var(--soft);padding:30px 2px}
.c h2{font-family:var(--serif);font-weight:400;font-size:22px;margin:0 0 10px}
.said{font-style:italic;color:var(--dim);margin:0 0 16px;max-width:66ch}
.k{font-size:12.5px;color:var(--accent);margin:16px 0 5px}
.v{font-size:14.5px;color:var(--muted);max-width:70ch;margin:0}
.opts{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0 0}
.opts button{font-family:var(--sans);font-size:13.5px;background:none;color:var(--muted);
border:1px solid var(--soft);border-radius:0;padding:9px 15px;cursor:pointer}
.opts button:hover{border-color:var(--line);color:var(--fg)}
.opts button.on{border-color:var(--accent);color:var(--fg)}
.opts button.build.on{border-color:var(--good);color:var(--good)}
.opts button.no.on{border-color:var(--bad);color:var(--bad)}
textarea{width:100%;margin:14px 0 0;background:rgba(255,255,255,.02);color:var(--fg);
border:1px solid var(--soft);border-radius:0;font-family:var(--sans);font-size:13.5px;
padding:11px 13px;min-height:56px;outline:none;resize:vertical}
textarea:focus{border-color:var(--accent)}
.bar{position:fixed;left:0;right:0;bottom:0;background:#050505;border-top:1px solid var(--line);
padding:16px 36px;display:flex;gap:18px;align-items:center;justify-content:space-between}
.bar span{font-size:13.5px;color:var(--muted)}
.bar button{font-family:var(--sans);font-size:13.5px;background:none;color:var(--fg);
border:1px solid var(--accent);border-radius:0;padding:10px 20px;cursor:pointer}
"""


def sheet(a):
    cands = json.load(open(a.candidates))
    rows = []
    for i, c in enumerate(cands):
        rows.append(f"""<div class="c" data-i="{i}">
<h2>{esc(c.get('title',''))}</h2>
<p class="said">{esc(c.get('symptom',''))}</p>
<p class="k">Does it throw an error</p><p class="v">{esc(c.get('errors','unstated'))}</p>
<p class="k">How the grader would catch it</p><p class="v">{esc(c.get('check',''))}</p>
<p class="k">What the person has to know</p><p class="v">{esc(c.get('skill',''))}</p>
<div class="opts">
  <button class="build" data-v="build">Build it</button>
  <button data-v="maybe">Not sure</button>
  <button class="no" data-v="no">No</button>
</div>
<textarea placeholder="Why. This is the part worth keeping."></textarea>
</div>""")
    html = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Candidate faults</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Candidate faults</h1>
<p class="sub">Drafted, not decided. A fault only belongs here if it runs, errors nowhere,
delivers, and is wrong. Anything that throws is already caught by the software.</p>
<p class="sub">Your reason matters more than your verdict. It is the thing that cannot be
rebuilt from the code.</p>
<hr>
{''.join(rows)}
</div>
<div class="bar"><span id="n">0 judged</span>
<button id="copy">Copy verdicts</button></div>
<script>
var V={{}};
document.querySelectorAll('.c').forEach(function(c){{
  var i=c.dataset.i;
  c.querySelectorAll('.opts button').forEach(function(b){{
    b.onclick=function(){{
      c.querySelectorAll('.opts button').forEach(function(x){{x.classList.remove('on')}});
      b.classList.add('on');
      V[i]=V[i]||{{}}; V[i].verdict=b.dataset.v; save();
    }};
  }});
  c.querySelector('textarea').addEventListener('input',function(e){{
    V[i]=V[i]||{{}}; V[i].reason=e.target.value; save();
  }});
}});
function save(){{
  try{{localStorage.setItem('propose:v1',JSON.stringify(V))}}catch(e){{}}
  document.getElementById('n').textContent=
    Object.values(V).filter(function(x){{return x.verdict}}).length+' judged';
}}
try{{V=JSON.parse(localStorage.getItem('propose:v1')||'{{}}');
  Object.keys(V).forEach(function(i){{
    var c=document.querySelector('.c[data-i="'+i+'"]'); if(!c)return;
    if(V[i].verdict){{var b=c.querySelector('[data-v="'+V[i].verdict+'"]'); if(b)b.classList.add('on');}}
    if(V[i].reason)c.querySelector('textarea').value=V[i].reason;
  }}); save();
}}catch(e){{}}
document.getElementById('copy').onclick=function(){{
  navigator.clipboard.writeText(JSON.stringify(V,null,2));
  this.textContent='Copied. Save it as verdicts.json';
}};
</script></body></html>"""
    open(a.out, "w", encoding="utf-8").write(html)
    print(f"  {a.out}   {len(cands)} candidates to judge")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def apply(a):
    cands = json.load(open(a.candidates))
    verdicts = json.load(open(a.verdicts))
    kept = [(i, c) for i, c in enumerate(cands)
            if verdicts.get(str(i), {}).get("verdict") == "build"]
    if not kept:
        sys.exit("  nothing marked build. Judge the sheet first.")

    base = os.path.join(ROOT, "environments", a.env)
    if not os.path.exists(os.path.join(base, "task.toml")):
        subprocess.run([sys.executable, os.path.join(ROOT, "tools", "scaffold.py"),
                        a.env, "--app", a.app, "--ext", a.ext], check=True)

    os.makedirs(os.path.join(base, "tasks"), exist_ok=True)
    print(f"\n  {len(kept)} kept of {len(cands)}\n")
    for i, c in kept:
        tid = c.get("id") or f"fault_{i}"
        p = os.path.join(base, "tasks", f"{tid}.json")
        if os.path.exists(p):
            print(f"  skip (exists)  {tid}")
            continue
        json.dump({
            "id": tid,
            "application": a.app,
            "broken_file": f"{tid}{a.ext}",
            "symptom": c.get("symptom", ""),
            "reference": "_reference_good" + a.ext,
            "may_change": [],
            "_todo": "Build the broken file and fill may_change. Then write the check "
                     "in tests/grader.py and an attack in tools/reward_hack.py.",
            "_kept_because": verdicts.get(str(i), {}).get("reason", ""),
            "_check_sketch": c.get("check", ""),
        }, open(p, "w"), indent=2)
        print(f"  wrote task     {tid}")

    # The verdicts are the asset. Keep them where they were made and never ship
    # them; a record of what a practitioner rejected is worth more than the list
    # of what they kept, and it cannot be reconstructed from the repository.
    log = os.path.join(ROOT, "judgement.local.json")
    hist = json.load(open(log)) if os.path.exists(log) else []
    hist.append({"env": a.env, "candidates": a.candidates, "verdicts": verdicts})
    json.dump(hist, open(log, "w"), indent=2)
    print(f"\n  verdicts appended to judgement.local.json (gitignored, never published)\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("sheet"); s.add_argument("candidates")
    s.add_argument("--out", default=os.path.join(ROOT, "judge.html"))
    p = sub.add_parser("apply"); p.add_argument("candidates"); p.add_argument("verdicts")
    p.add_argument("--env", required=True); p.add_argument("--app", required=True)
    p.add_argument("--ext", required=True)
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help(); return
    {"sheet": sheet, "apply": apply}[a.cmd](a)


if __name__ == "__main__":
    main()
