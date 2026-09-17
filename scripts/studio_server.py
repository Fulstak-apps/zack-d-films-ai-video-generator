#!/usr/bin/env python3
"""Local-only Shorts Studio. Credentials and production files remain on this Mac."""
import base64
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'out'
UI = ROOT / 'studio'
PORT = int(os.environ.get('SHORTS_STUDIO_PORT', '8787'))
LOCK = threading.RLock()
STATE = {'running': False, 'log': '', 'project': None, 'returncode': None}
def read(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default

CATALOG = read(ROOT / 'config/model_catalog.json', {})
MODELS = {
    entry['model']: {
        'name': {
            'wan3': 'Wan 3',
            'wan22_fast': 'Wan 2.2 Fast',
            'wan27_videoedit': 'Wan 2.7 VideoEdit',
            'wan22_animate': 'Wan 2.2 Animate',
        }.get(key, entry['model']),
        'workflow': entry.get('workflow', 'scene_generation'),
        'capabilities': entry.get('capabilities', []),
        'inputs': entry.get('inputs', {}),
        'resolutions': entry['settings']['resolution'],
        'rates': {resolution: pricing['amount'] for resolution, pricing in entry.get('pricing', {}).items()},
        'unit': next(iter(entry.get('pricing', {'480p': {'unit': 'second'}}).values())).get('unit', 'second'),
        'fixed_duration': entry['settings']['duration_seconds'].get('fixed') if isinstance(entry['settings']['duration_seconds'], dict) else None,
        'min_duration': entry['settings']['duration_seconds'].get('min') if isinstance(entry['settings']['duration_seconds'], dict) else None,
        'max_duration': entry['settings']['duration_seconds'].get('max') if isinstance(entry['settings']['duration_seconds'], dict) else None,
        'default_resolution': entry.get('defaults', {}).get('resolution'),
        'catalog_id': key,
    }
    for key, entry in CATALOG.items()
}
# Keep the API usable if a checkout predates the catalog pricing metadata.
MODELS['alibaba/wan-3']['rates'] = {'480p': .05, '720p': .10, '1080p': .20}
MODELS['wan-video/wan-2.2-i2v-fast']['rates'] = {'480p': .05}
SCENE_MODELS = {key for key, model in MODELS.items() if model['workflow'] == 'scene_generation'}
REMIX_MODELS = {key: model for key, model in MODELS.items() if model['workflow'] in ('video_edit', 'motion_transfer')}

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)

def load_env():
    env = os.environ.copy()
    if (ROOT / '.env').is_file():
        for line in (ROOT / '.env').read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1); env.setdefault(k.strip(),v.strip().strip('\"\''))
    env['PYTHONUNBUFFERED']='1'
    return env

def project_path(identifier):
    if not re.fullmatch(r'out/[A-Za-z0-9_-]+', identifier):
        raise ValueError('Invalid project')
    path=(ROOT/identifier).resolve()
    if path.parent != OUT.resolve() or not (path/'beats.json').is_file():
        raise ValueError('Project not found')
    return path

DEFAULT_SETTINGS = {'model': 'alibaba/wan-3', 'resolution': '480p', 'duration': 4, 'budget': 2}


def settings(path):
    saved = read(path / 'studio.json', {})
    if not isinstance(saved, dict):
        return dict(DEFAULT_SETTINGS)
    model = MODELS.get(saved.get('model'))
    if not model or model['workflow'] != 'scene_generation':
        return dict(DEFAULT_SETTINGS)
    if saved.get('resolution') not in model['resolutions']:
        return dict(DEFAULT_SETTINGS)
    try:
        duration = int(saved.get('duration', DEFAULT_SETTINGS['duration']))
        budget = float(saved.get('budget', DEFAULT_SETTINGS['budget']))
    except (TypeError, ValueError):
        return dict(DEFAULT_SETTINGS)
    if not 2 <= duration <= 30 or not 0 < budget <= 100:
        return dict(DEFAULT_SETTINGS)
    if model['fixed_duration'] and duration != model['fixed_duration']:
        duration = model['fixed_duration']
    return {'model': saved['model'], 'resolution': saved['resolution'], 'duration': duration, 'budget': budget}

def media_url(path):
    return '/files/'+str(path.relative_to(ROOT)) if path.is_file() else None

def detail(path):
    data=read(path/'beats.json'); scenes=[]
    for beat in data.get('beats',[]):
        for shot in beat.get('shots',[]):
            sid=shot['shot_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+',sid): continue
            scenes.append({**shot,'narration':beat.get('narration',''), 'image':media_url(path/'keyframes'/f'{sid}.png'), 'video':media_url(path/'clips'/f'{sid}.mp4')})
    opts=settings(path)
    model=MODELS[opts['model']]
    cost=model['rates'][opts['resolution']]*(opts['duration'] if model['unit']=='second' else 1)
    return {'id':str(path.relative_to(ROOT)), 'name':data.get('project_name',path.name), 'topic':data.get('topic',''), 'scenes':scenes,'settings':opts,'estimate':round(sum(not s['video'] for s in scenes)*cost,2),'video':media_url(path/'final_captioned.mp4')}

def projects():
    result=[]
    for file in sorted(OUT.glob('*/beats.json')):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',file.parent.name): continue
        try: result.append(detail(file.parent))
        except (ValueError,KeyError,TypeError): continue
    return result

def start_job(path, action, shot_id=None):
    with LOCK:
        if STATE['running']: raise ValueError('A studio job is already running')
        # Existing command-line workers also own paid jobs; never duplicate them.
        active=subprocess.run(['pgrep','-f','[w]an_clips.py'],capture_output=True,text=True)
        if action=='generate' and active.returncode==0: raise ValueError('A video generation process is already running. Wait for it to finish before retrying.')
        info=detail(path); opts=info['settings']; workpath=path
        scene_model = MODELS.get(opts['model'])
        if not scene_model or scene_model['workflow'] != 'scene_generation':
            raise ValueError('Choose a scene-generation model in project settings')
        target=next((s for s in info['scenes'] if s['shot_id']==shot_id),None)
        if shot_id and not target: raise ValueError('Unknown scene')
        if target:
            info['estimate']=scene_model['rates'][opts['resolution']]*(opts['duration'] if scene_model['unit']=='second' else 1)
            info['scenes']=[dict(target,video=None)]
        if action=='generate':
            if not any(not s['video'] for s in info['scenes']): raise ValueError('All scenes already have clips')
            if any(not s['scene_description'].strip() for s in info['scenes'] if not s['video']): raise ValueError('Add a prompt for every unfinished scene first')
            if scene_model['inputs'].get('start_frame', {}).get('required') and any(not s['image'] for s in info['scenes'] if not s['video']): raise ValueError('This model needs a portrait start frame for every unfinished scene')
            if info['estimate']>opts['budget']: raise ValueError('Estimated cost exceeds your budget cap')
            if not load_env().get('REPLICATE_API_TOKEN'): raise ValueError('Replicate token is missing from the local .env file')
        elif any(not s['video'] for s in info['scenes']): raise ValueError('Generate every scene before building the final video')
        jid=uuid.uuid4().hex
        if target:
            workpath=path/'versions'/jid
            document=read(path/'beats.json')
            document['beats']=[dict(b,shots=[s for s in b['shots'] if s['shot_id']==shot_id]) for b in document['beats'] if any(s['shot_id']==shot_id for s in b['shots'])]
            save(workpath/'beats.json',document)
            (workpath/'keyframes').mkdir()
            source_frame=path/'keyframes'/f'{shot_id}.png'
            if source_frame.is_file(): shutil.copy2(source_frame,workpath/'keyframes'/f'{shot_id}.png')
        STATE.update(running=True,project=info['id'],log='Starting '+action+'…',returncode=None,action=action,id=jid)
    def worker():
        env=load_env(); env.update(WAN_MODEL=opts['model'],WAN_DURATION_SECONDS=str(opts['duration']),WAN_RESOLUTION=opts['resolution'])
        python=str(ROOT/'venv/bin/python') if (ROOT/'venv/bin/python').exists() else sys.executable
        steps=([['run_manifest.py',str(workpath),'--model',opts['catalog_id'],'--resolution',opts['resolution'],'--duration',str(opts['duration']),'--aspect-ratio','9:16'],['wan_clips.py',str(workpath),'--max-cost-usd',str(opts['budget']),'--yes']] if action=='generate' else [[s,str(path)]+(['--captions'] if s=='finish_local.py' else []) for s in ['local_tts.py','local_captions.py','assemble.py','finish_local.py','quality_gate.py']])
        lines=[]; code=1
        try:
            for step in steps:
                proc=subprocess.Popen([python,'-u',str(ROOT/'scripts'/step[0]),*step[1:]],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
                for line in proc.stdout:
                    for key in ('REPLICATE_API_TOKEN','OPENAI_API_KEY'):
                        if env.get(key): line=line.replace(env[key],'[redacted]')
                    lines.append(line.rstrip())
                    with LOCK: STATE['log']='\n'.join(lines[-120:])
                code=proc.wait()
                if code: break
            if code==0 and target:
                replacement=workpath/'clips'/f'{shot_id}.mp4'
                if not replacement.is_file() or not replacement.stat().st_size: raise ValueError('Generated clip is missing')
                destination=path/'clips'/f'{shot_id}.mp4'; destination.parent.mkdir(exist_ok=True)
                if destination.exists(): shutil.copy2(destination,workpath/'previous.mp4')
                shutil.copy2(replacement,destination)
                lines.append('Scene replaced. Previous clip retained in versions/'+jid)
        except Exception as exc: code=1; lines.append(str(exc))
        finally:
            with LOCK:
                STATE.update(running=False,returncode=code,log='\n'.join(lines[-120:]))
                save(path/'jobs'/f'{jid}.json',dict(STATE,finished_at=time.time()))
    threading.Thread(target=worker,daemon=True).start()


def start_remix(path, shot_id, model_id, prompt, reference, resolution=None, duration=None):
    """Run a video-edit or motion-transfer model against one existing scene."""
    with LOCK:
        if STATE['running']:
            raise ValueError('A studio job is already running')
        active = subprocess.run(['pgrep', '-f', '[r]eplicate_remix.py'], capture_output=True, text=True)
        if active.returncode == 0:
            raise ValueError('A remix process is already running. Wait for it to finish before retrying.')
        model = REMIX_MODELS.get(model_id)
        if not model:
            raise ValueError('Unsupported remix model')
        info = detail(path)
        target = next((scene for scene in info['scenes'] if scene['shot_id'] == shot_id), None)
        if not target or not target.get('video'):
            raise ValueError('Remix needs an existing scene clip')
        if model['workflow'] == 'video_edit' and not str(prompt or '').strip():
            raise ValueError('Wan 2.7 VideoEdit needs an editing instruction')
        if model['workflow'] == 'motion_transfer' and not reference:
            raise ValueError('Wan 2.2 Animate needs a character image')
        resolution = resolution or model['default_resolution'] or model['resolutions'][0]
        if resolution not in model['resolutions']:
            raise ValueError('Unsupported remix resolution')
        duration = int(duration or target.get('duration_sec', info['settings']['duration']))
        if model['fixed_duration']:
            duration = model['fixed_duration']
        if model['min_duration'] and not model['min_duration'] <= duration <= model['max_duration']:
            raise ValueError(f'Remix duration must be {model["min_duration"]}–{model["max_duration"]} seconds')
        estimate = model['rates'][resolution] * (duration if model['unit'] == 'second' else 1)
        if estimate > info['settings']['budget']:
            raise ValueError(f'Estimated remix cost ${estimate:.3f} exceeds this project’s budget cap')
        if not load_env().get('REPLICATE_API_TOKEN'):
            raise ValueError('Replicate token is missing from the local .env file')

        jid = uuid.uuid4().hex
        workpath = path / 'versions' / jid
        document = read(path / 'beats.json')
        document['beats'] = [
            dict(beat, shots=[shot for shot in beat.get('shots', []) if shot.get('shot_id') == shot_id])
            for beat in document.get('beats', [])
            if any(shot.get('shot_id') == shot_id for shot in beat.get('shots', []))
        ]
        save(workpath / 'beats.json', document)
        source = path / 'clips' / f'{shot_id}.mp4'
        shutil.copy2(source, workpath / 'source.mp4')
        reference_path = None
        if reference:
            reference_path = workpath / 'reference.png'
            try:
                from PIL import Image
                with Image.open(io.BytesIO(reference)) as image:
                    image.load()
                    image.convert('RGB').save(reference_path)
            except ImportError as exc:
                raise ValueError('Install Pillow before using a character reference') from exc
            except Exception as exc:
                raise ValueError('Character reference must be a valid image') from exc
        STATE.update(
            running=True, project=info['id'], log=f'Starting {model["name"]}…',
            returncode=None, action='remix', id=jid, model=model_id,
        )

    def worker():
        env = load_env()
        python = str(ROOT / 'venv/bin/python') if (ROOT / 'venv/bin/python').exists() else sys.executable
        args = [
            python, '-u', str(ROOT / 'scripts/replicate_remix.py'), str(workpath),
            '--shot', shot_id, '--model', model_id, '--source-video', str(workpath / 'source.mp4'),
            '--resolution', resolution, '--duration', str(duration),
            '--max-cost-usd', str(info['settings']['budget']), '--yes',
        ]
        if prompt:
            args.extend(['--prompt', str(prompt)[:5000]])
        if reference_path:
            args.extend(['--reference-image', str(reference_path)])
        lines = []
        code = 1
        try:
            proc = subprocess.Popen(
                args, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
            )
            for line in proc.stdout:
                for key in ('REPLICATE_API_TOKEN', 'OPENAI_API_KEY'):
                    if env.get(key):
                        line = line.replace(env[key], '[redacted]')
                lines.append(line.rstrip())
                with LOCK:
                    STATE['log'] = '\n'.join(lines[-120:])
            code = proc.wait()
            if code == 0:
                replacement = workpath / 'clips' / f'{shot_id}.mp4'
                if not replacement.is_file() or not replacement.stat().st_size:
                    raise ValueError('Remix output is missing')
                destination = path / 'clips' / f'{shot_id}.mp4'
                if destination.exists():
                    shutil.copy2(destination, workpath / 'previous.mp4')
                shutil.copy2(replacement, destination)
                lines.append('Remix applied. Previous clip retained in versions/' + jid)
        except Exception as exc:
            code = 1
            lines.append(str(exc))
        finally:
            with LOCK:
                STATE.update(running=False, returncode=code, log='\n'.join(lines[-120:]))
                save(path / 'jobs' / f'{jid}.json', dict(STATE, finished_at=time.time()))

    threading.Thread(target=worker, daemon=True).start()

class Handler(BaseHTTPRequestHandler):
    def send_json(self,data,status=200):
        body=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        try:
            url=urlparse(self.path); path=unquote(url.path)
            if path=='/api/projects': return self.send_json({'projects':projects(),'models':MODELS,'connected':bool(load_env().get('REPLICATE_API_TOKEN'))})
            if path=='/api/status':
                with LOCK: return self.send_json(dict(STATE))
            if path=='/api/history':
                rows=[read(p) for p in OUT.glob('*/jobs/*.json')]
                return self.send_json(sorted(rows,key=lambda r:r.get('finished_at',0),reverse=True))
            if path.startswith('/files/'):
                target=(ROOT/path[7:]).resolve()
                if not target.is_relative_to(OUT.resolve()) or target.suffix.lower() not in ('.mp4','.png','.jpg','.jpeg','.wav','.aiff','.srt'): return self.send_error(404)
            else:
                target=UI/({'/':'index.html','/app.js':'app.js','/style.css':'style.css'}.get(path,'missing'))
            if not target.is_file(): return self.send_error(404)
            size=target.stat().st_size; start=0; end=size-1
            partial=self.headers.get('Range')
            if partial:
                match=re.fullmatch(r'bytes=(\d+)-(\d*)',partial)
                if not match: return self.send_error(416)
                start=int(match[1]); end=min(int(match[2]) if match[2] else end,end)
                if start>end: return self.send_error(416)
            self.send_response(206 if partial else 200); self.send_header('Content-Type',mimetypes.guess_type(str(target))[0] or 'application/octet-stream'); self.send_header('Accept-Ranges','bytes'); self.send_header('Content-Length',str(end-start+1)); self.send_header('X-Content-Type-Options','nosniff')
            if partial: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with target.open('rb') as stream:
                stream.seek(start); remaining=end-start+1
                while remaining:
                    block=stream.read(min(65536,remaining))
                    if not block: break
                    self.wfile.write(block); remaining-=len(block)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception as exc: self.send_json({'error':str(exc)},400)

    def do_POST(self):
        try:
            if self.headers.get('Origin') not in (None,f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'): raise ValueError('Invalid origin')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': raise ValueError('JSON request required')
            size=int(self.headers.get('Content-Length','0'))
            if size>15_000_000: raise ValueError('File too large; maximum 10 MB')
            data=json.loads(self.rfile.read(size)); action=urlparse(self.path).path
            with LOCK:
                if action=='/api/create':
                    name=str(data.get('name','')).strip()[:100]
                    if not name: raise ValueError('Give your project a name')
                    count=int(data.get('count',10))
                    if not 1<=count<=30: raise ValueError('Choose 1–30 scenes')
                    prompt=str(data.get('prompt','')).strip()[:5000]
                    slug=re.sub('[^a-z0-9]+','_',name.lower()).strip('_')[:50] or 'story'
                    path=OUT/(slug+'_'+uuid.uuid4().hex[:6])
                    save(path/'beats.json',{'project_name':name,'topic':name,'aspect_ratio':'9:16','beats':[{'beat_id':f'beat_{i}','narration':'','shots':[{'shot_id':f'beat_{i}_a','scene_description':prompt if i==1 else '','camera_move':'slow push in','duration_sec':4}]} for i in range(1,count+1)]})
                    return self.send_json(detail(path))
                path=project_path(data.get('project',''))
                if STATE['running'] and STATE['project']==data['project']: raise ValueError('Wait for this project’s current job before editing')
                if action=='/api/settings':
                    incoming=data['settings']; model=MODELS.get(incoming.get('model'))
                    if not model or model['workflow'] != 'scene_generation' or incoming.get('resolution') not in model['resolutions']: raise ValueError('Unsupported model settings')
                    duration=int(incoming['duration']); budget=float(incoming['budget'])
                    if not 2<=duration<=30 or (model['fixed_duration'] and duration!=model['fixed_duration']) or not 0<budget<=100: raise ValueError('Invalid duration or budget')
                    opts={'model':incoming['model'],'resolution':incoming['resolution'],'duration':duration,'budget':budget}
                    save(path/'studio.json',opts)
                elif action=='/api/scene':
                    document=read(path/'beats.json'); found=False
                    for beat in document['beats']:
                        for shot in beat['shots']:
                            if shot['shot_id']==data['shot']:
                                shot['scene_description']=str(data['prompt'])[:5000]; shot['camera_move']=str(data.get('camera','slow push in'))[:100]; beat['narration']=str(data['narration'])[:2000]; found=True
                    if not found: raise ValueError('Unknown scene')
                    save(path/'beats.json',document)
                elif action=='/api/upload':
                    sid=data.get('shot')
                    if sid not in [s['shot_id'] for s in detail(path)['scenes']]: raise ValueError('Unknown scene')
                    from PIL import Image
                    raw=base64.b64decode(data['content'],validate=True)
                    if len(raw)>10_000_000: raise ValueError('Maximum 10 MB')
                    with Image.open(io.BytesIO(raw)) as img:
                        if img.width>=img.height: raise ValueError('Choose a portrait image for this Short')
                        img.load(); dest=path/'keyframes'/f'{sid}.png'; dest.parent.mkdir(exist_ok=True)
                        if dest.exists(): dest.rename(dest.with_name(f'{sid}.{time.time_ns()}.png'))
                        img.convert('RGB').save(dest)
                elif action=='/api/reuse':
                    sid=data.get('shot')
                    if sid not in [s['shot_id'] for s in detail(path)['scenes']]: raise ValueError('Unknown scene')
                    source=project_path(data['source_project'])/'keyframes'/(data['source_shot']+'.png')
                    if data['source_shot'] not in [s['shot_id'] for s in detail(project_path(data['source_project']))['scenes']]: raise ValueError('Unknown source scene')
                    if not source.is_file(): raise ValueError('Source frame missing')
                    dest=path/'keyframes'/f'{sid}.png'; dest.parent.mkdir(exist_ok=True)
                    if source.resolve()!=dest.resolve():
                        if dest.exists(): dest.rename(dest.with_name(f'{sid}.{time.time_ns()}.png'))
                        shutil.copy2(source,dest)
                elif action=='/api/remix':
                    encoded=data.get('reference')
                    reference = None
                    if encoded:
                        try:
                            reference = base64.b64decode(encoded, validate=True)
                        except (ValueError, TypeError) as exc:
                            raise ValueError('Invalid character reference image') from exc
                        if len(reference) > 10_000_000:
                            raise ValueError('Character reference must be smaller than 10 MB')
                    start_remix(
                        path, data.get('shot'), data.get('model'), data.get('prompt', ''), reference,
                        data.get('resolution'), data.get('duration'),
                    )
                elif action in ('/api/run','/api/assemble'): start_job(path,'generate' if action=='/api/run' else 'assemble',data.get('shot') if action=='/api/run' else None)
                else: return self.send_error(404)
            self.send_json({'ok':True})
        except Exception as exc: self.send_json({'error':str(exc)},400)

    def log_message(self,*_): pass

if __name__=='__main__':
    print(f'Shorts Studio: http://127.0.0.1:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
