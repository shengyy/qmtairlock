# Security

The bridge is intended for a trusted Windows user session and a trusted application on the same machine. Deployment permissions and broker access requirements remain the operator's responsibility.

## Local access boundary

The same-host channel follows the Windows process's default access policy. The configured account and allowed account types are checked for each RPC. Processes permitted by that local access policy may connect; operate QMT and the relay under a controlled user and restrict desktop/server access accordingly.

Remote exposure and multi-tenant deployment are outside the supported operating model. The channel provides local message exchange; it does not provide an independent identity or encrypted remote-access service. Keep it inside the trusted machine and follow the terminal provider's access agreement and controls.

Trading methods require `allow_order_methods=True`, which defaults to `False`. Applications own durable execution intent, position sizing and risk limits. A timeout after dispatch can leave an unknown broker result; reconcile native facts before deciding any further action.

## Data and reporting

Keep accounts, credentials and local state outside Git. Host diagnostics use the QMT console. Client Parquet caches inherit local filesystem permissions. The optional external launcher operates the Windows desktop; deployment-specific login automation and secrets are the operator's responsibility.

Use GitHub's private vulnerability reporting when available. If unavailable, open an issue requesting a private contact route without disclosing exploit details, account data or credentials. Ordinary reproducible bugs can use the public template with synthetic data.

The intended-use and disclaimer statement is in [PRODUCT.md](PRODUCT.md#intended-use-and-disclaimer).
