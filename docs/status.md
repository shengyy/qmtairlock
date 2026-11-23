# Validation status

Current release: **0.1.1**. This document records the verified environment boundary; it does not equate mock coverage with broker acceptance.

| Area | Current evidence |
|---|---|
| Development | macOS, Python 3.15 locked dependencies (pandas 3.1, numpy 2.5); pytest also run on Python 3.12 and 3.13; lint, source checks and wheel/sdist builds |
| Embedded artifact | Pure ASCII output, Python 3.12 syntax, warning-free compile and load on Python 3.12–3.15, closed import graph, real module bodies and SHA-256 manifest |
| Runtime boundary | Mocked lifecycle and representative RPCs pass the runtime dependency boundary checks |
| Trading contracts | Isolated tests for option/credit enum mapping, native identifiers, expiry, unknown writes, reconciliation and callback ordering |
| Pipe/relay | Mocked native lifecycle races plus real local subprocess framing tests |
| Windows local IPC | Platform tests are provided; skipped on the current macOS development machine |
| QMT terminal | Target host is QMT client 2.1.36 (embedded Python 3.12+, pandas 3); not yet verified on a terminal. Native read and controlled execution acceptance remain operator tasks |
| Production | This release does not itself install a strategy, change a service or enable broker writes |

Before declaring a terminal supported, record the exact broker build and embedded Python version, read-only market/account/credit/option/formula results, callback scheduling, stop/restart behavior, and Windows/WSL pipe tests. Execution acceptance requires separately authorized controlled order/cancel checks. Update this document with current evidence rather than keeping a chronological process log.
