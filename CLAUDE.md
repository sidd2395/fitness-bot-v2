# Coach Reyes

A multi-user agentic fitness coach on Telegram. Built with the raw Anthropic SDK
(no LangChain), SQLAlchemy and Alembic. FastAPI arrives with the Telegram webhook
in phase 2 and isn't in requirements.txt yet.

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
- `app/db/`: models (incl. `notes`, `milestones`), session, `delete_user`.
- `alembic/versions/`: migrations. The test DB is built from these.
- `test_local.py`: persona tests with real model calls, against `test.db`.

## How to run

- `python3 test_local.py`: every persona, Haiku onboarding plus Sonnet coaching,
  written to `test_output_split.txt`
- `--only <persona>`: one persona. `--only code`: code-level checks only, no
  model calls. `--list`: list personas.
- `--model haiku|sonnet|<model id>`: one model for everything, written to
  `test_output_<model>.txt`
- `python3 -m alembic upgrade head`: migrate `fitness.db`

## Rules

- Don't run the persona tests unless asked. They make real, paid API calls.
- Never commit `.env` or any database file.
- `coach.md` is the only source for the coach's voice. Don't put tone or
  persona text in code.
- Safety rules live in code, not the prompt: the under-18 block (fixed reply, no
  model call, data deleted, nothing stored), check-in range checks, and the
  forced `log_checkin` safety net. The prompt can explain them, never replace them.

## Current state

Phase 1, the local agent, is built, plus the personal-coaching batch:
motivation question, notes (remember / resolve_note with follow-ups),
milestones, and length matching in coach.md. Not yet checked by a full
persona run:
- Explicit corrections save at once; a bare new value needs a yes
- A check-in is asked for at most once a day, never in reply to small talk
- maya (notes and follow-up) and sam (motivation under pressure) personas
- Short replies must never cut a safety point (Tom's back warning)

## Next: phase 2

- Telegram webhook (FastAPI) with a webhook secret
- Railway plus Postgres, Singapore region
- Consent message before onboarding
- `/delete` and `/mydata` commands
- Rate limit, and a daily cap of 40 turns per user
- Evening check-in
- `/mydata` must include notes, motivation and milestones, and `/delete` must
  wipe them (the ORM cascade in `delete_user` already covers notes and
  milestones; keep it that way)
