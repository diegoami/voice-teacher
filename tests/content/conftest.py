import socket
import pytest


@pytest.fixture(autouse=True)
def offline_content(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("content adapter attempted network access")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
