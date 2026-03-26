"""Cross-platform secret storage backed by the OS credential store."""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, NoKeyringError, PasswordDeleteError


class SecretStoreError(Exception):
    """Raised when the system credential store is unavailable or fails."""


class SecretStore:
    """Wrapper around keyring to avoid leaking provider secrets into project files."""

    def __init__(self, service_name: str = "DevBrain") -> None:
        self._service_name = service_name

    def set_secret(self, secret_ref: str, secret_value: str) -> None:
        try:
            keyring.set_password(self._service_name, secret_ref, secret_value)
        except (KeyringError, NoKeyringError) as exc:
            raise SecretStoreError(self._friendly_message(exc)) from exc

    def get_secret(self, secret_ref: str) -> str | None:
        try:
            return keyring.get_password(self._service_name, secret_ref)
        except (KeyringError, NoKeyringError) as exc:
            raise SecretStoreError(self._friendly_message(exc)) from exc

    def delete_secret(self, secret_ref: str) -> None:
        try:
            keyring.delete_password(self._service_name, secret_ref)
        except PasswordDeleteError:
            return
        except (KeyringError, NoKeyringError) as exc:
            raise SecretStoreError(self._friendly_message(exc)) from exc

    @staticmethod
    def _friendly_message(exc: Exception) -> str:
        return (
            "System credential storage is unavailable. "
            "Please ensure the local keyring service is available and try again."
        )


_secret_store = SecretStore()


def get_secret_store() -> SecretStore:
    """Return the shared secret store instance."""

    return _secret_store
