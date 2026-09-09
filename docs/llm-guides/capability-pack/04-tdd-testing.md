# 04 — TDD & Testing

Rule: **watch every new test fail before making it pass.** A test you've never seen
fail proves nothing — it may be testing nothing.

## The cycle

1. **Red.** Write ONE test for the next small behavior. Run it. Confirm it fails for
   the RIGHT reason (assertion on missing behavior — not an import error or typo).
   Quote the failure output.
2. **Green.** Write the minimum code to pass. Run the test. Quote the pass.
3. **Refactor.** Clean up while green; re-run after. Then next test.

Implementation before test happened anyway? Comment out the implementation, run the
test to see it fail, restore. Cheap, honest.

## What to test (priority order)

1. **The acceptance behavior** — what the task promised, through the public interface.
2. **Edge cases of the data:** empty / zero / one / many · null/missing fields ·
   boundary values (off-by-one limits, max lengths) · duplicate inputs ·
   unicode/whitespace in strings · timezone-bearing datetimes.
3. **Failure paths:** invalid input rejected with the right error · dependency failure
   (DB down, API 500) handled, not swallowed.
4. **Regressions:** every bug fixed gets a test encoding its reproduction (guide 03).

## What NOT to test

- Private helpers directly — test through the public surface, or refactors break tests
  without breaking behavior.
- The framework/library itself ("test" that ORM saves a row).
- Mock-only tests that assert the mock was called with what you just typed — they
  restate the implementation, catch nothing.

## Test quality rules

- One behavior per test; the name states it: `test_rejects_expired_token`, not `test_2`.
- Arrange–act–assert, visible in the test body. Minimal fixtures — a reader should see
  the cause of the assertion without hunting.
- Deterministic: no real network, no real clock (`freeze_time`/inject clock), no
  ordering dependence between tests. A flaky test is worse than none — fix or delete.
- Assert on outcomes (return value, DB row, response body), not on internal call
  sequences, wherever possible.
- Tests follow the project's existing test layout and fixture patterns (guide 01).

## Mocking rule

Mock only true boundaries: network, clock, randomness, third-party APIs, filesystem
when slow. Everything inside your own codebase runs real. Over-mocked test = test of
your mocks.

## Output contract

Every new behavior has a test that was SEEN failing, then passing · full suite green ·
no flaky/no-op tests added · failure output quoted in your report, not paraphrased.
