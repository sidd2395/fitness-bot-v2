"""Fixed Telegram replies, sent from code with no model call."""
from app.capabilities import help_text

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
AFTER_CONSENT = (
    "Good to have you. I'm Bob. A few quick questions so I can coach you properly, "
    "two minutes tops. First up, what should I call you?"
)

NOT_ALLOWED = "Coach Bob is in private beta."
TEXT_ONLY = "I can only read text for now."
SLOW_DOWN = "One at a time please. Give me a second with your last message."
DAILY_CAP = (
    "That's all the messages I can take today. I'll be back after midnight "
    "Singapore time, and everything you've logged is saved."
)
ERROR_REPLY = "Sorry, something went wrong on my side. Try sending that again in a moment."
UNKNOWN_COMMAND = "I don't know that command. /help lists what I can do."

HELP = help_text()

# /reminders and the end-of-onboarding buttons (copy: docs/drafts/BOB_COPY_DRAFT.md)
REMINDERS_STATUS = ("Right now I check in at {when}, only when I haven't heard from you.")
REMINDERS_WHEN = {"both": "10am and 9pm", "morning": "10am", "off": "never"}
REMINDERS_BUTTONS = [[("Morning and night", "remind:both"), ("Just mornings", "remind:morning")],
                     [("Pause 7 days", "remind:pause"), ("Off", "remind:off")]]
REMINDERS_SET = {
    "both": "Done. 10am and 9pm, only if I haven't heard from you.",
    "morning": "Done. Just 10am from now on.",
    "pause": "Paused until {date}. I'll be here if you message before then.",
    "off": "Off. I won't message first. Turn it back on with /reminders anytime.",
}

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
