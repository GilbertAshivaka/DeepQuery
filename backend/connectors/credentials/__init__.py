"""Credential management — encrypted per-user credential store + OAuth flows.

Credentials are owned here (the Gateway's credential store), never by connectors
(SDK contract) and never shipped in connector code/config. See guide §6.
"""

from connectors.credentials.store import (
    CredentialError,
    CredentialStore,
    InjectedCredential,
    credential_store,
)

__all__ = ["CredentialStore", "credential_store", "CredentialError", "InjectedCredential"]
