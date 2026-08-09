# MPA — Multi Purpose Assistant

> "all-purpose personal manager" — a local-LLM chat assistant, built around PTIT's UIS
> student portal, that can read your class schedule, answer natural-language
> questions about it in Vietnamese, and keep a Notion calendar in sync with it.

This README is a from-scratch analysis of the repository as it currently stands
(4 commits, single author, actively mid-development). It documents what each
file does, how the pieces fit together, what already works, and what is
unfinished or broken.

---

## 1. What this project actually is

MPA is a **local, tool-calling chatbot** that runs against an **Ollama** model
(`qwen2.5:7b-instruct`) instead of a hosted API. The only fully-implemented
capability today is a **class-schedule assistant** for students at
**PTIT (Học viện Công nghệ Bưu chính Viễn thông)**, sourced from the
university's **UIS** web portal (`uis.ptithcm.edu.vn`), with a one-way sync
into a **Notion database** so the schedule shows up in Notion Calendar.

The repo's folder names (`ingestion/`, `notes/`, `source/vector_source.py`)
make clear the intended scope is much bigger than schedules — an "all-purpose"
assistant that eventually ingests email, messenger chats, and notes, and
retrieves over them with a vector store. Right now, all of that beyond the
schedule pipeline is **stubbed out (empty files)**.

### Elevator pitch of the working slice

1. A Playwright script logs into UIS, sniffs the auth headers off a normal
   page request, and replays them against the internal schedule API to pull
   the current semester's timetable as JSON.
2. That JSON is normalized into a `source/schedule_source.py` module exposing
   four Ollama-compatible **tool functions**: get a day's classes, find free
   periods in a day, summarize a whole week, and sync/resync to Notion.
3. `main.py` runs a CLI chat loop: user message → a small deterministic date
   parser rewrites relative Vietnamese dates ("mai", "tuần sau", …) into
   explicit ISO dates → sent to the local model with the tool list →
   model calls a tool → Python executes it against the local schedule JSON →
   result is fed back to the model → final natural-language answer.
4. Every turn (raw input, resolved input, tool calls + results, final answer)
   is appended to a JSONL log, explicitly earmarked for **future fine-tuning /
   retraining** of the local model.

---

## 2. Repository layout

```
MPA/
├── main.py                     # CLI chat loop + Ollama request/response orchestration
├── config.py                   # semester-code logic, paths, Ollama endpoint/model
├── date_resolver.py            # deterministic Vietnamese relative-date parser
├── registry.py                 # aggregates tool sources, dispatches tool calls
├── logger_setup.py             # stdout tee-logging + JSONL turn logging
├── .env.example                # UIS_USERNAME / UIS_PASSWORD / NOTION_TOKEN / NOTION_SCHEDULE_DB_ID
├── .gitignore                  # ignores .venv, .idea, data/, .env
│
├── ingestion/
│   ├── schedule_fetch.py       # Playwright login + header-sniffing UIS scraper (implemented)
│   ├── email_ingest.py         # empty stub
│   ├── messenger_ingest.py     # empty stub
│   └── notes_ingest.py         # empty stub
│
├── source/
│   ├── schedule_source.py      # schedule data access + Ollama tool definitions (implemented)
│   └── vector_source.py        # empty stub (intended: RAG / vector retrieval source)
│
├── sync/
│   └── notion_schedule_sync.py # upserts normalized sessions into a Notion database (implemented)
│
├── workflows/
│   └── resync_schedule.py      # orchestrates fetch_schedule -> sync_to_notion end-to-end
│
├── notes/
│   └── notion_source.py        # empty stub (intended: pull notes *from* Notion, not just push)
│
├── tests/
│   └── test.py                 # scratch/exploratory script for a direct (non-Playwright) UIS login attempt
│
├── sample_data/
│   └── sample_source.json      # empty — placeholder for example fixture data
│
└── __pycache__/, */__pycache__/  # committed bytecode caches (should be gitignored, see §6)
```

Data produced at runtime (fetched schedules, logs) lives under a `data/`
directory that is correctly excluded via `.gitignore` — none of it is in the
repo, which is good hygiene but also means the project can't be evaluated
without running the fetch pipeline first.

---

## 3. Component-by-component analysis

### `config.py` — semester detection & paths
Computes PTIT's semester code (`nhhk`, e.g. `20261`) from the current date
using the academic calendar convention (Aug–Dec = HK1, Jan–Jun = HK2 of the
previous year), and raises deliberately in July (summer term) rather than
guessing — with an `UIS_SEMESTER_OVERRIDE` env escape hatch. This also drives
the schedule JSON's filename (`data/tkb_<nhhk>.json`), so the whole pipeline
auto-rotates to a new semester without code changes. `OLLAMA_URL` and `MODEL`
(`qwen2.5:7b-instruct`) are hardcoded here rather than pulled from env/config
file.

### `date_resolver.py` — deterministic date math, not model math
The most carefully-documented file in the repo. Its docstring explains the
*why* directly: testing showed `qwen2.5:7b-instruct` miscalculates chained
relative-date expressions (its example: "3 hôm nữa của 5 tuần kế" landing
~11 days off) and sometimes fabricates a fake tool-call/response in plain
text rather than invoking a real tool when the reasoning chain is too long.
The fix is to **never let the model do date arithmetic**: this module
pattern-matches Vietnamese relative-date phrases ("hôm nay", "mai", "hôm
qua", "ngày kia", "N hôm nữa", "tuần này/sau/trước", "cuối tuần", plus one
explicitly-scoped compound pattern "N hôm nữa của M tuần sau") in pure
Python/regex, and appends a pre-computed `[Đã tính sẵn: ...]` annotation to
the user's message before it ever reaches the model. Ambiguous compounds
outside the one confirmed pattern are intentionally left unresolved so the
model asks the user to clarify instead of silently guessing — a sound design
call given the failure mode being defended against.

### `source/schedule_source.py` — the actual schedule logic + tool schema
Loads the semester's JSON, builds a period-number → (start-time, end-time)
lookup, and exposes:
- `schedule_get_day(date)` — classes on one date
- `schedule_find_free_slot(date)` — unbooked periods on one date
- `schedule_get_week_summary(week_offset)` — a full Mon–Sun week, explicitly
  meant to replace repeated per-day calls for "what's free next week"-style
  questions (the docstring tells the model to prefer this tool for that case)
- `schedule_sync_to_notion()` / `schedule_resync()` — trigger the Notion sync
  or the full fetch+sync pipeline as callable tools

Also defines the four/five `TOOLS` schemas (Ollama function-calling format)
and a `dispatch()` used by `registry.py`. Week-of-Monday math is computed
in Python from `date.today()`, consistent with the "don't trust the model
with dates" principle from `date_resolver.py`.

### `ingestion/schedule_fetch.py` — UIS scraping via Playwright
Rather than reverse-engineering UIS's auth flow, it launches a real
(headless) Chromium session, logs in through the actual login form, and
**passively sniffs** the auth headers off the first request UIS itself makes
to the target schedule API (`w-locdstkbtuanusertheohocky`). It then replays
that endpoint with a custom semester filter via `page.evaluate(fetch(...))`,
using the browser's live session rather than trying to hand-roll a token
flow in Python. Strips connection-level headers before replay, retries by
raising a descriptive `RuntimeError` if login or header-capture fails, and
computes the "current week" locally by comparing today's date against each
week's real start/end dates. `run_fetch_and_save()` is the reusable
entrypoint other modules call; the file is also directly runnable as a CLI
script.

### `sync/notion_schedule_sync.py` — idempotent Notion upsert
Builds a stable `SyncKey` per class session (`md5(id_tkb|ngay)`) so re-running
sync is idempotent: it queries Notion for an existing page with that key and
either patches or creates. Requests carry a small retry wrapper for transient
`ConnectionError`s and a fixed inter-request delay to stay under Notion's
rate limits. Timestamps are hardcoded to `+07:00` (Vietnam time). Skips
sessions flagged `is_nghi_day` (a day off/holiday). `sync_all()` returns a
structured summary (created/updated/skipped/failed counts, first 5 errors)
that flows straight back to the LLM as a tool result.

### `workflows/resync_schedule.py` — the two-stage pipeline
Thin orchestrator: `run_fetch_and_save()` then, only if that succeeds,
`notion_schedule_sync.sync_all()`, logging each stage via a dedicated
resync logger. This is what the `schedule_resync` tool calls, and it's also
clearly intended to be wired into a scheduled task (Windows Task Scheduler,
per the docstring) so the calendar refreshes without user interaction.

### `logger_setup.py` — three separate logging concerns
1. **Session log** (`data/session_log.txt`) — a `_Tee` class mirrors every
   `stdout`/`stderr` write to both the terminal and a file, so a CLI session
   is fully replayable.
2. **Resync log** (`data/resync_log.txt`) — timestamped lines for the fetch→
   sync pipeline specifically.
3. **Data log** (`data/data_log.jsonl`) — structured, one-JSON-object-per-line
   record of every chat turn (raw message, date-resolved message, tool calls
   with arguments/results, final answer). The stated purpose in the code is
   building a dataset **to retrain the local model later** — i.e. this
   project is also collecting its own fine-tuning data as it's used.

All three always append, never truncate, and headers mark session boundaries.

### `registry.py` — pluggable tool source aggregation
Deliberately small: a `SOURCES` list (currently just `schedule_source`),
`all_tools()` concatenates every source's `TOOLS` schema for the Ollama
payload, and `dispatch()` routes a tool call by name to whichever source
declares it. The commented-out imports (`vector_source`, `notion_source`)
show exactly how new capabilities are meant to be plugged in once those
stub files are implemented — no other file needs to change.

### `main.py` — the orchestration loop
Builds the system message + tool-augmented request, sends to Ollama, and if
the model responds with `tool_calls`, executes them all via `registry.dispatch`,
appends `role: tool` results, and makes a **second** model call for the final
answer — the standard two-round tool-calling pattern. Logs every turn via
`logger_setup.log_turn`. Also contains the CLI entrypoint (`while True` input
loop with `exit`/`quit`).

**This file is currently broken.** `_build_system_message()` and
`_strip_system_messages(history)` have no real bodies — they contain only a
comment (`# ... giữ nguyên toàn bộ, không đổi ...`, i.e. "unchanged, kept as
is") where an implementation should be. As committed, this is a Python
`IndentationError`/`SyntaxError` at import time — the file cannot run at all
until those two functions are filled in. This looks like content lost in an
edit/merge rather than an intentional stub (unlike the genuinely-empty files
in `ingestion/`/`notes/`, which are `0` bytes and clearly placeholders).
`main.py` also uses `traceback` inside `chat()` without importing it at
module scope (it's only imported inside the `if __name__ == "__main__"` block),
so the error-handling branch around `registry.dispatch` would itself raise
`NameError` if `chat()` is invoked from anywhere other than the CLI block.

### `tests/test.py` — exploratory script, not a test suite
Despite the name/location, this isn't a `pytest`/`unittest` test — it's a
scratch attempt at a **direct HTTP login** to UIS (via `httpx`) as an
alternative to the Playwright approach, with comments noting the request
shape is unconfirmed ("cần xác nhận URL thật"). It's disconnected from the
rest of the app (no imports from it elsewhere) and appears to predate/explore
around the Playwright solution that `ingestion/schedule_fetch.py` ultimately
shipped with.

### Empty stub files
`ingestion/email_ingest.py`, `ingestion/messenger_ingest.py`,
`ingestion/notes_ingest.py`, `notes/notion_source.py`, `source/vector_source.py`,
and `sample_data/sample_source.json` are all `0` bytes. They establish the
architecture's intended shape (multi-source ingestion feeding a vector-search
source, notes read *from* Notion) but contain no code yet.

---

## 4. Data & control flow (schedule Q&A path)

```
User (CLI) ──▶ main.py:chat()
                 │
                 ├─▶ date_resolver.resolve_relative_dates()   (pure Python date math)
                 │
                 ├─▶ Ollama /api/chat  (qwen2.5:7b-instruct, + registry.all_tools())
                 │        │
                 │        └─ model may emit tool_calls
                 │
                 ├─▶ registry.dispatch(tool_name, args)
                 │        └─▶ source/schedule_source.py  (reads data/tkb_<nhhk>.json)
                 │              or  sync/notion_schedule_sync.sync_all()
                 │              or  workflows/resync_schedule.run_full_resync()
                 │                     ├─▶ ingestion/schedule_fetch.py  (Playwright → UIS)
                 │                     └─▶ sync/notion_schedule_sync.py (→ Notion API)
                 │
                 ├─▶ Ollama /api/chat  (second call, with tool results appended)
                 │
                 └─▶ logger_setup.log_turn()  → data/data_log.jsonl
```

---

## 5. Setup (as inferred from the code — not independently verified)

1. **Install Ollama locally** and pull the model referenced in `config.py`:
   ```bash
   ollama pull qwen2.5:7b-instruct
   ```
2. **Python dependencies** (no `requirements.txt` is committed; inferred from
   imports across the codebase): `requests`, `python-dotenv`, `playwright`
   (plus `playwright install chromium`), `httpx` (used only by `tests/test.py`).
3. **Environment variables** — copy `.env.example` to `.env` and fill in:
   ```
   UIS_USERNAME=
   UIS_PASSWORD=
   NOTION_TOKEN=
   NOTION_SCHEDULE_DB_ID=
   ```
4. **Notion database schema** must match the properties
   `sync/notion_schedule_sync.py` writes to: `Tên môn` (title), `Ngày` (date,
   with start/end), `Phòng` (rich text), `Lớp` (rich text), `Giảng viên`
   (rich text), `SyncKey` (rich text) — the database has to be created with
   these exact property names beforehand.
5. **Fetch a schedule first**: `python -m ingestion.schedule_fetch` (or via
   the `schedule_resync` tool) before any schedule Q&A can work, since
   `schedule_source.py` reads a semester JSON file that only the fetch step
   produces.
---
