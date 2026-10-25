# Release procedure

Package version is declared in `pyproject.toml` and `src/qmtairlock/version.py`; they must match. Tags use `vMAJOR.MINOR.PATCH`. `CHANGELOG.md` holds release notes and pending changes.

1. Complete the local gates in [Contributing](../CONTRIBUTING.md) and adversarial review. Keep [status](status.md) accurate about native-platform gaps.
2. Build the wheel/sdist and `dist/QMTAIRLOCK.py` with its manifest from the exact tagged commit. Record SHA-256 checksums of release files.
3. Verify the manifest's artifact hash and source-module hashes; inspect the generated configuration block and ensure it contains placeholders with writes disabled.
4. Push the commit and tag, then create the GitHub release with the built files. There is no automatic Actions trigger or automatic package-index publication.
5. Consumers pin an exact Git commit or verified release artifact. Install host strategy, Windows relay/launcher and client from the same revision. Actual installation and write-gate changes remain an operator-controlled deployment.

The builder produces `QMTAIRLOCK.manifest.json` alongside the strategy. Editing account configuration changes the complete artifact hash: deployment tools must validate the unconfigured artifact and limit changes to the marked configuration region. Keep configured copies and their account-specific manifests private.

A rollback must account for outstanding broker operations. Restarting clears in-memory deduplication and callback state; reconcile native order/deal facts before resuming writes. Never treat a rollback as permission to resend unknown requests.
