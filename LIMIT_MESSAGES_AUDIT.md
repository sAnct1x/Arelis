# Complete Audit of "Limit" Messages in Arelis

## User-Visible Error Messages Containing "limit"

### 1. Round Limit (max_rounds exhausted)
**File:** `arelis/core/loop_helpers.py:352`
```python
_ROUND_LIMIT_NOTICE = "I hit the tool-step limit before finishing. Try a narrower ask."
```

**Trigger condition:** The agent loop exhausts all `max_rounds` without completing the task.
- Demo: `max_rounds = 8` (`default.yaml:95`)
- Matrix: `max_rounds = 6` (`harness.py:675`)

**Visible to model:** YES - shown as fallback_text when `_force_final_answer` produces empty/refused content
**Location:** `agent_loop.py:810`
**Can be followed by document write:** NO - `_force_final_answer` runs with `expect_tools=False` (line 765), no tools allowed

**Counter reset:** Per-turn (new TurnContext for each user message)

### 2. Repeat Failure Block (fail_counts >= 2)
**File:** `arelis/core/turn_confirm.py:45-61`
```python
notice = f"[fail:other] Already failed twice with the same {name} arguments this turn; not asking Allow again. Change the args or stop."
stop_msg = f"Stop calling `{name}` with those same arguments — it already failed twice this turn."
```

**Trigger condition:** Same tool with same arguments fails twice in one turn
**Visible to model:** YES - injected as tool result message and user message
**Can be followed by document write:** YES - blocks one specific call, not the entire turn
**Counter reset:** Per-turn (`fail_counts` is in TurnContext, line `turn_context.py:138`)

### 3. Too Many Redirects
**File:** `arelis/tools/fetch.py:162`
```python
raise BlockedUrlError(f"Too many redirects (>{_MAX_REDIRECTS}) starting at {url}")
```
**Not relevant to plot tool**

### 4. Too Many Pending Reminders
**File:** `arelis/reminders.py:277`
```python
raise ReminderError(f"Too many pending reminders ({MAX_PENDING}). Cancel one first.")
```
**Not relevant to plot tool**

### 5. Rate Limiting (web search/scrape)
**Files:** `arelis/core/evidence.py`, `arelis/tools/search.py`
```python
if "rate limit" in text or "ratelimit" in text:
    return "fail:rate_limit"
# Message: "The engine may be rate limiting."
```
**Not relevant to plot tool**

### 6. Attachment Size Limit
**File:** `arelis/tools/inbox.py:574`
```python
f"{name or '(unnamed)'} is too large to download ({len(blob):,} bytes; the limit is {self.max_attachment_bytes:,}). Nothing was saved."
```
**Not relevant to plot tool**

## Plot Tool-Specific Validation Errors

**File:** `arelis/tools/plot.py`

The plot tool has NO messages containing "limit". Its validation errors are:
- Line 559: "Give a table path with x and y columns, or xs and ys as numbers"
- Line 101: "{name} must be numbers separated by commas, not an expression"
- Line 103: "{name} contained a non-number"
- Line 566: "xs and ys must be the same length"
- Line 568: "Need at least two points"

## Python Exec Tool Limits (could surface under plot's name?)

**File:** `arelis/tools/python_exec.py`

- Line 288: "The Python cell timed out (10s). I will not guess the result."
- Line 291: "Python refused: {exc}"
- Line 295: "Python syntax error: {exc.msg}"
- Line 298: "Python failed: {exc}"

**Can python_exec limits surface as plot errors?** NO - Each tool call is separate. Python runs, returns its result, then plot is called with that result. If python fails, plot never runs.

## Confirm/Allow Flow for Plot (risk=write)

**File:** `arelis/tools/base.py`, `arelis/tools/policy.py`

Plot has `risk = "write"` (plot.py:233), so it triggers Allow confirmation.

**Confirmation timeout:** `default.yaml:102` - 300 seconds
**What happens on timeout:** Confirm is denied, tool doesn't run
**What happens on denial:** Tool doesn't run, model told "user declined this specific `{tool}` call"
**Is there a "too many confirmations" limit?** NO - each call gets its own confirm card

## Turn Budget and Step Counting

**Rounds vs Tool Calls:**
- A "round" is one model inference + any tool calls it makes
- If model generates text without tools: counts as 1 round
- If model calls tools: counts as 1 round regardless of how many tools
- Preamble text before tool call: same round as the tool call
- Failed tool call: still counts as a round

**What counts toward max_rounds:**
1. Model generates text (with or without tools)
2. Model calls tools (successful or failed)
3. NO-CALL rounds (model tries but produces no valid call): YES, still counts

**What does NOT count:**
- Confirmation waiting time
- Tool execution time itself

**Shared budgets between tools:** NONE - each tool call is independent

## Document Tool Folder Selection

**File:** `arelis/tools/document.py:236-259`

```python
def out_dir(self) -> tuple[Path, str]:
    """(folder, short where-it-landed note)."""
    room_dir = self.room_documents_dir()  # Project/documents if room has folder
    if room_dir is not None:
        return room_dir, "this room's documents folder"
    # Falls back to outputs/documents/
    return self.drop_dir(), "the shared drop tray (outputs/documents)"
```

**Where to check for Squares-Report.md:**
1. If in a room with a workspace root: `<workspace_root>/documents/Squares-Report.md`
2. Otherwise: `outputs/documents/Squares-Report.md`

The `-2` suffix is added by `_unique_dest()` at line 328 when the base name already exists.

## Summary: What Could Cause "hit a limit"?

Based on the audit, only ONE message matches Christopher's report:

**`_ROUND_LIMIT_NOTICE` = "I hit the tool-step limit before finishing"**

This is shown when max_rounds is exhausted. However, Christopher said the plot tool failed "then the model still wrote the doc" - but `_ROUND_LIMIT_NOTICE` happens AFTER the force_final_answer round which has `expect_tools=False`, so document couldn't be written after this message.

**Contradiction:** The report says plot failed with "hit a limit", then document was written. But code shows the limit message only appears after all tools are blocked.

**Possible explanations:**
1. Christopher paraphrased - the actual message was "Already failed twice" and he remembered it as "hit a limit"
2. The sequence was: plot failed (validation error), document succeeded, THEN at turn end the round limit notice appeared
3. There's a message I haven't found yet

**What log line would settle this:** The actual tool result message from the failed plot call, showing the exact error text and when it occurred relative to the document write.
