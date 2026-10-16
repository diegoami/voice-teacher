import socket
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refused(*args, **kwargs): raise AssertionError("API tests must not use a network provider")
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
