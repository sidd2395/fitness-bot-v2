# Running Coach Bob yourself

You need Python 3.12 (production runs 3.12), an Anthropic API key, and a Telegram bot token from BotFather.

```bash
git clone https://github.com/sidd2395/fitness-bot-v2.git
cd fitness-bot-v2
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your Anthropic key, Telegram bot token and Telegram user id
alembic upgrade head          # create the database tables
python run_polling.py         # talk to your bot locally (not for a deployed bot)
python test_local.py --only tom   # run one test persona
```

`ALLOWED_TELEGRAM_IDS` in `.env` must include your Telegram user id, or the bot answers nobody.

More test options (`--only code` for the free code checks, `--quick`, `--list`) are in `CLAUDE.md` under "How to run".

Deploying to Railway is covered in [`DEPLOY.md`](../DEPLOY.md).
