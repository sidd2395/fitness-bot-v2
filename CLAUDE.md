# Coach Bob

A multi-user agentic fitness coach on Telegram. Built with the raw Anthropic SDK
(no LangChain), SQLAlchemy, Alembic and FastAPI (the Telegram webhook).

## File map

- `app/agent/loop.py`: the agent loop. Short-term memory, onboarding with forced
  `save_profile`, coaching loop, safety net, empty-reply handling, style cleanup,
  fixed replies (welcome, blocked, all set). Models come from `MODEL_ONBOARDING`
  and `MODEL_COACH`.
- `app/agent/tools.py`: `log_checkin`, `save_profile`, `remember` and
  `resolve_note` schemas and handlers. Range checks, number words, pounds to kg,
  correction guard, under-18 block, motivation fallback, notes cap (30 open).
  Onboarding is `ONBOARDING_STEPS` (8) questions; never hard-code the count.
- `app/agent/context.py`: system prompt. Static part (coach.md, tool rules,
  onboarding rules) is cached. The per-turn block comes after it.
- `app/agent/stats.py`: numbers computed in code for the context block, and
  milestones (reached in code, stored in `milestones` so each fires once).
- `app/agent/prompts/coach.md`: the coach's voice.
- `app/pricing.py`: price per million tokens for each model (input, output,
  cache read, cache write). Every model call logs its token counts
  (`event=usage`); `test_local.py` ends with a cost summary from these.
- `app/telegram/handler.py`: `handle_update`, shared by polling and the webhook.
  Allowlist, duplicate update ids (`telegram_updates`), rate limit, text only,
  commands, consent (no user row until "I agree"), daily cap, then `run()`.
  `replies.py` holds its fixed replies, `mydata.py` the /mydata text, `api.py`
  the Bot API calls and message splitting.
- `app/main.py`: FastAPI. `POST /telegram/webhook` (secret header or 401,
  handled in a background task), `GET /health`, migrations on startup.
- `app/logs.py`: JSON logs in prod. Never log message text, replies, names or keys.
- `app/db/`: models (incl. `notes`, `milestones`), session (`database_url()`
  converts Railway's postgres://), `delete_user`, `migrate.upgrade_head`.
- `alembic/versions/`: migrations. The test DB is built from these.
- `test_local.py`: persona tests with real model calls, against `test.db`.

## How to run

- `python3 test_local.py`: every persona, Haiku onboarding plus Sonnet coaching,
  written to `test_output_split.txt`
- `--only <persona> [<persona> ...]`: only those personas. `--only code`: code-level checks only, no
  model calls. `--list`: list personas.
- `--model haiku|sonnet|<model id>`: one model for everything, written to
  `test_output_<model>.txt`
- `python3 -m alembic upgrade head`: migrate `fitness.db`
- `python3 run_polling.py`: the bot on Telegram over long polling, local db.
  Removes any webhook; `python3 scripts/set_webhook.py <https url>` puts it back.
- Railway: `railway.json` runs `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## Rules

- Never commit `.env` or any database file.
- `coach.md` is the only source for the coach's voice. Don't put tone or
  persona text in code.
- Safety rules live in code, not the prompt: the under-18 block (fixed reply, no
  model call, data deleted, nothing stored), check-in range checks, and the
  forced `log_checkin` safety net. The prompt can explain them, never replace them.
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
short-sleep run is computed in code (sam 22/22).

Phase 2, part 1 is built and passes the code-level checks, but hasn't been
tried on a phone yet: Telegram layer, polling, webhook, allowlist, consent,
/help /mydata /delete, 40 turns a day, 2s rate limit, JSON logs, Postgres URL.
Not yet checked against a real Postgres.

## Next: phase 2

- Try it on a phone with polling, then deploy: Railway plus Postgres,
  Singapore region, `TZ=Asia/Singapore` (check-in dates use the server's
  local date)
- Evening check-in
- `/mydata` must include notes, motivation and milestones, and `/delete` must
  wipe them (the ORM cascade in `delete_user` already covers notes and
  milestones; keep it that way)
