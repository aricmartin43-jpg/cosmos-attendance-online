"""API rules tested with SQLite and isolated fake face/storage adapters, not live services."""
import base64
import io
import json
import os
import tempfile
from datetime import timedelta

import numpy as np
import pytest
from cryptography.fernet import Fernet
from PIL import Image

os.environ['APP_ENV'] = 'development'
os.environ['DATABASE_URL'] = 'sqlite:///' + tempfile.mktemp(suffix='.db')
os.environ['SECRET_KEY'] = 'test-secret-' * 8
os.environ['FACE_ENCRYPTION_KEY'] = Fernet.generate_key().decode()
os.environ['ADMIN_PASSWORD'] = 'testing-admin-password'
import app as module
from init_db import initialise


@pytest.fixture(autouse=True)
def database(monkeypatch):
    module.Base.metadata.drop_all(module.engine)
    initialise()
    module.app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    module.limiter.enabled = False
    monkeypatch.setattr(module, 'face_image', lambda value: (np.zeros(128), b'fake-photo'))
    monkeypatch.setattr(module, 'upload_photo', lambda value: 'private-photo-id')
    monkeypatch.setattr(module, 'remove_photo', lambda value: None)


def client(code='admin', password='testing-admin-password'):
    c = module.app.test_client()
    token = c.get('/api/session').json['csrf']
    response = c.post('/api/login', json=dict(code=code, password=password), headers={'X-CSRF-Token':token})
    assert response.status_code == 200
    c.csrf = response.json['csrf']
    return c


def post(c, path, data):
    return c.post(path, json=data, headers={'X-CSRF-Token':c.csrf})


def employee(admin, code='ces001', name='Test Employee'):
    r = post(admin, '/api/employees', dict(code=code, name=name, department='Production', pin='1234'))
    assert r.status_code == 201
    assert post(admin, f'/api/employees/{r.json["id"]}/enrol', dict(photo='fake', consent=True)).status_code == 200
    return client(code, '1234'), r.json['id']


def attendance(c, action='in', **overrides):
    challenge = post(c, '/api/capture', {}).json['challenge']
    data = dict(action=action, challenge=challenge, photo='fake', location=dict(lat=11.01,lng=76.96,accuracy=12,timestamp=module.now().timestamp()*1000))
    data.update(overrides)
    return post(c, '/api/attendance', data)


def test_authentication_csrf_and_roles():
    c = module.app.test_client()
    assert c.get('/api/employees').status_code == 401
    assert c.post('/api/login', json={}).status_code == 403
    admin = client()
    worker, eid = employee(admin)
    assert worker.get('/api/employees').status_code == 403
    assert worker.get('/api/export?month=2026-09').status_code == 403
    assert post(worker, f'/api/employees/{eid}/enrol', dict(photo='fake',consent=True)).status_code == 403


def test_shift_rules_and_record_isolation():
    admin = client()
    worker, _ = employee(admin)
    other, _ = employee(admin, 'ces002')
    assert attendance(worker, 'out').status_code == 409
    assert attendance(worker).status_code == 201
    assert attendance(worker).status_code == 409
    assert len(other.get('/api/attendance').json) == 0
    assert attendance(worker, 'out').status_code == 201
    assert attendance(worker).status_code == 409
    row = worker.get('/api/attendance').json[0]
    assert row['hours'] >= 0 and row['out_location']['accuracy'] == 12
    assert 'in_photo' not in row and 'encoding' not in row


def test_face_mismatch_and_gps_validation(monkeypatch):
    worker, _ = employee(client())
    for location in ({}, dict(lat=float('nan'),lng=10,accuracy=1,timestamp=1), dict(lat=11,lng=76,accuracy=10,timestamp=1)):
        assert attendance(worker, location=location).status_code == 400
    monkeypatch.setattr(module, 'face_image', lambda value:(np.ones(128),b'photo'))
    assert attendance(worker).status_code == 403
    assert worker.get('/api/attendance').json == []


def test_failed_storage_does_not_create_attendance(monkeypatch):
    worker, _ = employee(client())
    def failed(_): raise RuntimeError('Simulated Cloudinary outage')
    monkeypatch.setattr(module, 'upload_photo', failed)
    assert attendance(worker).status_code == 503
    assert worker.get('/api/attendance').json == []


def test_overnight_checkout(monkeypatch):
    worker, _ = employee(client())
    start = module.datetime(2026,9,15,17,0,tzinfo=module.UTC)
    monkeypatch.setattr(module, 'now', lambda:start)
    assert attendance(worker).status_code == 201
    monkeypatch.setattr(module, 'now', lambda:start + timedelta(hours=8))
    assert worker.get('/api/my-status').json['open_shift']['date'] == '2026-09-15'
    result = attendance(worker, 'out')
    assert result.status_code == 201 and result.json['hours'] == 8
    assert result.json['date'] == '2026-09-15'


def test_export_formula_safety_and_dates():
    admin = client()
    worker, _ = employee(admin, name='=HYPERLINK("bad")')
    assert attendance(worker).status_code == 201
    month = module.now().astimezone(module.LOCAL).strftime('%Y-%m')
    csv = admin.get('/api/export?month='+month)
    assert csv.status_code == 200 and "'=HYPERLINK" in csv.text
    assert admin.get('/api/export?month=2026-99').status_code == 400


def test_consent_deactivation_and_encrypted_templates():
    admin = client()
    worker, eid = employee(admin)
    assert post(admin, f'/api/employees/{eid}/enrol',dict(photo='fake',consent=False)).status_code == 400
    with module.DB() as db:
        encrypted = db.get(module.Employee,eid).encoding
        assert not encrypted.startswith('[')
        assert len(json.loads(module.CIPHER.decrypt(encrypted.encode()))) == 128
    assert attendance(worker).status_code == 201
    assert post(admin, f'/api/employees/{eid}/active',dict(active=False)).status_code == 409
    assert attendance(worker,'out').status_code == 201
    assert post(admin, f'/api/employees/{eid}/active',dict(active=False)).status_code == 200
    assert worker.get('/api/attendance').status_code == 401


def test_successful_challenge_cannot_be_replayed():
    worker, _ = employee(client())
    challenge = post(worker,'/api/capture',{}).json['challenge']
    data=dict(action='in',challenge=challenge,photo='fake',location=dict(lat=11,lng=76,accuracy=2,timestamp=module.now().timestamp()*1000))
    assert post(worker,'/api/attendance',data).status_code == 201
    data['action']='out'
    assert post(worker,'/api/attendance',data).status_code == 400


def test_pages_and_security_headers():
    c=module.app.test_client()
    response=c.get('/')
    assert response.status_code == 200 and 'Cosmos Attendance' in response.text
    assert response.headers['X-Frame-Options'] == 'DENY'
    for path in ('/static/app.js','/static/style.css','/static/favicon.svg'):
        assert c.get(path).status_code == 200
