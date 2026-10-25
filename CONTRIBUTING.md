# Contributing

Use Python 3.11+ and `uv` for development. The installed client supports Python 3.10+. The lockfile owns development dependencies. The embedded strategy is additionally checked against Python 3.6 syntax and must stay within the host import boundary.

## Local validation

```sh
uv sync --locked
uv run --locked ruff check src scripts tests
uv run --locked ruff format --check src scripts tests
uv run --locked python scripts/check_repository.py
uv run --locked python scripts/check_host.py
uv run --locked pytest -q
uv run --locked python scripts/build_strategy.py
uv build
git diff --check
```

Run from the repository root. `dist/` holds generated files and is ignored. Tests must use isolated accounts and native-function doubles; they never submit live orders. Windows-only native pipe tests skip on other platforms. Do not report skipped tests as verified behavior.

The source gate caps Python files in `src/`, `scripts/` and `tests/` at 800 lines. Split by domain responsibility using composition. Do not introduce numbered parts, mixins or forwarding modules to satisfy the count. The generated strategy is exempt from this source limit.

## Changes

Use a topic branch and a pull request. Add behavior changes to `CHANGELOG.md`, update each fact at its documented owner and link rather than duplicate it. Include relevant local test results and material unverified boundaries. One adversarial review is required for execution, lifecycle and serialization changes.

Never commit account identifiers, credentials, terminal state, logs, local cache or generated build output. Real broker writes, production deployment and changes to live risk settings need explicit authorization from the operator.

## CI and benchmarks

The workflow has only `workflow_dispatch`; pushes, pull requests and tags do not run Actions. Run checks locally by default. Manual CI is optional and is not a prerequisite for publishing locally validated artifacts.

```sh
uv run --locked python scripts/benchmark.py --iterations 1000
```

This measures local serialization and relay framing only. It neither connects to QMT nor estimates terminal round-trip latency. Release steps are owned by [release.md](docs/release.md).
