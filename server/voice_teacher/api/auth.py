"""Hashed, learner-bound bearer grants; pairing is operator initiated."""
from dataclasses import dataclass
import hashlib
import math
import secrets
import time
from uuid import uuid4

from ..storage.sqlite import _id


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    learner_id: str | None
    operator: bool = False


class Auth:
    def __init__(self, store, operator_token, *, clock=time.time, code_ttl=300, client_ttl=30 * 86400):
        if not isinstance(operator_token, str) or len(operator_token) < 32:
            raise ValueError("operator token must have at least 32 characters")
        if any(type(v) not in {int, float} or not math.isfinite(v) for v in (code_ttl, client_ttl)) or not 0 < code_ttl <= 600 or not 0 < client_ttl <= 365 * 86400:
            raise ValueError("invalid pairing/client lifetime")
        self.store, self.operator_hash, self.clock = store, digest(operator_token), clock
        self.code_ttl, self.client_ttl = code_ttl, client_ttl

    def authenticate(self, token):
        if not isinstance(token, str) or not 32 <= len(token) <= 256: return None
        hashed = digest(token)
        if secrets.compare_digest(hashed, self.operator_hash): return Principal(None, True)
        with self.store._connection() as c:
            row = c.execute("SELECT learner_id FROM clients WHERE token_hash=? AND revoked=0 AND expires>?", (hashed, self.clock())).fetchone()
            return Principal(row[0]) if row is not None else None

    def issue_code(self, learner, label):
        self.store.learner(learner)
        code, expires = secrets.token_urlsafe(32), self.clock() + self.code_ttl
        with self.store._transaction() as c:
            c.execute("DELETE FROM pairing_codes WHERE expires<=?", (self.clock(),))
            c.execute("INSERT INTO pairing_codes VALUES (?,?,?,?)", (digest(code), _id(learner), label, expires))
        return {"code": code, "expires_at": expires}

    def pair(self, code):
        if not isinstance(code, str) or not 32 <= len(code) <= 256: return None
        token, client = secrets.token_urlsafe(32), str(uuid4())
        expires = self.clock() + self.client_ttl
        with self.store._transaction() as c:
            row = c.execute("DELETE FROM pairing_codes WHERE code_hash=? AND expires>? RETURNING learner_id,label", (digest(code), self.clock())).fetchone()
            if row is None: return None
            c.execute("INSERT INTO clients(token_hash,client_id,learner_id,label,expires) VALUES (?,?,?,?,?)", (digest(token), client, row[0], row[1], expires))
        return {"token": token, "client_id": client, "expires_at": expires, "learner_id": row[0]}

    def revoke(self, client):
        with self.store._transaction() as c:
            c.execute("UPDATE clients SET revoked=1 WHERE client_id=?", (_id(client),))
