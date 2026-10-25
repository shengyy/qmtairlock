# Documentation map

## Core documents

| Document | Only responsibility |
|---|---|
| [PRODUCT.md](../PRODUCT.md) | Supported domains, public boundaries and non-goals |
| [architecture.md](architecture.md) | Module ownership, data flow and build layout |
| [status.md](status.md) | Current verification evidence and remaining environment checks |
| [qmt-runtime.md](qmt-runtime.md) | Host setup, native injection, scheduling and WSL setup |
| [rpc-contract.md](rpc-contract.md) | Wire format, method families, account scope and outcome semantics |
| [release.md](release.md) | Versions, artifact verification and release procedure |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Development setup, local gates and review rules |
| [SECURITY.md](../SECURITY.md) | Trust boundary, credentials and vulnerability reporting |

## Directories

| Directory | Only holds |
|---|---|
| `src/qmtairlock/` | Importable domain, client, host and transport implementations |
| `scripts/` | Strategy builder, source/runtime boundary gates and local benchmarks |
| `tests/` | Isolated contract, concurrency, local IPC and runtime boundary tests |
| `docs/` | Current architecture, contracts, operations and verification facts |
| `.github/` | Manual CI and contribution templates |
| `dist/` | Ignored local build output |

## Writing rules

- **One owner per fact:** edit the responsible document and link to it elsewhere.
- **Current state only:** remove superseded plans and process logs; Git holds history.
- **Verified then written:** distinguish implementation, local tests and native terminal acceptance.
- **Nothing private:** use placeholders and synthetic fixtures, never real accounts or host paths.

Use lowercase kebab-case filenames inside `docs/`. Keep root files as standard entry points. Update English and Chinese READMEs together; route detailed material to its owner.

## Context layers

1. `AGENTS.md` contains persistent boundaries and a routing table; `CLAUDE.md` points to it.
2. This map and the relevant owner documents provide task-specific context.
3. Read the owning implementation and targeted tests before changing or claiming behavior.
