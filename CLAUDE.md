# Coach Bob

A multi-user agentic fitness coach on Telegram. Built with the raw Anthropic SDK
(no LangChain), SQLAlchemy, Alembic and FastAPI (the Telegram webhook).

## File map

- `app/agent/loop.py`: the agent loop. Short-term memory, onboarding with forced
  `save_profile`, coaching loop, safety net, empty-reply handling, style cleanup,
  fixed replies (welcome, blocked, all set). Models come from `MODEL_ONBOARDING`
  and `MODEL_COACH`.
- `app/agent/tools.py`: `log_checkin`, `save_profile`, `remember`,
  `resolve_note` and `get_history` (up to 60 days; the context block only has
  3) schemas and handlers. Range checks, number words, pounds to kg,
  correction guard, under-18 block, motivation fallback, notes cap (30 open).
  Onboarding is `ONBOARDING_STEPS` (8) questions; never hard-code the count.
- `app/agent/context.py`: system prompt. Static part (coach.md, tool rules,
  onboarding rules) is cached. The per-turn block comes after it.
- `app/agent/stats.py`: numbers computed in code for the context block, and
  milestones (reached in code, stored in `milestones` so each fires once).
  Also the 7-day trend, "weight steady for 3 weeks", and rationed tips (one
  every 3 days, each kind once), stored in `nudges` as they're handed over.
- `app/agent/prompts/coach.md`: the coach's voice.
- `app/capabilities.py`: the user-facing copy of what Coach Bob can and can't do
  (Sid's wording, from docs/drafts/BOB_COPY_DRAFT.md): /help and its four
  button sections, the end-of-onboarding message and its reminder buttons, the
  command menu, and the prompt's "What you can help with". Change it there only.
- `app/pricing.py`: price per million tokens for each model (input, output,
  cache read, cache write). Every model call logs its token counts
  (`event=usage`); `test_local.py` ends with a cost summary from these.
- `app/telegram/handler.py`: `handle_update`, shared by polling and the webhook.
  Allowlist, duplicate update ids (`telegram_updates`), rate limit, text only,
  commands, consent (no user row until "I agree"), daily cap, then `run()`.
  `replies.py` holds its fixed replies, `mydata.py` the /mydata text,
  `summary.py` the /summary list (30-character lines, from `stats.daily_history`,
  the same rows `get_history` returns), `api.py` the Bot API calls and
  message splitting.
- `app/main.py`: FastAPI. `POST /telegram/webhook` (secret header or 401,
  handled in a background task), `GET /health`, migrations on startup.
- `app/logs.py`: JSON logs in prod. Never log message text, replies, names or keys.
- `app/clock.py`: Singapore local time (`now_local`, which tests replace), part
  of day, and midnight for the daily cap.
- `app/db/`: models (incl. `notes`, `milestones`), session (`database_url()`
  converts Railway's postgres://), `delete_user`, `migrate.upgrade_head`.
- `alembic/versions/`: migrations. The test DB is built from these.
- `test_local.py`: persona tests with real model calls, against `test.db`.
  Every run appends a row to `eval_runs.csv` (committed): time, commit (+dirty),
  models, coach.md hash, per-check results, totals and cost.

## How to run

- `python3 test_local.py`: every persona, Sonnet for onboarding and coaching
  (`MODEL_ONBOARDING`, `MODEL_COACH`), written to `test_output_split.txt`
- `--only <persona> [<persona> ...]`: only those personas. `--only code`: code-level checks only, no
  model calls. `--list`: list personas.
- `--model haiku|sonnet|<model id>`: one model for everything, written to
  `test_output_<model>.txt`
- `python3 -m alembic upgrade head`: migrate `fitness.db`
- `python3 run_polling.py`: the bot on Telegram over long polling, local db.
  Removes any webhook; `python3 scripts/set_webhook.py <https url>` puts it back.
- Railway: see DEPLOY.md (variables, webhook, admin scripts, the gate before
  every push). Production runs Python 3.12 (`.python-version`); test with 3.12
  too, since Railpack doesn't support 3.9.
- `python3 scripts/user_data.py --chat <id> --count | --delete`: row counts per
  table, or delete one user. Never prints content.
- `python3 scripts/export_transcript.py [--user N | --chat ID] [--anonymise]`

## Rules

- Never commit `.env` or any database file.
- `coach.md` is the only source for the coach's voice. Don't put tone or
  persona text in code. `capabilities.py` is the only list of what he offers.
- Safety rules live in code, not the prompt: the under-18 block (fixed reply, no
  model call, data deleted, nothing stored), check-in range checks, and the
  forced `log_checkin` safety net. The prompt can explain them, never replace them.
- Targets are the person's or their coach's, never the coach's suggestion:
  code saves one only on a yes to our question naming a number they said
  first, and the calorie floor comes before that.
- Never trust a confirmation flag the model sets. After onboarding, saved profile
  values change only when the user's own message backs it up (`_EVIDENCE` in
  tools.py); `is_correction` needs correction words or a yes to our question.

## Working rules

- After a change, run only the personas it touches (`--only`), without
  asking. They make real, paid API calls, so never more than that. Read the
  transcript yourself.
- On a failure, decide first: bot bug or test bug. Max 2 fix attempts, then
  stop and report.
- Report in 20 lines max: what changed, pass rate, new failures with the exact
  reply quoted and your verdict, run cost.
- Hard-rule checks must pass. No word-matching checks for style; log style
  issues in `KNOWN_QUIRKS.md`.
- Full suite only before a deploy or when asked. No new features during a fix
  batch; ideas go in `IDEAS.md`.

## Current state

Phase 1 is built and passed its last full run, 187/187. Since then the
short-sleep run is computed in code (sam 22/22), and the onboarding fixes:
an active issue is saved once, a described trainer or coach is saved and
acknowledged, several goals at once save none, no promises to message first
(new persona lena; onboarding personas and tom pass). Then the 6 Oct fixes:
local time and part of day in the context block, once-a-day injury
reminders tracked in code, note start/end dates with status computed in
code (migration 009), and "they check in with you" in coach.md (new persona
rohan; rohan, tom, lena, maya, nadia pass). Then get_history, the rule never
to call data missing without it, and /summary [days] (new persona kim). Then
the profile learns from chat: trainer saved whenever mentioned (not locked),
sports added, calorie/protein/water targets saved after a yes to our question
about a number they said first, with targets_set_by (migration 010; new
persona dev).

Phase 2, part 1 is built and passes the code-level checks, but hasn't been
tried on a phone yet: Telegram layer, polling, webhook, allowlist, consent,
/help /mydata /delete, 40 turns a day, 2s rate limit, JSON logs, Postgres URL.
Migrations and delete_user are checked against a real Postgres (pgserver).

## Next: phase 2

- Try it on a phone with polling, then deploy: Railway plus Postgres,
  Singapore region, `TZ=Asia/Singapore` (check-in dates use the server's
  local date)
- Evening check-in
- `/mydata` must include notes, motivation and milestones, and `/delete` must
  wipe them (the ORM cascade in `delete_user` already covers notes and
  milestones; keep it that way)
