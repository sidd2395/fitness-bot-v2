# Deploying Coach Bob

Railway, one web service plus Postgres, Singapore region. The build uses
Railpack (set in `railway.json`), which reads the Python version from
`.python-version` (3.12; Railpack supports 3.10 and up). `requirements.txt`
pins every package. Migrations run when the app starts.

## Services

1. New project, region Singapore (Southeast Asia).
2. Add Postgres.
3. Add the web service from this GitHub repo. `railway.json` sets the start
   command (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`), the `/health`
   check and one replica (the rate limiter lives in memory).
4. Settings, Networking: generate a public domain for the web service.

## Variables (web service)

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your Anthropic key |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference to the Postgres service; the app converts it to psycopg) |
| `TELEGRAM_BOT_TOKEN` | from BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | a long random string; the same value goes in your local `.env` for `set_webhook.py` |
| `ALLOWED_TELEGRAM_IDS` | Telegram user ids, comma separated. Empty means nobody gets in. |
| `MODEL_ONBOARDING` | `claude-haiku-4-5-20251001` |
| `MODEL_COACH` | `claude-sonnet-5` |
| `TZ` | `Asia/Singapore` (check-in dates use the server's local date) |
| `LOG_FORMAT` | optional; logs are JSON on Railway anyway (`RAILWAY_ENVIRONMENT` is set there) |

Never put values in this file or in git.

## Point Telegram at the app

From your machine, with `TELEGRAM_BOT_TOKEN` and the same
`TELEGRAM_WEBHOOK_SECRET` in your local `.env`:

```
python3 scripts/set_webhook.py https://<your-domain>.up.railway.app
python3 scripts/set_webhook.py --info        # check it, and see the last error if any
```

`run_polling.py` removes the webhook, so run `set_webhook.py` again after any
local polling session with the same bot.

## Admin scripts against the live database

`user_data.py` prints row counts only. `export_transcript.py` prints a whole
conversation, so use `--anonymise` unless you need the real one.

`railway run` runs the command on your machine with the service's variables,
and your machine can't reach Postgres's private address
(`postgres.railway.internal`). Two ways round it:

**A. `railway run` with the public database URL.** Postgres service, Settings,
Networking, Public Access: this adds a TCP proxy and fills in
`DATABASE_PUBLIC_URL` (egress through it is billed). Both scripts use
`DATABASE_PUBLIC_URL` when it's set. Run with the Postgres service's variables:

```
railway run --service Postgres python3 scripts/user_data.py --chat <chat id> --count
railway run --service Postgres python3 scripts/user_data.py --chat <chat id> --delete
railway run --service Postgres python3 scripts/export_transcript.py --chat <chat id> --anonymise
```

The transcript is written on your machine as `transcript_anon_<n>.txt`
(gitignored). Turn Public Access off again when you're done.

**B. Inside the container, no public database.** `railway ssh` runs a command
in the deployed web service, where the private address resolves:

```
railway ssh --service <web service> -- python3 scripts/user_data.py --chat <chat id> --count
railway ssh --service <web service> -- python3 scripts/export_transcript.py --chat <chat id> --anonymise > transcript_anon_live.txt
```

For `--delete`, open `railway ssh --service <web service>` and run the command
in that shell, since it asks you to type the chat id.

## Before every push

All of these, in order. Stop and fix anything that fails; don't push.

1. `git status` is clean, and nothing secret is tracked:
   `git ls-files | grep -E '(^|/)\.env$|\.db$|transcript_'` prints nothing.
2. Migrations work on a fresh, empty database:
   `rm -f /tmp/fresh.db && DATABASE_URL=sqlite:////tmp/fresh.db python3 -m alembic upgrade head`
   (and on Postgres when one is to hand).
3. The full persona suite passes: `python3 test_local.py`, reported per the
   working rules in CLAUDE.md (pass rate, new failures with the reply quoted
   and a verdict, cost).
4. Then `git push`.
