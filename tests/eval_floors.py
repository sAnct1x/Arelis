"""Named pass-rate floors. A drop is one assert; raising a floor is one line.

Pinned 2026-09-18 against the boards on this checkout. The live tool-choice
floor is the 2026-09-17 shipping-arm table, not a re-measure.
"""

from __future__ import annotations

# 2026-09-18 — scripted foundation scenarios that test_eval_board runs.
# Keep the exact-count assert against SCENARIOS; this pin is so adding one
# is a one-line raise rather than a silent extra green.
SCRIPTED_BOARD_COUNT = 84

# 2026-09-18 — skill retrieval board. passed == total still required;
# these pins catch the board shrinking or a case disappearing.
SKILL_RETRIEVAL_TOTAL = 18
SKILL_RETRIEVAL_PASSED = 18

# 2026-09-18 — len(CHOICE_CASES). Four cases landed after the 2026-09-17
# 42-case live table (memory list, workspace rename, clipboard write,
# inbox download). The live floor below is still an absolute hit count.
CHOICE_CASE_COUNT = 46

# 2026-09-17 shipping arm (skinny + preflight) on qwen3.5:9b, 42 cases:
# seeds 37, 39, 37 — mean 37.7 / 42. Unguarded skinny mean 31.7.
# Floor sits below the measured mean and above the unguarded band.
CHOICE_LIVE_FLOOR = 35
