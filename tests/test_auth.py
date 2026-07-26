import os
import pathlib

# Defina variáveis de ambiente necessárias antes de importar a aplicação
os.environ.setdefault('SECRET_KEY', 'test-secret-key-please-change')
os.environ.setdefault('DATABASE_URL', 'sqlite:///./test_db.sqlite')
os.environ.setdefault('ACCESS_TOKEN_EXPIRE_MINUTES', '60')

from fastapi.testclient import TestClient
import main


def setup_module(module):
    # garante que qualquer BD de teste antigo seja removido
    p = pathlib.Path('test_db.sqlite')
    if p.exists():
        p.unlink()


def teardown_module(module):
    p = pathlib.Path('test_db.sqlite')
    if p.exists():
        p.unlink()


def test_register_and_login_flow():
    client = TestClient(main.app)

    payload = {"email": "testuser@example.com", "password": "strongpassword", "role": "paciente"}
    resp = client.post('/auth/registrar', json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data['email'] == payload['email']
    assert data['role'] == payload['role']

    # agora tentar login via OAuth2 password flow
    login_data = {'username': payload['email'], 'password': payload['password']}
    resp = client.post('/auth/login', data=login_data)
    assert resp.status_code == 200, resp.text
    token = resp.json().get('access_token')
    assert token
