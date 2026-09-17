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
        clips = list((project / "clips").glob("*.mp4")) if (project / "clips").is_dir() else []
        result.append({"id": str(project.relative_to(ROOT)), "name": data.get("project_name", project.name),
                       "scenes": sum(len(b.get("shots", [])) for b in data.get("beats", [])),
                       "clips": len(clips), "video": str((project / "final_captioned.mp4").relative_to(ROOT))
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
        command = ["python3", str(ROOT / "scripts/wan_clips.py"), str(project), "--max-cost-usd", "2.00", "--yes"]
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
        if self.path != "/api/run":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", "0"))
        data = json.loads(self.rfile.read(length) or b"{}")
        project_id = data.get("project", "")
        if project_id not in [p["id"] for p in projects()]:
            return self.send_json({"error": "unknown project"}, 400)
        if not run_project(project_id):
            return self.send_json({"error": "a generation is already running"}, 409)
        self.send_json({"started": True})

    def log_message(self, *_):
        pass


PAGE = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shorts Studio</title>
<style>body{font:15px system-ui;background:#101214;color:#eee;max-width:1000px;margin:0 auto;padding:28px}button,select{font:inherit;padding:10px 14px;border-radius:8px;border:0;margin:4px;background:#d1fe17;color:#101214;font-weight:700}select{background:#252a2e;color:#fff}pre{background:#191d20;padding:16px;border-radius:10px;white-space:pre-wrap}video{max-width:360px;width:100%;background:#000;border-radius:10px}.card{background:#181b1e;padding:18px;border-radius:12px;margin:14px 0}</style></head>
<body><h1>Shorts Studio</h1><p>Replicate generation with local narration, captions, assembly, and quality checks.</p><div class="card"><select id="project"></select><button onclick="run()">Generate missing scenes</button><span id="status"></span></div><pre id="log">Ready.</pre><div id="gallery"></div>
<script>
async function refresh(){let p=await (await fetch('/api/projects')).json(),s=await (await fetch('/api/status')).json();let sel=document.querySelector('#project');let old=sel.value;sel.innerHTML=p.projects.map(x=>`<option value="${x.id}">${x.name} — ${x.clips}/${x.scenes} scenes</option>`).join('');if(old)sel.value=old;document.querySelector('#status').textContent=s.running?'Generating…':(s.returncode===0?' Complete':'');document.querySelector('#log').textContent=s.log||'Ready.';document.querySelector('#gallery').innerHTML=p.projects.filter(x=>x.video).map(x=>`<div class="card"><h3>${x.name}</h3><video controls src="/files/${x.video}"></video></div>`).join('')||''}
async function run(){let project=document.querySelector('#project').value;await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({project})});refresh()}setInterval(refresh,3000);refresh();
</script></body></html>'''


if __name__ == "__main__":
    print(f"Shorts Studio: http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
