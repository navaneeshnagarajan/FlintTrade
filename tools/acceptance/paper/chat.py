"""One owned custom-chat protocol reply, never model inference."""

import sys
from paths import artifacts
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import threading

MODEL='r84-inert-signal'
class Chat:
    def __init__(self, desk, variant='positive'):
        self.desk,self.variant=desk,variant
        self.rows=[]
        os.environ.update(LLM_PROVIDER='custom',LLM_HOST='http://127.0.0.1:5178',LLM_MODEL=MODEL)
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def refuse(self, reason):
                desk.failures.append(['unregistered-chat',self.command,self.path,reason])
                self.send_error(500)
            def do_POST(self):
                if self.path!='/v1/chat/completions' or owner.rows:
                    self.refuse('path-or-duplicate'); return
                size=self.headers.get('Content-Length','')
                if not size.isdecimal() or not 1<=int(size)<=65536 or self.headers.get('Content-Type')!='application/json':
                    self.refuse('body-framing'); return
                raw=self.rfile.read(int(size))
                try:
                    body=json.loads(raw)
                    assert set(body)=={'model','messages','temperature','max_tokens','stream'}
                    assert body['model']==MODEL and body['max_tokens']==32 and body['stream'] is False
                    assert type(body['messages']) is list and body['messages']
                    assert all(set(m)=={'role','content'} and m['role'] in {'system','user'} and type(m['content']) is str and m['content'] for m in body['messages'])
                    assert type(body['temperature']) in {float,int} and 0<=body['temperature']<=2
                    assert self.headers.get('Host')=='127.0.0.1:5178'
                    assert not self.headers.get('Authorization') and not self.headers.get('Transfer-Encoding')
                    expected_headers={'host':'127.0.0.1:5178','accept':'*/*','accept-encoding':'gzip, deflate, br, zstd',
                        'connection':'keep-alive','user-agent':'python-httpx/0.28.1','content-type':'application/json',
                        'content-length':str(len(raw))}
                    assert {k.lower():v for k,v in self.headers.items()}==expected_headers
                    assert len(self.headers)==len(expected_headers)
                except Exception:
                    self.refuse('request-shape'); return
                value={'model':MODEL,'choices':[{'message':{'role':'assistant','content':'BUY'},'finish_reason':'stop'}],
                       'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
                if owner.variant=='empty-chat': value['choices'][0]['message']['content']=''
                if owner.variant=='malformed-chat': value={'choices':3}
                response=json.dumps(value,separators=(',',':')).encode()
                owner.rows.append({'method':self.command,'path':self.path,'headers':list(self.headers.items()),
                                   'request_base64':base64.b64encode(raw).decode(),'response_base64':base64.b64encode(response).decode(),
                                   'classification':'synthetic-protocol-response-and-usage-not-inference'})
                self.send_response(200); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(response))); self.end_headers(); self.wfile.write(response)
            def __getattr__(self,name):
                if name.startswith('do_'): return lambda:self.refuse('method')
                raise AttributeError(name)
            def log_message(self,*a): pass
        desk.allowed_ports.add(5178)
        self.server=HTTPServer(('127.0.0.1',5178),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,name='r84-chat-wire')
        self.thread.start()
    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=3)
        assert not self.thread.is_alive()
        (artifacts() / 'chat.json').write_text(json.dumps(self.rows,indent=2))
