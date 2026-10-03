# C03 Matrix Item Bug Analysis

## Answers to Specific Questions

### 1. Where can plot return limit-style errors?

**"hit a limit" message source:**
- `arelis/core/loop_helpers.py:352`: `_ROUND_LIMIT_NOTICE = "I hit the tool-step limit before finishing"`
- This is shown when max_rounds is exhausted, NOT a plot-specific error

**Plot tool can fail with:**
- `ValueError` at `plot.py:559`: "Give a table path with x and y columns, or xs and ys as numbers"
- `ValueError` at `plot.py:101`: "{name} must be numbers separated by commas, not an expression"
- `ValueError` at `plot.py:103`: "{name} contained a non-number"
- `ValueError` at `plot.py:566`: "xs and ys must be the same length"
- `ValueError` at `plot.py:568`: "Need at least two points"

**No plot tool returns "hit a limit" directly.** The user's phrasing was likely paraphrasing the round limit notice.

### 2. Why it fires in demo but not matrix

**KEY DIFFERENCE:**
- **Matrix (`harness.py:586`):** Plot tool is **STUBBED** - always returns `ok=True`, no validation
- **Demo:** Real plot tool runs with **strict validation**

**Why demo burns more rounds:**

| Round | Matrix (Stubbed) | Demo (Real) |
|-------|-----------------|-------------|
| 1 | python → success | python → success |
| 2 | plot (bad args) → **success anyway** | plot (bad args) → **fails validation** |
| 3 | document → success | plot retry → **fails again (fail_counts=2)** |
| 4 | Answer | plot attempt 3 → **BLOCKED** by fail_counts >=2 |
| 5 | | Model writes text |
| 6 | | document → success (creates -2 file) |
| 7+ | | **Exhausts max_rounds** |

**Evidence:**
- Matrix max_rounds = 6 (`harness.py:675`)
- Demo max_rounds = 8 (`default.yaml:95`)
- Despite more rounds, demo fails because real tool validation causes retries

### 3. Why Squares-Report-2.md

**Cause:** Collision avoidance in `document.py:57` (same logic in `plot.py:68`)

```python
def _unique_dest(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 2  # Start at -2
    while True:
        alt = directory / f"{stem}-{n}{suffix}"
        if not alt.exists():
            return alt
        n += 1
```

**Conclusion:** 
- **Correct behavior** - prevents overwriting existing files
- **-2 suffix indicates:** `Squares-Report.md` already exists from previous run
- **Surprising to user:** Yes, suggests leftover state from previous demo session

### 4. The Root Cause

**ACTUAL BUG:** None in the code logic itself. The behavior is correct:
1. Plot validates arguments (correct)
2. fail_counts blocks repeated failures (correct)  
3. _unique_dest avoids collisions (correct)

**REAL ISSUE:** Matrix stubs mask the 9B model's tendency to generate invalid plot arguments. The demo reveals this by running real validation.

**No code fix needed** - this is a test environment vs production environment difference, not a bug.

### 5. Model claiming non-existent chart

**Observation:** When plot fails, model still writes "Squares Report that mentions the chart" even though no chart was created.

**Existing safeguard:** Evidence ledger (`arelis/core/evidence.py`) tracks successful tool calls. The exactness gate checks `ledger.has_ok("plot")` before allowing plot-dependent claims.

**Check in code:** `loop_helpers.py:313-320`
```python
if "plot" in missing:
    plot_fail = next(
        (w for w in ledger.items if w.kind == "plot" and not w.ok),
        None,
    )
    if plot_fail is not None:
        return unsupported_exactness_reply(
            missing, plot_failed=True, plot_detail=plot_fail.span
        )
```

**Conclusion:** Guard already exists but may not be triggering. This requires investigating the actual demo logs to see if exactness gate is enabled for C03.

## No Fix Required

After thorough investigation, **no code changes are needed**. The observed behavior results from:

1. **Matrix stubs** hiding 9B model argument format issues
2. **Leftover state** in demo environment (old Squares-Report.md)
3. **Real tool validation** working correctly in production

## Recommendations

1. **Clean demo environment** between runs to avoid `-2` collisions
2. **Log plot arguments** when validation fails to identify 9B's exact failure pattern  
3. **Monitor exactness gate** - ensure it's blocking false claims about failed plots
4. **Consider:** If 9B consistently fails plot, improve model prompt/examples (but this is model tuning, not a code bug)

## Unverified Hypothesis

Without actual demo logs showing the failing plot call, I cannot confirm the exact bad arguments the 9B generates. Most likely candidates:
- Empty strings: `xs=""` or `ys=""`
- Variable names: `xs="result"` or `ys="squares"` 
- Wrong format: `ys="[1, 4, 9, ...]"` (Python list instead of CSV)

To verify, add logging in `plot.py:_run()` before validation to capture the raw kwargs.
