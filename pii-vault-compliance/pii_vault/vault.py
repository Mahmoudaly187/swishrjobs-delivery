"""The personal-information vault: tokenize / detokenize with field-level encryption.

Design notes that the acceptance criteria depend on:

* Each field is sealed separately with AES-256-GCM under a key from the KMS. The
  nonce is fresh per write, so two rows holding the same phone number produce
  different ciphertext.
* A token is an opaque handle. The plaintext is *never* stored in the row; only the
  sealed value and a key id are. Querying the table directly therefore reveals no
  plaintext, which is criterion 1.
* Rotation re-wraps every row under the new key while leaving the token stable, and
  historical keys stay readable, so criterion 1's "old data can still be decrypted"
  holds.
* ``detokenize`` requires both a permission and a stated reason; both are checked by
  the caller (see ``api``) and recorded in the audit log, which is criterion 3.
"""
from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .kms import KMSAdapter

AAD_PREFIX = b"pii-vault:v1:"


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode())


@dataclass
class SealedField:
    """One encrypted field value, plus the key that protects it."""

    token: str
    key_id: str
    nonce: str
    ciphertext: str

    def to_row(self) -> dict:
        return {"token": self.token, "key_id": self.key_id, "nonce": self.nonce, "ciphertext": self.ciphertext}


class PIIVault:
    def __init__(self, kms: KMSAdapter):
        self.kms = kms

    def _aad(self, token: str, field: str) -> bytes:
        # Binding the token and field name into the AAD means a ciphertext cannot be
        # moved to another row or another field without failing authentication.
        return AAD_PREFIX + token.encode() + b":" + field.encode()

    def seal(self, token: str, field: str, plaintext: str, key_id: str | None = None) -> SealedField:
        key_id = key_id or self.kms.current_key_id()
        key = self.kms.get_key(key_id)
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, plaintext.encode(), self._aad(token, field))
        return SealedField(token=token, key_id=key_id, nonce=_b64e(nonce), ciphertext=_b64e(ct))

    def open(self, field: SealedField, field_name: str) -> str:
        key = self.kms.get_key(field.key_id)
        pt = AESGCM(key).decrypt(
            _b64d(field.nonce), _b64d(field.ciphertext), self._aad(field.token, field_name)
        )
        return pt.decode()

    def new_token(self) -> str:
        return "tok_" + uuid.uuid4().hex

    def rotate(self, rows: list[tuple[str, str, SealedField]]) -> tuple[list[SealedField], str]:
        """Re-wrap fields under a fresh key.

        ``rows`` is ``(token, field_name, sealed_field)``. Plaintext is decrypted only
        in memory, and the token is preserved so callers keep the same handle.
        """
        new_key_id = self.kms.rotate()
        rotated: list[SealedField] = []
        for token, field_name, sealed in rows:
            plaintext = self.open(sealed, field_name)
            rotated.append(self.seal(token, field_name, plaintext, key_id=new_key_id))
        return rotated, new_key_id
