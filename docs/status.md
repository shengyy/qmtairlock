# Validation status

Current release: **0.1.1**. This document records the verified environment boundary; it does not equate mock coverage with broker acceptance.

| Area | Current evidence |
|---|---|
| Development | macOS, Python 3.14, locked dependencies; lint, source checks, pytest and wheel/sdist builds |
| Embedded artifact | GBK output, Python 3.6 syntax, closed import graph, real module bodies and SHA-256 manifest |
| Runtime boundary | Mocked lifecycle and representative RPCs pass the runtime dependency boundary checks |
| Trading contracts | Isolated tests for option/credit enum mapping, native identifiers, expiry, unknown writes, reconciliation and callback ordering |
| Pipe/relay | Mocked native lifecycle races plus real local subprocess framing tests |
| Windows local IPC | Platform tests are provided; skipped on the current macOS development machine |
| QMT terminal | No broker terminal build is certified for 0.1.1 yet; native read and controlled execution acceptance remain operator tasks |
| Production | This release does not itself install a strategy, change a service or enable broker writes |

Before declaring a terminal supported, record the exact broker build and embedded Python version, read-only market/account/credit/option/formula results, callback scheduling, stop/restart behavior, and Windows/WSL pipe tests. Execution acceptance requires separately authorized controlled order/cancel checks. Update this document with current evidence rather than keeping a chronological process log.
