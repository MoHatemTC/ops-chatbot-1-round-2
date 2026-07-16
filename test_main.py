import time
from fastapi.testclient import TestClient
import pytest
from main import app, rate_limit_store

client = TestClient(app)

def test_login_success():
    response = client.post("/login", data={"username": "ayman", "password": "anypassword"})
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_chat_stream_unauthorized():
    payload = {
        "message": "Hello",
        "thread_id": "session-123",
        "cohort_id": "alexandria-university-cohort-1"
    }
    response = client.post("/chat/stream", json=payload)
    assert response.status_code == 401

def test_chat_stream_forbidden_cohort():
    login_res = client.post("/login", data={"username": "ayman", "password": "anypassword"})
    token = login_res.json()["access_token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "message": "Hello",
        "thread_id": "session-123",
        "cohort_id": "wrong-cohort-id"
    }
    response = client.post("/chat/stream", json=payload, headers=headers)
    assert response.status_code == 403

def test_chat_stream_success():
    login_res = client.post("/login", data={"username": "ayman", "password": "anypassword"})
    token = login_res.json()["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "message": "Hello Bot",
        "thread_id": "session-123",
        "cohort_id": "alexandria-university-cohort-1"
    }
    response = client.post("/chat/stream", json=payload, headers=headers)
    assert response.status_code == 200
    assert "data:" in response.text
    assert "Stub" in response.text and "Response" in response.text

def test_rate_limiting():
    rate_limit_store.clear()
    login_res = client.post("/login", data={"username": "ayman", "password": "anypassword"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "message": "Hello",
        "thread_id": "session-123",
        "cohort_id": "alexandria-university-cohort-1"
    }
    
    for _ in range(10):
        response = client.post("/chat/stream", json=payload, headers=headers)
        assert response.status_code == 200
        
    response = client.post("/chat/stream", json=payload, headers=headers)
    assert response.status_code == 429