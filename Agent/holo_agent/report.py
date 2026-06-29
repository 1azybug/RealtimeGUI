"""Render a Holo trajectory (a recorded result dir) into a self-contained HTML report.

Environment-agnostic: it reads only the generic ``traj.jsonl`` + per-step
observation screenshots + ``system_prompt.txt`` + (optional) ``result.txt`` that
``holo_agent.recorder.TrajectoryRecorder`` writes — so the same replay works for
OSWorld, RealtimeGym, or any future environment. It produces one portable file:
a step-by-step trace of what the agent SAW (each observation) and DID (its note /
thought / structured action / executed command), with the click target drawn on
the image as a crosshair reticle (a pure CSS/SVG overlay; the screenshot is never
modified). Images are embedded as base64 data URIs.

Usage::

    python -m holo_agent.report --task-dir <dir with traj.jsonl>   # -> <dir>/report.html
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os


POINTER_TOOLS = {"click", "double_click", "right_click", "scroll", "drag"}
KEYBOARD_TOOLS = {"write", "press_key", "hotkey"}


def _kind(tool: str) -> str:
    if tool in POINTER_TOOLS:
        return "pointer"
    if tool in KEYBOARD_TOOLS:
        return "keyboard"
    return "terminal"


def _data_uri(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _esc(x) -> str:
    return html.escape("" if x is None else str(x))


def _executed_command(d: dict):
    """The low-level command the env ran, if it recorded one (e.g. OSWorld pyautogui)."""
    info = d.get("info") or {}
    return d.get("pyautogui") or info.get("pyautogui") or info.get("command")


def _reticle(tc: dict, kind: str) -> str:
    if kind != "pointer":
        return ""

    def pct(v):
        return max(0.0, min(100.0, float(v) / 10.0))

    parts = []
    if tc.get("tool_name") == "drag" and tc.get("to_x") is not None:
        x1, y1, x2, y2 = pct(tc["x"]), pct(tc["y"]), pct(tc["to_x"]), pct(tc["to_y"])
        parts.append(
            f'<svg class="drag-line" viewBox="0 0 100 100" preserveAspectRatio="none">'
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" /></svg>'
        )
        parts.append(f'<div class="reticle start" style="left:{x1}%;top:{y1}%"></div>')
        parts.append(
            f'<div class="reticle" style="left:{x2}%;top:{y2}%">'
            f'<span class="coord">drag → ({tc["to_x"]}, {tc["to_y"]})</span></div>'
        )
        return "".join(parts)
    if tc.get("x") is not None and tc.get("y") is not None:
        x, y = pct(tc["x"]), pct(tc["y"])
        parts.append(
            f'<div class="reticle" style="left:{x}%;top:{y}%">'
            f'<span class="coord">{_esc(tc.get("tool_name","click"))} · ({tc["x"]}, {tc["y"]})</span></div>'
        )
    return "".join(parts)


def _action_summary(tc: dict) -> str:
    name = tc.get("tool_name", "")
    if name in ("click", "double_click", "right_click"):
        return f'{name}({tc.get("x")}, {tc.get("y")})  —  {_esc(tc.get("element",""))}'
    if name == "scroll":
        return f'scroll {tc.get("direction")} ×{tc.get("amount",3)} @ ({tc.get("x")}, {tc.get("y")})'
    if name == "drag":
        return f'drag ({tc.get("x")}, {tc.get("y")}) → ({tc.get("to_x")}, {tc.get("to_y")})'
    if name == "write":
        suffix = " + Enter" if tc.get("press_enter") else ""
        return f'write {json.dumps(tc.get("content",""), ensure_ascii=False)}{suffix}'
    if name == "press_key":
        return f'press_key "{_esc(tc.get("key"))}"'
    if name == "hotkey":
        return "hotkey " + " + ".join(_esc(k) for k in tc.get("keys", []))
    return name


def build_html(task_dir: str) -> str:
    traj = []
    with open(os.path.join(task_dir, "traj.jsonl"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                traj.append(json.loads(line))

    instruction = ""
    sysprompt = ""
    sp_path = os.path.join(task_dir, "system_prompt.txt")
    if os.path.exists(sp_path):
        sysprompt = open(sp_path, encoding="utf-8").read()
        if "<task>" in sysprompt:
            instruction = sysprompt.split("<task>", 1)[1].split("</task>", 1)[0].strip()

    score = None
    rp = os.path.join(task_dir, "result.txt")
    if os.path.exists(rp):
        try:
            score = float(open(rp).read().strip())
        except ValueError:
            pass

    # Optional sidecar metadata (env-specific, written by the runner). The report
    # only knows two conventional keys: ``banner`` ({text, level}) and ``facts`` (dict).
    meta = {}
    mp = os.path.join(task_dir, "meta.json")
    if os.path.exists(mp):
        try:
            meta = json.load(open(mp, encoding="utf-8")) or {}
        except (ValueError, OSError):
            meta = {}

    success = score is not None and score >= 0.999
    status_txt = "—" if score is None else ("SUCCESS" if success else "FAIL")
    status_cls = "ok" if success else ("bad" if score is not None else "")
    model = os.path.basename(os.path.dirname(os.path.dirname(task_dir)))

    steps_html = []
    for d in traj:
        tc = d.get("tool_call") or {}
        tool = d.get("tool_name") or tc.get("tool_name") or "?"
        kind = _kind(tool)
        img_file = d.get("screenshot_file")
        img_path = os.path.join(task_dir, img_file) if img_file else None
        img_uri = _data_uri(img_path) if img_path and os.path.exists(img_path) else ""
        reticle = _reticle(tc, kind)
        note = d.get("note")
        note_html = (
            f'<div class="field note"><span class="k">note</span><p>{_esc(note)}</p></div>'
            if note else ""
        )
        reasoning = (d.get("reasoning") or "").strip()
        reasoning_html = (
            f'<details class="reasoning"><summary>reasoning_content</summary><pre>{_esc(reasoning)}</pre></details>'
            if reasoning else ""
        )
        cmd = _executed_command(d)
        code_html = f'<pre class="code">{_esc(cmd)}</pre>' if cmd else ""
        steps_html.append(f"""
      <section class="step k-{kind}">
        <div class="rail"><span class="tick">{d.get('step_num')}</span></div>
        <figure class="shot">
          <div class="imgwrap">
            <img loading="lazy" src="{img_uri}" alt="observation at step {d.get('step_num')}">
            {reticle}
          </div>
          <figcaption>observation · step {d.get('step_num')}</figcaption>
        </figure>
        <div class="meta">
          <div class="toolrow"><span class="chip {kind}">{_esc(tool)}</span>
            <span class="summary">{_esc(_action_summary(tc))}</span></div>
          <div class="field"><span class="k">thought</span><p>{_esc(d.get('thought'))}</p></div>
          {note_html}
          {code_html}
          {reasoning_html}
        </div>
      </section>""")

    # Banner (e.g. an INFEASIBLE-task warning) + extra facts, both from meta.json.
    banner = meta.get("banner") or {}
    banner_html = ""
    if isinstance(banner, dict) and banner.get("text"):
        lvl = banner.get("level", "info")
        banner_html = f'<div class="banner {_esc(lvl)}">{_esc(banner.get("text"))}</div>'
    extra_facts = ""
    if isinstance(meta.get("facts"), dict):
        for k, v in meta["facts"].items():
            extra_facts += f'<span>{_esc(k)} <b>{_esc(v)}</b></span>'

    sys_block = (
        f'<details class="sysprompt"><summary>system prompt sent to the model'
        f' <span class="hint">(instructions + output schema + task)</span></summary>'
        f'<pre>{_esc(sysprompt)}</pre></details>'
        if sysprompt else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Holo trace · {_esc(instruction[:60])}</title>
<style>
  :root {{
    --bg:#0d1014; --panel:#141a21; --panel2:#1b222c; --line:#283039;
    --text:#d8dee6; --muted:#8a94a3; --dim:#5f6b7a;
    --pointer:#ff7a29; --keyboard:#46d6c6; --terminal:#b389ff;
    --ok:#3fb950; --bad:#f85149;
  }}
  * {{ box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; }}
  body {{
    margin:0; background:
      radial-gradient(1200px 600px at 80% -10%, #16202b 0%, transparent 60%),
      var(--bg);
    color:var(--text);
    font:15px/1.6 ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;
  }}
  header.hero {{ padding:40px 28px 26px; border-bottom:1px solid var(--line);
    background:linear-gradient(180deg,#11171f, transparent); }}
  .eyebrow {{ font-family:ui-monospace,monospace; letter-spacing:.34em; text-transform:uppercase;
    font-size:11px; color:var(--pointer); margin:0 0 12px; }}
  h1 {{ margin:0 0 18px; font-size:clamp(22px,3.4vw,36px); font-weight:650; letter-spacing:-.02em;
    max-width:60ch; line-height:1.18; }}
  .facts {{ display:flex; flex-wrap:wrap; gap:10px 26px; align-items:center;
    font-family:ui-monospace,monospace; font-size:12.5px; color:var(--muted); }}
  .facts b {{ color:var(--text); font-weight:600; }}
  .status {{ display:inline-flex; align-items:center; gap:8px; padding:5px 12px; border-radius:999px;
    border:1px solid var(--line); font-weight:700; letter-spacing:.08em; }}
  .status.ok {{ color:var(--ok); border-color:color-mix(in srgb,var(--ok) 45%, var(--line)); }}
  .status.bad {{ color:var(--bad); border-color:color-mix(in srgb,var(--bad) 45%, var(--line)); }}
  .banner {{ margin-top:18px; padding:12px 16px; border-radius:10px; font-weight:600; font-size:13.5px;
    border:1px solid var(--line); line-height:1.5; }}
  .banner.warn {{ color:#ffcaa3; background:color-mix(in srgb,var(--pointer) 14%, transparent);
    border-color:color-mix(in srgb,var(--pointer) 45%, var(--line)); }}
  .banner.info {{ color:var(--muted); background:var(--panel); }}
  .status .dot {{ width:8px; height:8px; border-radius:50%; background:currentColor; box-shadow:0 0 12px currentColor; }}
  main {{ max-width:1180px; margin:0 auto; padding:22px 20px 80px; }}
  details.sysprompt,details.reasoning {{ border:1px solid var(--line); border-radius:10px;
    background:var(--panel); margin:18px 0; }}
  details.sysprompt > summary {{ padding:13px 16px; cursor:pointer; font-weight:600; color:var(--text); }}
  .hint {{ color:var(--dim); font-weight:400; }}
  details pre {{ margin:0; padding:16px; border-top:1px solid var(--line); overflow:auto; max-height:360px;
    font-family:ui-monospace,monospace; font-size:12px; color:var(--muted); white-space:pre-wrap; }}
  .step {{ display:grid; grid-template-columns:34px minmax(0,1.35fr) minmax(0,1fr); gap:20px;
    padding:24px 0; border-top:1px solid var(--line); align-items:start; }}
  .step:first-of-type {{ border-top:none; }}
  .rail {{ display:flex; justify-content:center; padding-top:6px; }}
  .tick {{ font-family:ui-monospace,monospace; font-size:13px; font-weight:700; color:var(--bg);
    width:30px; height:30px; border-radius:50%; display:grid; place-items:center;
    background:var(--pointer); box-shadow:0 0 0 4px color-mix(in srgb,var(--pointer) 18%, transparent); }}
  .k-keyboard .tick {{ background:var(--keyboard); box-shadow:0 0 0 4px color-mix(in srgb,var(--keyboard) 18%, transparent); }}
  .k-terminal .tick {{ background:var(--terminal); box-shadow:0 0 0 4px color-mix(in srgb,var(--terminal) 18%, transparent); }}
  figure.shot {{ margin:0; }}
  .imgwrap {{ position:relative; border:1px solid var(--line); border-radius:12px; overflow:hidden;
    background:#000; box-shadow:0 18px 40px -24px #000; }}
  .imgwrap img {{ display:block; width:100%; height:auto; }}
  figcaption {{ margin-top:8px; font-family:ui-monospace,monospace; font-size:11px; letter-spacing:.12em;
    text-transform:uppercase; color:var(--dim); }}
  /* signature element: the targeting reticle drawn on the observation */
  .reticle {{ position:absolute; width:0; height:0; }}
  .reticle::before, .reticle::after {{ content:""; position:absolute; background:var(--pointer); }}
  .reticle::before {{ width:2px; height:34px; left:-1px; top:-17px; box-shadow:0 0 8px var(--pointer); }}
  .reticle::after  {{ height:2px; width:34px; top:-1px; left:-17px; box-shadow:0 0 8px var(--pointer); }}
  .reticle > .coord {{ position:absolute; left:16px; top:-30px; white-space:nowrap;
    font-family:ui-monospace,monospace; font-size:11px; font-weight:600; color:#0d1014;
    background:var(--pointer); padding:3px 7px; border-radius:5px; box-shadow:0 4px 14px -4px var(--pointer); }}
  .reticle:not(.start) {{ outline:2px solid var(--pointer); outline-offset:9px; border-radius:50%; }}
  .reticle.start {{ width:14px; height:14px; margin:-7px 0 0 -7px; border:2px solid var(--pointer);
    border-radius:50%; background:transparent; }}
  .reticle.start::before,.reticle.start::after {{ display:none; }}
  @keyframes pulse {{ 0%{{ box-shadow:0 0 0 0 color-mix(in srgb,var(--pointer) 55%,transparent);}}
    100%{{ box-shadow:0 0 0 22px transparent;}} }}
  .reticle:not(.start) {{ animation:pulse 1.8s ease-out infinite; }}
  svg.drag-line {{ position:absolute; inset:0; width:100%; height:100%; pointer-events:none; }}
  svg.drag-line line {{ stroke:var(--pointer); stroke-width:.5; stroke-dasharray:2 1.5; opacity:.85; }}
  .meta {{ min-width:0; }}
  .toolrow {{ display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; margin-bottom:14px; }}
  .chip {{ font-family:ui-monospace,monospace; font-size:11.5px; font-weight:700; letter-spacing:.06em;
    padding:4px 10px; border-radius:6px; text-transform:uppercase; color:#0d1014; }}
  .chip.pointer {{ background:var(--pointer); }} .chip.keyboard {{ background:var(--keyboard); }}
  .chip.terminal {{ background:var(--terminal); }}
  .summary {{ font-family:ui-monospace,monospace; font-size:12.5px; color:var(--muted); word-break:break-word; }}
  .field {{ margin:12px 0; }}
  .field .k {{ display:block; font-family:ui-monospace,monospace; font-size:10.5px; letter-spacing:.18em;
    text-transform:uppercase; color:var(--dim); margin-bottom:3px; }}
  .field p {{ margin:0; color:var(--text); }}
  .field.note p {{ color:var(--keyboard); }}
  pre.code {{ margin:12px 0 0; padding:12px 14px; background:#0a0d11; border:1px solid var(--line);
    border-radius:8px; overflow:auto; font-family:ui-monospace,monospace; font-size:12px; color:#aeb9c7; }}
  details.reasoning summary {{ padding:9px 12px; cursor:pointer; font-family:ui-monospace,monospace;
    font-size:11px; color:var(--dim); }}
  footer {{ max-width:1180px; margin:0 auto; padding:0 20px 60px; color:var(--dim);
    font-family:ui-monospace,monospace; font-size:11.5px; }}
  @media (max-width:820px) {{ .step {{ grid-template-columns:26px 1fr; }} .meta {{ grid-column:2; }} }}
  @media (prefers-reduced-motion:reduce) {{ .reticle:not(.start){{ animation:none; }} html{{scroll-behavior:auto;}} }}
</style>
</head>
<body>
  <header class="hero">
    <p class="eyebrow">Holo-3.1 · computer-use trace</p>
    <h1>{_esc(instruction) or "Holo agent trajectory"}</h1>
    <div class="facts">
      <span class="status {status_cls}"><span class="dot"></span>{status_txt}{'' if score is None else f' · {score:g}'}</span>
      <span>model <b>{_esc(model)}</b></span>
      <span>steps <b>{len(traj)}</b></span>
      <span>action legend ·
        <b style="color:var(--pointer)">mouse</b> /
        <b style="color:var(--keyboard)">keyboard</b> /
        <b style="color:var(--terminal)">terminal</b></span>
      {extra_facts}
    </div>
    {banner_html}
  </header>
  <main>
    {sys_block}
    {''.join(steps_html)}
  </main>
  <footer>Generated from traj.jsonl · the amber reticle marks where the model chose to act, drawn on the exact screenshot it observed.</footer>
</body>
</html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True, help="a recorded result dir containing traj.jsonl")
    ap.add_argument("--out", default=None, help="output html path (default <task-dir>/report.html)")
    args = ap.parse_args()
    out = args.out or os.path.join(args.task_dir, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build_html(args.task_dir))
    print("wrote", out)


if __name__ == "__main__":
    main()
