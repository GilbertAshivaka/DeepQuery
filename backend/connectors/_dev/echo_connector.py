"""An SDK connector that echoes back the credential the Gateway injected.

Used to prove per-user credential injection and isolation: each user's call
spawns this connector with *their* token in the environment, and `whoami` returns
exactly that token. The connector reads it through the SDK's
`env_credential_provider`, the intended cross-process injection path.

    python connectors/_dev/echo_connector.py   # serves over stdio
"""

from __future__ import annotations

from deepquery_sdk import Connector, CredentialError, env_credential_provider, resource

# Must match connectors.credentials.store.ENV_TOKEN.
_ENV_TOKEN = "DEEPQUERY_CONNECTOR_TOKEN"


class EchoAuthConnector(Connector):
    name = "echo-auth"
    version = "1.0.0"
    description = "Echoes the per-user credential the gateway injected (for testing)."
    requires_network = False
    air_gapped_capable = True

    @resource(
        description="Return the credential token injected for the calling user.",
        input_schema={"type": "object", "properties": {}},
    )
    def whoami(self):
        try:
            token = self.current_credential.token
        except CredentialError:
            token = None
        return [
            self.cite(
                {"injected_token": token},
                source_object_id="whoami",
                title_or_label=f"injected token: {token}",
            )
        ]


if __name__ == "__main__":
    from deepquery_sdk.mcp_emit import run_stdio

    connector = EchoAuthConnector()
    connector.set_credential_provider(env_credential_provider(token_env=_ENV_TOKEN))
    run_stdio(connector)
