import socket
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refused(*args, **kwargs): raise AssertionError("Provider unit tests must not call live services")
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
