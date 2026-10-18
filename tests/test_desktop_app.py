import socket
import pytest
from fastapi.testclient import TestClient
import backend.main as main
from desktop_app import reserve_listener


def test_desktop_listener_is_exclusive_and_released():
    listener = reserve_listener(0)
    port = listener.getsockname()[1]
    with pytest.raises(RuntimeError, match='already open'):
        reserve_listener(port)
    listener.close()
    reopened = reserve_listener(port)
    reopened.close()


def test_desktop_origin_is_explicitly_allowed(monkeypatch):
    monkeypatch.setattr(main.app.state, 'desktop_origin', 'http://127.0.0.1:8765', raising=False)
    with TestClient(main.app) as client:
        # Validation response proves local request passed origin middleware without changing data.
        response = client.post('/tasks/search', json={}, headers={'origin':'http://127.0.0.1:8765'})
        assert response.status_code == 422
        assert client.post('/tasks/search', json={}, headers={'origin':'https://untrusted.example'}).status_code == 403
