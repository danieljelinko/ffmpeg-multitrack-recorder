# Red/Green TDD

Default development discipline for any new code.

## The cycle

1. **Red** — write the failing test first. Run it. Confirm it fails for the reason you expect (not import error, not typo).
2. **Green** — write the minimum production code to make that test pass. Resist adding untested behaviour while you're there.
3. **Refactor** — clean up while tests stay green. Run tests after each meaningful change.

## Rules

- No production code without a failing test that requires it.
- One failing test at a time. If you find a second case, note it as a TODO and finish the current cycle first.
- Tests use real data over mocks when feasible — mock only at external boundaries (network, subprocess, hardware). See "Real data over mocks" below.
- When fixing a bug: write the test that exposes it (red), then fix (green). Prevents regressions automatically.

## Test framework and format

The concrete framework mandate, test-file naming, test-name pattern, and fixture conventions are **language-specific** — see the test-format rule distributed alongside this file for your project's language (e.g. the pytest or vitest test-format rule).

Whatever the language, keep these invariants:

- **Test name expresses what is tested.** Read it aloud as a sentence describing the *behaviour* and the *condition*: `{subject}_{expected_outcome}_when_{condition}`. Avoid vague names like `basic` or `works`.
- **Given / When / Then** blocks inside each test, separated by blank lines and comments, so intent is scannable without reading the assertions.
- **Factory fixtures over static ones** for shared setup — build test data with parameters so each test's setup stays visible at the call site.
- **One assertion per concept.** Multiple assert lines are fine if they verify one behaviour; split a test that verifies two unrelated behaviours.
- **Self-contained, deterministic, ordering-independent.** Use framework-managed temp state; never write to a path the test does not own. Passing under shuffled order is mandatory.

## Real data over mocks

Mocking is a last resort, not a default. It hides integration bugs and produces tests that pass while production fails.

### What to mock

- ✅ External processes (media tools, `git`, subprocesses you don't own)
- ✅ System resources (writes to system logs, hardware devices, sound, screen)
- ✅ Time-dependent behaviour (when testing specific dates/times — fake or inject the clock)
- ✅ Network calls to third-party services

### What NOT to mock

- ❌ Database operations — use an in-memory or file-backed real database in a temp dir
- ❌ File operations — use a framework-managed temp dir and let the runner clean up
- ❌ Internal application logic — if you're mocking your own code to test your own code, the test boundary is wrong

## When TDD does not apply

- Throwaway exploration / spikes (delete the spike when done).
- Pure config / docs / data files (no behaviour to test).
- Tracer-bullet UI work where the feedback loop is visual (still write tests for the underlying logic once the UI stabilises).
