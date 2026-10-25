# Security

The bridge assumes a trusted Windows user session and a trusted client application on the same machine. It is not a multi-tenant or hostile-local-user boundary.

## Access

The server creates message-mode named pipes with `PIPE_REJECT_REMOTE_CLIENTS`. The account id is part of the pipe name and every RPC envelope must match the configured account. Account-type access is limited to the strategy configuration.

Pipe access uses the Windows process's default security descriptor; there is no custom per-client ACL, authentication token or encryption layer. Other local processes allowed by that descriptor may connect. Run QMT and the relay under a controlled user and restrict desktop/server access accordingly. Do not forward the pipe or relay to an untrusted network.

Trading methods require `allow_order_methods=True`, which defaults to `False`. The bridge's validation and deduplication do not replace an application's execution intent, position sizing or risk controls. A timeout after dispatch can mean the broker accepted an order: query native facts and do not blindly retry.

## Data and reporting

Keep accounts, credentials and local state outside Git. The host logs to its console only. Client Parquet caches contain market data and inherit local filesystem permissions. The optional launcher operates the Windows desktop; deployment-specific login automation and secrets are the operator's responsibility.

Use GitHub's private vulnerability reporting on this repository when available. If unavailable, open an issue requesting a private contact route without disclosing exploit details, account data or credentials. Ordinary reproducible bugs can use the public bug template with synthetic data.
