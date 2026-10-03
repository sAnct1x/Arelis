# C03 Plot Regression Investigation Report

## Symptom
In the demo with 9B model, C03 matrix item fails:
- Prompt: "Using Python, compute the squares of 1 through 8, then plot those squares as a line chart, then create a markdown document titled Squares Report that mentions the chart."
- Plot tool fails with message "hit a limit"
- Model skips chart, writes `Squares-Report-2.md` (note `-2` suffix)
- Same prompt passes in matrix runs

## Root Cause Analysis

### 1. "Hit a limit" Error Source
**File:** `arelis/core/loop_helpers.py:352`
```python
_ROUND_LIMIT_NOTICE = "I hit the tool-step limit before finishing. Try a narrower ask."
```

This is shown when `max_rounds` is exhausted.

### 2. max_rounds Configuration
- **Matrix/eval:** 6 rounds (`arelis/eval/harness.py:675`)
- **Demo/shipped:** 8 rounds (`arelis/config/default.yaml:95`)

Despite demo having MORE rounds, it still fails. Why?

### 3. Key Difference: Stubbed vs Real Tools
**Matrix:** Plot tool is stubbed (`arelis/eval/harness.py:586-587`)
- Stub ALWAYS returns `ok=True` regardless of arguments
- No validation, accepts any input

**Demo:** Real plot tool runs
- Validates arguments strictly
- Can fail with `ValueError` on bad input

### 4. Failure Scenarios for Plot Tool
From `arelis/tools/plot.py`:

```python
# Line 559-562: Missing xs/ys
if not xs or not ys:
    raise ValueError(
        "Give a table path with x and y columns, or xs and ys as numbers."
    )

# Line 563: Parse numbers
x = _parse_numbers(xs, name="xs")  # Can fail if xs contains non-numbers

# Line 99-101 in _parse_numbers:
try:
    values = np.array([float(p) for p in parts], dtype=float)
except ValueError as exc:
    raise ValueError(f"{name} must be numbers separated by commas, not an expression.")
```

**Hypothesis:** The 9B model may call plot with:
- Empty strings for xs/ys
- Variable names like `xs="squares"` instead of actual data
- Mal-formed data that fails float parsing

### 5. fail_counts Blocking Logic
**File:** `arelis/core/turn_confirm.py:143`
```python
if fail_counts.get(call_fp, 0) >= 2:
    return await _emit_skip_repeat_fail(...)
```

**Call fingerprint:** `arelis/core/loop_helpers.py:493-498`
```python
def _tool_fail_fingerprint(name: str, args: dict[str, Any] | None) -> str:
    try:
        payload = json.dumps(args or {}, sort_keys=True, default=str)
    except TypeError:
        payload = repr(args)
    return f"{name}|{payload}"
```

**Problem:** If plot fails twice with the SAME bad arguments, all future plot calls with those args are blocked.

### 6. Why Demo Burns More Rounds Than Matrix

**Matrix scenario (6 rounds, passes):**
1. Round 1: python call → succeeds (stub)
2. Round 2: plot call (bad args) → succeeds anyway (stub doesn't validate)
3. Round 3: document call → succeeds (stub)
4. Answer generated

**Demo scenario (8 rounds, fails):**
1. Round 1: Model preamble text
2. Round 2: python call → succeeds
3. Round 3: plot call (bad args) → fails (real validation)
4. Round 4: plot retry (same bad args) → fails again (fail_counts=2)
5. Round 5: plot attempt 3 → BLOCKED by fail_counts >= 2
6. Round 6: Model tries different approach / writes text
7. Round 7: document call → succeeds, creates Squares-Report-2.md
8. Round 8: Try to write answer → hits max_rounds, shows "_ROUND_LIMIT_NOTICE"

### 7. Squares-Report-2.md Naming
**File:** `arelis/tools/document.py:57-66` (also `plot.py:68-77`)
```python
def _unique_dest(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        alt = directory / f"{stem}-{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1
```

**Behavior:** Correct - prevents overwriting existing files.
**Conclusion:** `Squares-Report-2.md` indicates a `Squares-Report.md` already exists from a previous run. This is NOT a bug, just evidence of leftover state.

## Evidence Summary

| Question | Answer | Evidence |
|----------|--------|----------|
| Where can plot return limit-style error? | max_rounds exhaustion | loop_helpers.py:352 |
| Why demo fails but matrix passes? | Matrix stubs always succeed, demo validates | harness.py:586, plot.py:559 |
| Why Squares-Report-2.md? | Previous file exists | document.py:57, plot.py:68 |
| Is -2 behavior correct? | Yes, prevents overwriting | ✓ |
| Is -2 surprising to user? | Somewhat - indicates leftover state | ⚠️ |

## Root Cause
**The plot tool's argument validation correctly rejects malformed input from the 9B model, but the fail_counts mechanism blocks all retries after 2 failures, causing the turn to exhaust max_rounds before completing the 3-tool chain.**

In the matrix, stubbed tools mask this by accepting any input.

## Proposed Fix
**Smallest safe fix:** None required for plot validation - it's working correctly.

**Actual issue:** The 9B model needs better guidance on plot argument format, OR the demo environment needs state cleanup between runs to avoid the `-2` collision issue that suggests repeated failures.

**Alternative:** Increase demo max_rounds to match the higher failure rate of real vs stubbed tools, but this masks the underlying model behavior issue.

## Recommendations
1. **No code change needed** - the `-2` suffix is correct collision avoidance
2. **Environment cleanup** - ensure demo/test runs start with clean outputs folder
3. **Model guidance** - if 9B consistently fails plot arguments, improve prompt/examples
4. **Monitoring** - log the actual plot arguments when it fails to identify the pattern

## Unverified Speculation
Without access to actual demo logs showing the failing plot arguments, I cannot confirm the exact argument format causing the failure. The most likely candidates are:
- Empty strings: `xs=""` or `ys=""`
- Variable references: `xs="result"` or `ys="squares"`
- Malformed data: `ys="[1, 4, 9, ...]"` (Python list syntax instead of CSV)
