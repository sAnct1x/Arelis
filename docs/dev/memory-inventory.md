# B0 Memory and chat inventory (Nov 9 2026)

Read-only pass on `origin/main` at `3f4e896`. Goal: map what exists before B1-B4.
Christopher's feel that memory and chat are "basically nonexistent" is partly
UX (hidden docks, confirm gates, no auto-recall) and partly real gaps
(preferences never injected, compaction drops numbers, no edit UI).

## 1. Storage

| What | Where | Format |
|------|-------|--------|
| Conversation archive | `user_data_dir()/data/memory.db` | SQLite WAL, schema v12 |
| Standing profile | `user_data_dir()/data/profile.yaml` | YAML, hand-edited |
| Dated memory copies | off by default (`MEMORY_BACKUP_KEEP = 0`) | |

- Installed Windows root is `%LOCALAPPDATA%\Arelis`; checkout uses the repo root (`arelis/paths.py:75-105`, `state_dir` at `:108-110`). Override: `ARELIS_DATA_DIR`.
- Default DB path: `state_dir() / "memory.db"` (`arelis/memory/store.py:25`, `368`).
- Tables: `sessions`, `messages`, `summaries`, `facts`, `embeddings`, `documents` / `document_chunks` / `document_embeddings`, `mail_*`, `tasks`, `preferences`, `decisions`, `episodes`, `goals`, plus FTS5 mirrors (`store.py:31-281`, `SCHEMA_VERSION = 12` at `:29`).
- Embeddings: CPU `nomic-embed-text` via separate llama-server (`default.yaml:27-33,66-86`; `indexer.py:36`, `1-6`). Idle batches only (`indexer.py:3-6`).

## 2. What is saved about the user, and when

| Kind | When written | Status / gate |
|------|--------------|---------------|
| Chat messages | Every `SessionMemory.add` with a sink | Immediate write-through (`core/memory.py:178-182`; `store_sessions.py:134-156`) |
| Session title | First user turn | Auto from content (`store_sessions.py:146-155`) |
| Rolling summary | When history overflows token/count budget | Model fold; speak/slash/research skip (`agent_loop.py:1422-1520`) |
| Pending facts | Proposed by summarizer | Stay pending until History click (`store_facts.py:19-26`; `history.py:88-91`) |
| Active facts | `memory` tool remember, or History approve | Confirm card for tool writes (`memory_tool.py:1-9,76`) |
| Preferences / decisions / episodes | Explicit `memory` tool only | Confirm; episodes never auto (`memory_tool.py:7-9`; `episodes.py:3-4`) |
| Profile fields | Hand-edit `profile.yaml` | Injected every turn (`profile.py:1-5,158-169`) |
| Doc/mail chunks | Idle indexer | Docs on by default; mail off (`default.yaml:70-86`) |

Dedup: exact-text active/pending facts (`store_facts.py:46-56`); keyed facts supersede (`:58-59,137-159`). Forget uses loose match (`store.py:332-350`; `store_facts.py:173-199`). Cap on remember: 400 chars (`memory_tool.py:178-182`).

## 3. Retrieval into a chat

**Automatic (every turn, system prompt):**
- Standing profile (`prompt_sections.py:147-149`)
- Active facts, up to 24 / 1200 chars (`facts.py:9-37`; `agent_loop.py:1311-1321`; `prompt_sections.py:153-155`)
- Last 3 episodes (`episodes.py:18-36`; `prompt_sections.py:157-161`)
- In-session summary pin: `[earlier in this conversation: …]` (`agent_loop.py:1354-1359`)
- Recent chat via `SessionMemory.as_chat` (notices omitted) (`core/memory.py:260-270`)

**Not automatic:** preferences and decisions tables are tool-list only (`memory_tool.py:199-238`; no `preferences_prompt` in `prompt_sections.py`). Past chats and docs are **not** pulled unless the model calls `recall`.

**`recall` tool (opt-in search):** FTS5/LIKE + optional vector; merge by RRF k=60 (`recall.py:1-10,201-261`; `rrf.py:7-24`). Default 8 hits, max 20, 300-char excerpts (`recall.py:24-26`). Embed failure falls back to keywords (`:217-254`). CPU embed so chat VRAM stays free (`:7-10`).

## 4. Chat history persistence and UI

- Save: write-through on every message when UI/CLI attach `MemoryStore` as sink (`store.py:1-6`; `core/memory.py:123-125`). Jobs use no sink.
- List: History dock, up to 100 sessions, pinned first (`history_host.py:12-31`; `store_sessions.py:237-263`). Blank unused shells hidden (`:107-118`).
- Search: title/date filter plus body via `store.search` limit 200 (`history.py:28-65,117-122`). Shortcut Ctrl+Shift+F (`:120`).
- Reopen: click emits `SESSION_LOAD`; blocked while a turn is busy (`history_host.py:63-82,164-170`). New / pin / delete supported (`:85-151`).
- In-chat find: Ctrl+F `ChatFindBar` (`chat_find.py:36`; `shortcuts.py:37`).
- Hydrate trims to `history_max_messages` so a long reopen cannot blow the working set (`core/memory.py:304-335`).

## 5. Compaction / summarization

- Triggers when token budget or `history_max_messages` (600) cannot hold history; drops a block to ~half (`default.yaml:201-240`; `agent_loop.py:1361-1408`; `core/memory.py:342-357`).
- Model fold: one paragraph, max 800 chars; proposes up to 2 pending facts (`agent_loop.py:383-409,1551-1570`). Skipped for speak, slash, research (`:1422-1447`). Timeout/fail = drop with no summary (`:1497-1513`).
- **Numbers / equations / decisions:** summary prompt asks for durable identity/prefs only and says most excerpts get `FACTS: NONE` (`:385-406`). It does **not** require verbatim numbers, equations, or decisions. No UI marker at the compaction point in the transcript; only a status toast and the system pin (`:1468-1471,1358`).
- Archive keeps full messages; only the in-process working set shrinks (`:1516-1519`).

## 6. Settings and user-visible memory UI

- **History dock:** sessions + pending fact approve/reject (`history.py:87-100,160+`).
- **Settings → Memory:** `ActiveFactsPanel` lists active facts, filter, forget (reject). No edit/rename of fact text (`panels/memory.py:20-135`; `settings_dialog.py:824`).
- Tool path: `memory` list/remember/forget/prefer/decide/episode (`memory_tool.py:57-75`). Writes need confirm.
- Profile is file-based, not a Settings form (`profile.py:1-5`).
- Dated `memory.db` snapshots are off (`docs/backups.md:3-4`; `memory/backup.py:23`).

## 7. Gaps vs B1-B4 and smallest first PRs

| Track | Plan ask | Today | Gap |
|-------|----------|-------|-----|
| B1 Memory | Durable facts, deduped, dated; see/edit/delete | Facts + dates + dedup + approve/forget exist; **no edit**; prefs/decisions unused in prompt; episodes tiny | Edit UI; inject prefs; surface dates in Settings |
| B2 Retrieval | Relevant memories each chat, ranked, not noisy | Only active facts + 3 episodes auto; rest needs `recall` | Auto-retrieve top-N ranked memories per turn |
| B3 Chat history | Saved, searchable, easy reopen | Mostly done (save/list/search/pin/reopen) | Discoverability / empty-state; maybe richer search UI |
| B4 Compaction | Summarize without losing numbers/equations/decisions; show marker | Fold exists; drops precision; no transcript marker | Preserve-verbatim rules + chat marker |

**Recommended build order (smallest first PR each):**
1. **B3 polish** (smallest): History empty-state + first-run tip that past chats live in the History dock. Files: `arelis/ui/panels/history.py`. No schema.
2. **B1 edit + prefs inject:** (a) edit active fact text in Settings → Memory; (b) pin `list_preferences` into `append_operating_context` like facts. Files: `panels/memory.py`, `store_facts.py`, `prompt_sections.py`.
3. **B4 compaction contract:** extend `_SUMMARY_SYSTEM` / `_SUMMARY_USER` to keep numbers, equations, and decisions verbatim; paint a visible "[earlier turns compressed]" marker in chat when `set_summary` runs. Files: `agent_loop.py`, chat panel.
4. **B2 auto-retrieval:** on each user turn, hybrid-search memory (facts + recent messages + prefs) and inject a capped ranked block; reuse `merge_ranked_hits`. Files: new helper + `prompt_sections.py` / turn prepare. Test with Babbage's fixed set on Atria.

Why Christopher feels nothing: auto context is thin (facts only after approve; prefs never injected); recall is a tool the model must choose; History/Memory are docks; compaction silently loses exact values.
