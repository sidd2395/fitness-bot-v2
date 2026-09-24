# Coach Reyes

A multi-user agentic fitness coach on Telegram. Built with the raw Anthropic SDK
(no LangChain), SQLAlchemy and Alembic. FastAPI arrives with the Telegram webhook
in phase 2 and isn't in requirements.txt yet.

## File map

- `app/agent/loop.py`: the agent loop. Short-term memory, onboarding with forced
  `save_profile`, coaching loop, safety net, empty-reply handling, style cleanup,
  fixed replies (welcome, blocked, all set). Models come from `MODEL_ONBOARDING`
  and `MODEL_COACH`.
- `app/agent/tools.py`: `log_checkin` and `save_profile` schemas and handlers.
  Range checks, number words, pounds to kg, correction guard, under-18 block.
- `app/agent/context.py`: system prompt. Static part (coach.md, tool rules,
  onboarding rules) is cached. The per-turn block comes after it.
- `app/agent/stats.py`: numbers computed in code for the context block.
- `app/agent/prompts/coach.md`: the coach's voice.
- `app/db/`: models, session, `delete_user`.
- `alembic/versions/`: migrations. The test DB is built from these.
- `test_local.py`: persona tests with real model calls, against `test.db`.

## How to run

- `python3 test_local.py`: every persona, Haiku onboarding plus Sonnet coaching,
  written to `test_output_split.txt`
- `--only <persona>`: one persona. `--list`: list personas.
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

Phase 1, the local agent, is built. The last fix hasn't been checked by a test
run yet:
- The reply joins all text from every response in the turn
- The safety net runs before the final reply, and the model sees its result
- Tom's back/surgery warning must survive into the reply
- Arjun's reply must never offer to save 820

## Next: phase 2

- Telegram webhook (FastAPI) with a webhook secret
- Railway plus Postgres, Singapore region
- Consent message before onboarding
- `/delete` and `/mydata` commands
- Rate limit, and a daily cap of 40 turns per user
- Evening check-in
