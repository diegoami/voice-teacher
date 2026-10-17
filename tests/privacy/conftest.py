"""Reuse original synthetic voice fixtures and forbid provider network access."""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'integration'))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refused(*args, **kwargs): raise AssertionError('privacy tests must not call network providers')
    monkeypatch.setattr(socket.socket, 'connect', refused)
    monkeypatch.setattr(socket, 'create_connection', refused)
