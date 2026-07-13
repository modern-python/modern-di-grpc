---
status: accepted
summary: Route around coveragepy#2124 with pragma:no cover on the affected lines rather than retrying CI, loosening the coverage gate, or shifting the blind spot with a checkpoint.
supersedes: null
superseded_by: null
---

# Fix the aio coverage flake in the test, not in CI or the gate

**Decision:** Mark the two lines after `server.stop(0)` in
`test_aio_app_finalizer_runs_on_root_close` with `# pragma: no cover`, rather
than adding CI-level retries, relaxing `--cov-fail-under=100` for Python
3.11, or shifting the blind spot with a scheduling checkpoint.

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
4. Add a scheduling checkpoint (`await asyncio.sleep(0)`) after
   `server.stop(0)` so the blind spot lands on a throwaway line instead of
   the assertions under test.
5. Mark the affected lines `# pragma: no cover` so they're excluded from the
   statement count regardless of whether the tracer catches them.

## Decision & rationale

Tried option 4 first — reproduced the flake again on CI within 2 rerun
attempts. The original failure showed a 2-line miss, not 1, so the blind
spot's width isn't fixed; moving it just relocates which line fails, and
`--cov-fail-under=100` fails on any missed line. Checkpoints don't work here.

Chose option 5. `# pragma: no cover` is honored by coverage.py's static
source parser, not the runtime tracer, so it's structurally immune to the
race regardless of how many lines it swallows on a given run — confirmed
locally by the tracked statement count for `tests/test_aio.py` dropping from
107 to 105.
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
