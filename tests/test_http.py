import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

class HTTPTests(unittest.TestCase):
    def test_signed_delivery_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as data:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
            env=dict(os.environ, DATA_DIR=data, PORT=str(port), WEBHOOK_SECRET='test-secret', REVIEWER_ID='123456', ALLOWED_REPOS='owner/repo')
            process=subprocess.Popen([sys.executable,'app.py','serve'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                    except OSError:time.sleep(.02)
                else:self.fail('server did not start')
                payload={'action':'review_requested','repository':{'id':1,'full_name':'owner/repo'},'requested_reviewer':{'id':123456},'pull_request':{'number':2,'state':'open','draft':False,'head':{'sha':'a'*40}}}
                raw=json.dumps(payload).encode()
                signature='sha256='+hmac.new(b'test-secret',raw,hashlib.sha256).hexdigest()
                def post(body, sig, path='/webhooks/github'):
                    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
                    conn.request('POST',path,body,{'X-Hub-Signature-256':sig,'X-GitHub-Delivery':'test-delivery','X-GitHub-Event':'pull_request'})
                    response=conn.getresponse(); code=response.status; response.read(); conn.close();return code
                self.assertEqual(401,post(raw,'sha256=wrong'))
                self.assertEqual(404,post(raw,signature,'/other'))
                self.assertEqual(202,post(raw,signature))
                self.assertEqual(202,post(raw,signature))
                conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
                conn.request('POST','/webhooks/github',b'',{'Content-Length':str(1024*1024+1)})
                response=conn.getresponse(); self.assertEqual(413,response.status);response.read();conn.close()
                import sqlite3
                with sqlite3.connect(Path(data)/'queue.sqlite3') as db:
                    self.assertEqual(1,db.execute('SELECT count(*) FROM jobs').fetchone()[0])
            finally:
                process.terminate();process.wait(timeout=5)
