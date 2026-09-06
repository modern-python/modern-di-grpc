# Fix the aio coverage flake in the test, not in CI or the gate

**Decision:** mark the two lines after `server.stop(0)` in
`test_aio_app_finalizer_runs_on_root_close` with `# pragma: no cover`, rather than adding CI-level
retries, relaxing `--cov-fail-under=100` for Python 3.11, or shifting the blind spot with a
scheduling checkpoint.

`checks / pytest (3.11)` intermittently failed CI's 100%-coverage gate, always on the same two lines
of that test, despite all tests passing. It reproduced directly on GitHub Actions (1 failure in the
original run plus 1 more within 5 reruns — roughly 1-in-4, not a rare one-off) and never locally on
macOS in 25 attempts. It traces to
[coveragepy#2124](https://github.com/coveragepy/coveragepy/issues/2124): on Python 3.11,
coverage.py's tracer can lose the lines immediately following an `await` that internally cancels a
task and catches `CancelledError`. `grpc.aio`'s `Server.stop()` does exactly that to its own
background tasks, so any test code placed right after `await server.stop(0)` sits in the blind spot.
The bug is open upstream with no released fix, and the issue thread notes
`--concurrency=thread,greenlet` does not work around it.

Five options were on the table: retry the pytest CI step once on failure; lower `--cov-fail-under`
for the 3.11 job specifically; pin a coverage.py version once the upstream bug is fixed; add a
scheduling checkpoint (`await asyncio.sleep(0)`) after `server.stop(0)` so the blind spot lands on a
throwaway line; or pragma-exclude the affected lines.

The checkpoint was tried **first** and rejected on evidence — it reproduced the flake again on CI
within 2 rerun attempts. The original failure showed a 2-line miss, not 1, so the blind spot's width
is not fixed; moving it just relocates which line fails, and `--cov-fail-under=100` fails on any
missed line. `# pragma: no cover` is honored by coverage.py's static source parser, not the runtime
tracer, so it is structurally immune to the race regardless of how many lines it swallows on a given
run — confirmed locally by the tracked statement count for `tests/test_aio.py` dropping from 107 to
105.

Retrying would mask any *other* flaky test that happens to fail for a real reason, and keeps the
flake latent forever. Lowering the gate permanently weakens the 100%-coverage guarantee for one
Python version over a bug that has nothing to do with real coverage. Pinning a fixed coverage
version is not available: the upstream fix is an open PR, not a release. All three remain reasonable
fallbacks if this test-side fix turns out not to generalize.

**Revisit trigger:** the coverage gate flakes again on a *different* test or different lines —
meaning this diagnosis does not fully explain the bug — or coveragepy ships a released fix for
#2124, at which point the pragmas come out and this record is superseded.
