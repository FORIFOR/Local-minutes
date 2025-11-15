from fastapi.testclient import TestClient
from backend.main import app


def test_healthz(fake_models_env):
    c = TestClient(app)
    r = c.get('/healthz')
    assert r.status_code == 200
    assert r.json()['ok'] is True


def test_ready_ok(fake_models_env):
    c = TestClient(app)
    r = c.get('/healthz/ready')
    j = r.json()
    assert r.status_code == 200
    assert j['ok'] is True
    names = {chk['name'] for chk in j['checks']}
    assert 'asr.dir' in names and 'llm.model' in names
