"""Local studio integration checks; never submit paid generation requests."""
import base64
import importlib.util
import io
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from PIL import Image

spec=importlib.util.spec_from_file_location('studio_server',Path(__file__).resolve().parents[1]/'scripts/studio_server.py')
studio=importlib.util.module_from_spec(spec); spec.loader.exec_module(studio)

class StudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(); studio.ROOT=Path(cls.temp.name).resolve(); studio.OUT=studio.ROOT/'out'
        cls.server=studio.ThreadingHTTPServer(('127.0.0.1',0),studio.Handler)
        studio.PORT=cls.server.server_port
        cls.base=f'http://127.0.0.1:{studio.PORT}'
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.temp.cleanup()
    def call(self,path,data=None,headers=None):
        request=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data else None,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with urllib.request.urlopen(request) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    def test_workflow(self):
        code,raw=self.call('/api/create',{'name':'Test story','count':2}); self.assertEqual(code,200)
        project=json.loads(raw); pid=project['id']; sid=project['scenes'][0]['shot_id']
        self.assertEqual(len(project['scenes']),2)
        code,_=self.call('/api/scene',{'project':pid,'shot':sid,'prompt':'Hotel arrival','narration':'He arrived at the hotel.','camera':'tracking'}); self.assertEqual(code,200)
        image=io.BytesIO(); Image.new('RGB',(90,160),'green').save(image,format='PNG')
        code,body=self.call('/api/upload',{'project':pid,'shot':sid,'content':base64.b64encode(image.getvalue()).decode()}); self.assertEqual(code,200,body)
        code,raw=self.call('/api/projects'); p=json.loads(raw)['projects'][0]
        self.assertEqual(p['scenes'][0]['scene_description'],'Hotel arrival'); self.assertTrue(p['scenes'][0]['image'])
        code,_=self.call('/api/settings',{'project':pid,'settings':{'model':'alibaba/wan-3','resolution':'720p','duration':4,'budget':2}}); self.assertEqual(code,200)
        _,raw=self.call('/api/projects'); self.assertEqual(json.loads(raw)['projects'][0]['estimate'],.8)
        code,_=self.call('/api/settings',{'project':pid,'settings':{'model':'wan-video/wan-2.2-i2v-fast','resolution':'480p','duration':4,'budget':2}}); self.assertEqual(code,400)
        code,_=self.call('/api/settings',{'project':pid,'settings':{'model':'wan-video/wan-2.2-i2v-fast','resolution':'480p','duration':5,'budget':2}}); self.assertEqual(code,200)
        _,raw=self.call('/api/projects'); self.assertEqual(json.loads(raw)['models']['wan-video/wan-2.2-i2v-fast']['fixed_duration'],5)
        models=json.loads(raw)['models']
        self.assertEqual(models['wan-video/wan-2.7-videoedit']['workflow'],'video_edit')
        self.assertEqual(models['wan-video/wan-2.2-animate-animation']['workflow'],'motion_transfer')
        code,_=self.call('/api/assemble',{'project':pid}); self.assertEqual(code,400)
        code,_=self.call('/api/settings',{'project':pid,'settings':{'model':'invalid','resolution':'480p','duration':4,'budget':2}}); self.assertEqual(code,400)
        code,raw=self.call('/api/create',{'name':'Prompt clip','count':1,'prompt':'A detective opens a hotel door as a red light blinks on a hidden camera.'}); self.assertEqual(code,200)
        prompt_project=json.loads(raw); self.assertEqual(prompt_project['scenes'][0]['scene_description'].startswith('A detective'),True)
        original_loader=studio.load_env; studio.load_env=lambda:{'PYTHONUNBUFFERED':'1'}
        try:
            code,_=self.call('/api/run',{'project':prompt_project['id'],'shot':prompt_project['scenes'][0]['shot_id']}); self.assertEqual(code,400)
        finally: studio.load_env=original_loader
        clip=studio.ROOT/pid/'clips'/f'{sid}.mp4'; clip.parent.mkdir(); clip.write_bytes(b'0123456789')
        code,_=self.call('/api/remix',{'project':pid,'shot':sid,'model':'wan-video/wan-2.2-animate-animation','resolution':'480','duration':4}); self.assertEqual(code,400)
        code,_=self.call('/api/remix',{'project':pid,'shot':sid,'model':'wan-video/wan-2.7-videoedit','resolution':'720p','duration':4}); self.assertEqual(code,400)
        code,_=self.call('/api/scene',{'project':'../escape'},headers={'Origin':'https://example.com'}); self.assertEqual(code,400)
        (studio.ROOT/'.env').write_text('SECRET=not-for-browser')
        code,_=self.call('/files/.env'); self.assertEqual(code,404)
        code,body=self.call('/files/'+str(clip.relative_to(studio.ROOT)),headers={'Range':'bytes=2-5'}); self.assertEqual((code,body),(206,b'2345'))

if __name__=='__main__':unittest.main()
