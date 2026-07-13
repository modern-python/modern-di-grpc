---
status: accepted
summary: Route around coveragepy#2124 with a test-side asyncio checkpoint rather than retrying CI or loosening the coverage gate.
supersedes: null
superseded_by: null
---

# Fix the aio coverage flake in the test, not in CI or the gate

**Decision:** Insert an `await asyncio.sleep(0)` checkpoint in the one test
that runs code after `server.stop(0)`, rather than adding CI-level retries or
relaxing `--cov-fail-under=100` for Python 3.11.

## Context

`checks / pytest (3.11)` intermittently failed CI's 100%-coverage gate,
always on the same two lines of `test_aio_app_finalizer_runs_on_root_close`,
despite all tests passing. Reproduced directly on GitHub Actions (1 failure
in the original run + 1 more within 5 reruns — roughly 1-in-4, not a rare
one-off) and never locally on macOS in 25 attempts.

Traced to [coveragepy#2124](https://github.com/coveragepy/coveragepy/issues/2124):
on Python 3.11, coverage.py's tracer can lose the lines immediately following
an await that internally cancels a task and catches `CancelledError`.
`grpc.aio`'s `Server.stop()` does this to its own background tasks, so any
test code placed right after `await server.stop(0)` sits in the blind spot.
The bug is open upstream with no released fix; the issue thread notes
`--concurrency=thread,greenlet` does not work around it.

Options considered:
1. Retry the pytest CI step once on failure.
2. Lower `--cov-fail-under` for the 3.11 job specifically.
3. Pin a coverage.py version once the upstream bug is fixed.
4. Add a scheduling checkpoint in the affected test so the blind spot lands
   on a throwaway line instead of the assertions under test.

## Decision & rationale

Chose option 4. It fixes the actual mechanism (a specific await placement)
rather than papering over symptoms:
- Retrying (1) would mask any *other* flaky test that happens to fail for a
  real reason, and keeps the flake latent forever.
- Lowering the gate (2) permanently weakens the 100%-coverage guarantee for
  one Python version over a bug that has nothing to do with real coverage.
- Pinning a fixed coverage version (3) isn't available yet — the upstream fix
  is an open PR, not a release.

Options 1-3 remain reasonable fallbacks if this test-side fix turns out not
to generalize (see revisit trigger).

## Revisit trigger

Reopen this if: the coverage gate flakes again on a *different* test or
different lines (meaning this diagnosis doesn't fully explain the bug), or if
coveragepy ships a released fix for #2124 (at which point the checkpoint and
this decision can be removed/superseded).
