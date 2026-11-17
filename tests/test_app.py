import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import app

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = SimpleNamespace(reviewer=123456, repos={'owner/repo'}, data=Path(self.tmp.name), token='fake')
        self.q = app.Queue(self.cfg.data)
        self.payload = {'action':'review_requested', 'repository':{'id':1,'full_name':'owner/repo'},
                        'requested_reviewer':{'id':123456}, 'pull_request':{'number':2, 'head':{'sha':'a'*40},'state':'open','draft':False}}
        self.job = app.select_job('pull_request',self.payload,self.cfg)
    def tearDown(self):
        self.q.db.close(); self.tmp.cleanup()
    def test_signature_raw_bytes(self):
        raw=b'{"a":1}'
        sig='sha256='+hmac.new(b'secret',raw,hashlib.sha256).hexdigest()
        self.assertTrue(app.authenticate('secret',raw,sig))
        self.assertFalse(app.authenticate('secret',raw+b' ',sig))
        self.assertFalse(app.authenticate('',raw,sig))
    def test_filter(self):
        for event in ['push','ping']:
            self.assertIsNone(app.select_job(event,self.payload,self.cfg))
        self.payload['action']='assigned'
        self.assertIsNone(app.select_job('pull_request',self.payload,self.cfg))
        self.payload['action']='review_requested'; self.payload['requested_reviewer']['id']=12
        self.assertIsNone(app.select_job('pull_request',self.payload,self.cfg))
    def test_repo_allowlist_and_draft(self):
        self.cfg.repos=set()
        self.assertIsNone(app.select_job('pull_request',self.payload,self.cfg))
        self.cfg.repos={'owner/repo'}; self.payload['pull_request']['draft']=True
        self.assertIsNone(app.select_job('pull_request',self.payload,self.cfg))
    def test_validation(self):
        for number in [True,0,-1,'2']:
            self.payload['pull_request']['number']=number
            with self.assertRaises(ValueError): app.select_job('pull_request',self.payload,self.cfg)
    def test_dedupe(self):
        a=self.q.admit('delivery-a',self.job)
        self.assertEqual(a,self.q.admit('delivery-a',self.job))
        self.assertEqual(a,self.q.admit('delivery-b',self.job))
        self.assertEqual(1,self.q.db.execute('SELECT count(*) FROM jobs').fetchone()[0])
        other=dict(self.job,sha='b'*40)
        with self.assertRaises(ValueError):self.q.admit('delivery-a',other)
        self.assertEqual(1,self.q.db.execute('SELECT count(*) FROM jobs').fetchone()[0])
    def test_durable_claim_lease(self):
        self.q.admit('a',self.job)
        self.q.db.close(); self.q=app.Queue(self.cfg.data)
        first=self.q.claim(); self.assertIsNotNone(first)
        self.assertIsNone(self.q.claim())
        self.q.db.execute('UPDATE jobs SET lease=0')
        self.assertEqual(first['id'],self.q.claim()['id'])
    def test_retry_limit(self):
        self.q.admit('a',self.job)
        for _ in range(3):
            job=self.q.claim(); self.q.retry(job,'test')
            self.q.db.execute('UPDATE jobs SET available=0')
        self.assertEqual('failed',self.q.db.execute('SELECT status FROM jobs').fetchone()[0])
        self.assertIsNone(self.q.claim())
    def test_private_draft(self):
        self.q.admit('a',self.job)
        api=SimpleNamespace(current=lambda *a:True,context=lambda *a:'[]')
        self.assertTrue(app.work_once(self.q,self.cfg,api,lambda *a:'No supported bugs.'))
        draft=json.loads((self.cfg.data/'draft-1.json').read_text())
        self.assertEqual('a'*40,draft['commit_id']);self.assertFalse(draft['published'])
        self.assertEqual('drafted',self.q.db.execute('SELECT status FROM jobs').fetchone()[0])
    def test_sha_changes_during_review(self):
        self.q.admit('a',self.job); states=iter([True,False])
        api=SimpleNamespace(current=lambda *a:next(states),context=lambda *a:'[]')
        app.work_once(self.q,self.cfg,api,lambda *a:'review')
        self.assertFalse((self.cfg.data/'draft-1.json').exists())
        self.assertEqual('stale',self.q.db.execute('SELECT status FROM jobs').fetchone()[0])
    def test_stale_before_agent(self):
        self.q.admit('a',self.job)
        api=SimpleNamespace(current=lambda *a:False)
        def unexpected(*a):self.fail('agent should not run')
        app.work_once(self.q,self.cfg,api,unexpected)
        self.assertEqual('stale',self.q.db.execute('SELECT status FROM jobs').fetchone()[0])
    def test_exception_redacted(self):
        self.q.admit('a',self.job)
        def fail(*a):raise RuntimeError('secret token')
        api=SimpleNamespace(current=fail)
        app.work_once(self.q,self.cfg,api)
        self.assertEqual('RuntimeError',self.q.db.execute('SELECT error FROM jobs').fetchone()[0])
    def test_worker_rechecks_allowlist(self):
        self.q.admit('a',self.job); self.cfg.repos=set()
        app.work_once(self.q,self.cfg,SimpleNamespace())
        self.assertEqual('stale',self.q.db.execute('SELECT status FROM jobs').fetchone()[0])

if __name__=='__main__':unittest.main()
