"""Fixed Telegram replies, sent from code with no model call."""

CONSENT_NOTICE = (
    "Hi, I'm Coach Bob, an AI fitness coach. Send me a quick check-in each day and "
    "I'll help you stay on track.\n\n"
    "Before we start, how your data is used:\n"
    "• I store your profile, check-ins and notes so I can coach you.\n"
    "• Your messages are processed by Anthropic's AI.\n"
    "• /mydata shows everything I hold about you, and /delete erases it.\n"
    "• We may review anonymised conversations to improve Coach Bob.\n"
    "• You need to be 18 or over.\n\n"
    "Tap \"I agree\" to start."
)
AGREE_BUTTON = ("I agree", "consent")
AFTER_CONSENT = "Thanks. To start, what's your first name?"

NOT_ALLOWED = "Coach Bob is in private beta."
TEXT_ONLY = "I can only read text for now."
SLOW_DOWN = "One at a time please. Give me a second with your last message."
DAILY_CAP = (
    "That's all the messages I can take today. I'll be back after midnight "
    "Singapore time, and everything you've logged is saved."
)
ERROR_REPLY = "Sorry, something went wrong on my side. Try sending that again in a moment."
UNKNOWN_COMMAND = "I don't know that command. /help lists what I can do."

HELP = (
    "Coach Bob is an AI fitness coach you check in with by text.\n"
    "Tell him how your day's going and he keeps track of it for you.\n"
    "He spots patterns and gives you one useful thing to focus on.\n\n"
    "Check-ins can look like:\n"
    "• 82kg, slept 7h, legs today\n"
    "• slept badly, skipped gym, ate light\n"
    "• is it ok to train with a sore knee?\n\n"
    "Nothing is required. Rough is fine.\n\n"
    "/summary: your recent check-ins to send a trainer (/summary 30 for 30 days)\n"
    "/mydata: everything Coach Bob holds about you\n"
    "/delete: erase all of it\n\n"
    "He won't write meal plans or training programmes, and he can't give medical advice."
)

DELETE_CONFIRM = (
    "This erases everything I hold about you: your profile, check-ins, notes, "
    "milestones and messages. It can't be undone. Delete everything?"
)
DELETE_BUTTONS = [("Yes, delete everything", "delete_yes"), ("Cancel", "delete_no")]
DELETED = (
    "Done. Everything I held about you is deleted. Send any message if you ever "
    "want to start again."
)
DELETE_CANCELLED = "Cancelled. Nothing was deleted."
NOTHING_HELD = "I don't hold anything about you."
SUMMARY_USAGE = "Send /summary for the last 14 days, or /summary 30 for up to 60 days."
