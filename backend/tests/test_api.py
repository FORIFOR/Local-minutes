from fastapi.testclient import TestClient
from backend.main import app
import time


def test_event_crud_and_search(fake_models_env):
    c = TestClient(app)
    now = int(time.time())
    r = c.post('/api/events', json={"title":"テスト会議","start_ts":now, "lang":"ja"})
    assert r.status_code == 200
    eid = r.json()['id']
    r = c.get(f'/api/events/{eid}')
    assert r.status_code == 200
    r = c.get('/api/search', params={'q':'テスト'})
    assert r.status_code == 200


def test_downloads(fake_models_env):
    c = TestClient(app)
    now = int(time.time())
    eid = c.post('/api/events', json={"title":"DLテスト","start_ts":now, "lang":"ja"}).json()['id']
    assert c.get('/download.srt', params={'id':eid}).status_code == 200
    assert c.get('/download.vtt', params={'id':eid}).status_code == 200
    assert c.get('/download.rttm', params={'id':eid}).status_code == 200
    assert c.get('/download.ics', params={'id':eid}).status_code == 200

