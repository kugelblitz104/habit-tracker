"""Symmetric encryption for secrets stored at rest (integration PATs).

Uses Fernet (AES-128-CBC + HMAC). The key comes from
``settings.integration_encryption_key`` when set; otherwise it is derived
deterministically from ``settings.secret_key`` so local dev works with no extra
configuration. Deriving from ``secret_key`` means rotating that value
invalidates previously-stored ciphertext — acceptable because the only thing
encrypted here is a user-supplied PAT they can simply re-enter.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from habit_tracker.core.config import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.integration_encryption_key
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)
    # Derive a valid 32-byte urlsafe-base64 Fernet key from the app secret.
    derived = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(derived)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret; returns urlsafe-base64 ciphertext (str)."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt ciphertext produced by encrypt_secret back to the plaintext."""
    return _fernet().decrypt(ciphertext.encode()).decode()
