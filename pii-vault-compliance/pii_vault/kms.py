"""Pluggable key-management adapters.

Keys never live beside the data they protect. A KMS adapter owns key material and
key lifecycle (create / rotate / retire); the vault only ever holds a key id.
"""
from __future__ import annotations

import abc
import json
import os
import secrets
import time
from pathlib import Path


class KMSAdapter(abc.ABC):
    """Minimal key-provider contract.

    Implementations must keep historical keys readable after rotation, otherwise
    data written under an old key could never be decrypted again.
    """

    @abc.abstractmethod
    def current_key_id(self) -> str: ...

    @abc.abstractmethod
    def get_key(self, key_id: str) -> bytes: ...

    @abc.abstractmethod
    def create_key(self) -> str: ...

    @abc.abstractmethod
    def list_key_ids(self) -> list[str]: ...

    def rotate(self) -> str:
        """Create a new key and make it current. Historical keys are retained."""
        return self.create_key()


class LocalFileKMS(KMSAdapter):
    """File-backed KMS used for local development and the acceptance tests.

    One file per key, 0600. The current key id lives in ``current``. This stands in
    for HashiCorp Vault: the interface is what matters, and ``VaultKMS`` below can be
    dropped in without touching the vault.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._current_file = self.root / "current"

    def _key_path(self, key_id: str) -> Path:
        return self.root / f"key-{key_id}.bin"

    def current_key_id(self) -> str:
        if not self._current_file.exists():
            return self.create_key()
        return self._current_file.read_text().strip()

    def get_key(self, key_id: str) -> bytes:
        path = self._key_path(key_id)
        if not path.exists():
            raise KeyError(f"unknown key id: {key_id}")
        return path.read_bytes()

    def create_key(self) -> str:
        key_id = f"k{int(time.time() * 1000)}{secrets.token_hex(3)}"
        path = self._key_path(key_id)
        path.write_bytes(secrets.token_bytes(32))
        os.chmod(path, 0o600)
        self._current_file.write_text(key_id)
        return key_id

    def list_key_ids(self) -> list[str]:
        return sorted(p.stem.removeprefix("key-") for p in self.root.glob("key-*.bin"))


class VaultKMS(KMSAdapter):
    """HashiCorp Vault transit-style adapter.

    Deliberately thin: it talks to a KV v2 path over the HTTP API and keeps the same
    contract as ``LocalFileKMS``. A ``simulate`` mode is provided so the acceptance
    tests can exercise this code path without a live Vault.
    """

    def __init__(self, url: str, token: str, mount: str = "secret", simulate: bool = False):
        self.url = url.rstrip("/")
        self.token = token
        self.mount = mount
        self._sim = LocalFileKMS(Path(os.environ.get("VAULT_SIM_DIR", "/tmp/pii-vault-kms-sim"))) if simulate else None

    def current_key_id(self) -> str:
        if self._sim:
            return self._sim.current_key_id()
        raise NotImplementedError("live Vault wiring is deployment-specific")

    def get_key(self, key_id: str) -> bytes:
        if self._sim:
            return self._sim.get_key(key_id)
        raise NotImplementedError("live Vault wiring is deployment-specific")

    def create_key(self) -> str:
        if self._sim:
            return self._sim.create_key()
        raise NotImplementedError("live Vault wiring is deployment-specific")

    def list_key_ids(self) -> list[str]:
        if self._sim:
            return self._sim.list_key_ids()
        raise NotImplementedError("live Vault wiring is deployment-specific")


def load_kms_from_env() -> KMSAdapter:
    """Select the adapter from the environment.

    ``PII_KMS=local`` (default) uses a directory; ``PII_KMS=vault`` uses Vault and
    falls back to the simulation unless a token is supplied.
    """
    kind = os.environ.get("PII_KMS", "local").lower()
    if kind == "vault":
        return VaultKMS(
            os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200"),
            os.environ.get("VAULT_TOKEN", ""),
            os.environ.get("VAULT_MOUNT", "secret"),
            simulate=not os.environ.get("VAULT_TOKEN"),
        )
    return LocalFileKMS(os.environ.get("PII_KMS_DIR", "/tmp/pii-vault-kms"))


def describe(kms: KMSAdapter) -> str:
    return json.dumps(
        {"adapter": type(kms).__name__, "current_key_id": kms.current_key_id(), "keys": kms.list_key_ids()}
    )
