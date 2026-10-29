"""Loopback GUI fixture for real-browser acceptance; no cookies or account data.

Run with an output directory argument. Read ready.json for its URL and events.json
for effects observed by the fixture, independently of the browser tool's replies.
"""
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
import threading


def main(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    events = {}
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            match = re.fullmatch(r'/event/([a-z0-9-]{1,48})/(increment|confirm|prompt)', self.path)
            if not match:
                self.send_error(404)
                return
            name, event = match.groups()
            with lock:
                key = name + ':' + event
                events[key] = events.get(key, 0) + 1
                temp = folder / 'events.tmp'
                temp.write_text(json.dumps(events, sort_keys=True))
                temp.replace(folder / 'events.json')
            self.send_response(204)
            self.end_headers()

        def do_GET(self):
            name = self.path.strip('/')
            if not re.fullmatch(r'[a-z0-9-]{1,48}', name):
                self.send_error(404)
                return
            source = '''<!doctype html><meta charset="utf-8">
<title>Hermes browser fixture NAME</title>
<style>body{font:20px system-ui;margin:40px}button,input{font:inherit;margin:12px;padding:12px}</style>
<h1>Fixture NAME</h1><p id="count">Count: 0</p>
<button id="inc">Increment once</button>
<label>Test input <input id="entry" autocomplete="off"></label><p id="typed">Typed: </p>
<button id="confirm">Open confirmation</button><p id="decision">Decision: pending</p>
<button id="prompt">Open prompt</button><p id="answer">Answer: pending</p>
<button id="popup">Open owned popup</button>
<script>
const fixture=FIXTURE;let count=0;
const record=event=>fetch('/event/'+fixture+'/'+event,{method:'POST'});
document.querySelector('#inc').onclick=()=>{count++;document.querySelector('#count').textContent='Count: '+count;record('increment');};
document.querySelector('#entry').oninput=e=>{document.querySelector('#typed').textContent='Typed: '+e.target.value;};
document.querySelector('#confirm').onclick=()=>{const yes=confirm('Hermes test '+fixture);document.querySelector('#decision').textContent='Decision: '+(yes?'yes':'no');record('confirm');};
document.querySelector('#prompt').onclick=()=>{const answer=prompt('Hermes test input '+fixture,'');document.querySelector('#answer').textContent='Answer: '+answer;record('prompt');};
document.querySelector('#popup').onclick=()=>window.open('/'+fixture+'-popup','_blank');
</script>'''.replace('FIXTURE', json.dumps(name)).replace('NAME', html.escape(name))
            body = source.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    (folder / 'ready.json').write_text(json.dumps({'url': f'http://127.0.0.1:{server.server_port}'}))
    (folder / 'events.json').write_text('{}')
    print('Local GUI fixture ready', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main(sys.argv[1])
