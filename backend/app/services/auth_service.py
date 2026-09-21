"""Password hashing/verification and login lookup for the per-user auth
layer (see models/user.py). No bcrypt/argon2 dependency - PBKDF2-HMAC-SHA256
from the stdlib is plenty for a handful of internal accounts, and keeps the
Docker image free of a compiled-extension dependency for this.
"""

import hashlib
import hmac
import os

from sqlalchemy.orm import Session

from app.models.user import User

_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt_hex, digest_hex = password_hash.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)


def authenticate(db: Session, login: str, password: str) -> User | None:
    """Returns the matching User on correct login+password, else None.

    Constant-time-ish w.r.t. wrong password (verify_password always runs the
    same hashing work); a nonexistent login short-circuits, which does leak
    login existence via timing - an accepted tradeoff for a handful of
    internal accounts, not worth a dummy-hash comparison here.
    """
    user = db.query(User).filter(User.login == login).one_or_none()
    if user is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
