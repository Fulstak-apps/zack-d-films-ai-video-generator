#!/usr/bin/env python3
"""Small local browser studio for the Replicate-backed Shorts pipeline."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("SHORTS_STUDIO_PORT", "8787"))
STATE = {"running": False, "project": None, "log": "", "returncode": None}
LOCK = threading.Lock()


def load_env():
    env = os.environ.copy()
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env.setdefault(key.strip(), value.strip().strip('"\''))
    return env


def projects():
    result = []
    for beats in sorted((ROOT / "out").glob("*/beats.json")):
        project = beats.parent
        data = json.loads(beats.read_text())
        shots = [shot["shot_id"] for beat in data.get("beats", []) for shot in beat.get("shots", [])]
        clips = [project / "clips" / f"{shot_id}.mp4" for shot_id in shots]
        complete = [clip for clip in clips if clip.is_file() and clip.stat().st_size]
        result.append({"id": str(project.relative_to(ROOT)), "name": data.get("project_name", project.name),
                       "scenes": len(shots), "clips": len(complete), "missing": len(shots) - len(complete),
                       "estimated_cost": round((len(shots) - len(complete)) * 4 * 0.05, 2),
                       "video": str((project / "final_captioned.mp4").relative_to(ROOT))
                       if (project / "final_captioned.mp4").is_file() else None})
    return result


def run_project(project_id):
    project = ROOT / project_id
    with LOCK:
        if STATE["running"]:
            return False
        STATE.update(running=True, project=project_id, log="Starting Replicate generation...", returncode=None)

    def worker():
        env = load_env()
        python = str(ROOT / "venv/bin/python") if (ROOT / "venv/bin/python").exists() else "python3"
        command = [python, str(ROOT / "scripts/wan_clips.py"), str(project), "--max-cost-usd", "2.00", "--yes"]
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        lines = []
        for line in process.stdout:
            lines.append(line.rstrip())
            with LOCK:
                STATE["log"] = "\n".join(lines[-80:])
        code = process.wait()
        with LOCK:
            STATE.update(running=False, returncode=code)

    threading.Thread(target=worker, daemon=True).start()
    return True


def assemble_project(project_id):
    project = ROOT / project_id
    with LOCK:
        if STATE["running"]:
            return False
        STATE.update(running=True, project=project_id, log="Building local narration, captions, and final export...", returncode=None)
    def worker():
        python = str(ROOT / "venv/bin/python") if (ROOT / "venv/bin/python").exists() else "python3"
        commands = [[python, str(ROOT / "scripts/local_tts.py"), str(project)],
                    [python, str(ROOT / "scripts/local_captions.py"), str(project), "--reuse-timing-srt"],
                    [python, str(ROOT / "scripts/assemble.py"), str(project)],
                    [python, str(ROOT / "scripts/finish_local.py"), str(project), "--captions"],
                    [python, str(ROOT / "scripts/quality_gate.py"), str(project)]]
        lines=[]; code=0
        for command in commands:
            process=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            lines.extend(process.stdout.splitlines()); code=process.returncode
            if code: break
            with LOCK: STATE["log"]="\n".join(lines[-80:])
        with LOCK: STATE.update(running=False,returncode=code,log="\n".join(lines[-80:]))
    threading.Thread(target=worker,daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/projects":
            return self.send_json({"projects": projects()})
        if path == "/api/status":
            with LOCK:
                return self.send_json(dict(STATE))
        if path.startswith("/files/"):
            target = (ROOT / path.removeprefix("/files/")).resolve()
            if ROOT not in target.parents or not target.is_file():
                return self.send_error(404)
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4" if target.suffix == ".mp4" else "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path not in ("/api/run", "/api/assemble"):
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        project_id = data.get("project", "")
        if project_id not in [p["id"] for p in projects()]:
            return self.send_json({"error": "unknown project"}, 400)
        action = assemble_project if self.path == "/api/assemble" else run_project
        if not action(project_id):
            return self.send_json({"error": "a generation is already running"}, 409)
        self.send_json({"started": True})

    def log_message(self, *_):
        pass


PAGE = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shorts Studio</title>
<style>body{font:15px system-ui;background:#0d1010;color:#f1f5ee;max-width:1100px;margin:auto;padding:30px}h1{font-size:32px;margin:0}.muted{color:#9aa49b}.grid{display:grid;grid-template-columns:1.2fr .8fr;gap:16px}.card{background:#171b19;border:1px solid #29332d;padding:20px;border-radius:14px;margin:16px 0}button,select{font:inherit;padding:11px 14px;border-radius:9px;border:0;margin:5px;background:#d1fe17;color:#0d1010;font-weight:750}button.alt{background:#2c3530;color:#fff}select{background:#252c28;color:#fff;width:100%}pre{background:#0a0d0b;padding:16px;border-radius:10px;white-space:pre-wrap;min-height:80px;max-height:260px;overflow:auto}video{width:100%;background:#000;border-radius:10px}.pill{padding:5px 8px;border-radius:20px;background:#29332d;color:#c7d1c9;font-size:12px}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}</style></head>
<body><h1>Shorts Studio</h1><p class="muted">Scene-first video production with Replicate generation and local finishing.</p><div class="grid"><section class="card"><label class="muted">PROJECT</label><select id="project" onchange="refresh()"></select><p id="details" class="muted"></p><button onclick="run('/api/run')">Generate missing scenes</button><button class="alt" onclick="run('/api/assemble')">Build final video</button></section><section class="card"><b>Production guardrails</b><p class="muted">Portrait source frames · per-scene progress · local narration · verified captions · export quality gate</p><span class="pill">Wan 3 · 480p · 9:16</span> <span class="pill">Replicate token stays local</span></section></div><section class="card"><b id="status">Ready</b><pre id="log">Ready.</pre></section><h2>Finished videos</h2><div id="gallery" class="gallery"></div>
<script>
let cache=[];async function refresh(){let p=await (await fetch('/api/projects')).json(),s=await (await fetch('/api/status')).json();cache=p.projects;let sel=document.querySelector('#project'),old=sel.value;sel.innerHTML=p.projects.map(x=>`<option value="${x.id}">${x.name}</option>`).join('');if(old)sel.value=old;let x=cache.find(x=>x.id===sel.value)||cache[0];document.querySelector('#details').textContent=`${x.clips}/${x.scenes} scenes ready · ${x.missing} remaining · estimated Replicate cost $${x.estimated_cost.toFixed(2)}`;document.querySelector('#status').textContent=s.running?'Working on '+s.project:(s.returncode===0?'Last job complete':'Ready');document.querySelector('#log').textContent=s.log||'Ready.';document.querySelector('#gallery').innerHTML=p.projects.filter(x=>x.video).map(x=>`<div class="card"><b>${x.name}</b><video controls src="/files/${x.video}"></video></div>`).join('')||'<p class="muted">No completed videos yet.</p>'}
async function run(url){let project=document.querySelector('#project').value;await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project})});refresh()}setInterval(refresh,3000);refresh();
</script></body></html>'''


if __name__ == "__main__":
    print(f"Shorts Studio: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
