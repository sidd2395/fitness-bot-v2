"""What Coach Bob can and can't do, in the words users see: the one source. /help
(main text, four buttons and their sections), the end-of-onboarding message,
the Telegram command menu and the prompt's "What you can help with" are all
built from it, so they never disagree. The wording is Sid's
(docs/drafts/BOB_COPY_DRAFT.md); change it here, nowhere else.
"""

# /help: the main text, then one button per section. Each section is sent as
# its own message when its button is tapped. Sections hold no questions.
HELP_MAIN = (
    "How to get the most out of Bob.\n\n"
    "Text me like you'd text a mate who coaches you. Rough is fine, any order.\n"
    "The more you tell me, the better I get at this.\n\n"
    "Tap one:"
)

# key: (button label, section text). The key is the button's callback data.
HELP_SECTIONS = {
    "send": ("What to send",
             "Anything about your day, in any order:\n"
             "• Weight: 82.4, 82.4kg or 181lb\n"
             "• Sleep: slept 6h, or slept like crap\n"
             "• Training: legs, 5k easy, muay thai 1hr, rest day\n"
             "• Energy: energy 3/5, or wrecked\n"
             "• Food: chicken rice for lunch. No calorie counting needed\n\n"
             "All at once is fine: \"81.9 slept 7h legs today energy 4\"\n\n"
             "Mornings: weight and sleep. Evenings: training, food, how you felt.\n"
             "Got a number wrong: \"actually it was 81.5\" fixes it.\n"
             "Missed a day: just send today's."),
    "tell": ("Things to tell me",
             "Tell me about life, not just numbers. I'll remember and work around it:\n"
             "• Injuries: my knee's been sore since Tuesday\n"
             "• Feeling sick: down with flu. I'll ease off and check on you\n"
             "• Trips: Bali from the 12th to the 18th. I'll go quiet and check in when you're back\n"
             "• Events: wedding on Saturday. I'll help you plan around it\n"
             "• Targets: my protein target is 140g. Yours or your coach's, I'll track it\n"
             "• Your trainer: my PT is Jake\n"
             "• Changes: I want to build muscle now\n\n"
             "And ask me things:\n"
             "• what's a good lunch at a hawker centre\n"
             "• hotel gym only, give me a workout\n"
             "• how's my weight trending\n"
             "• I'm losing motivation"),
    "most": ("Getting the most out",
             "1. Check in most days, even the rough ones. A bad-day log tells me more than "
             "a skipped one.\n"
             "2. Weigh in the morning, after the toilet, before food. Same time each day.\n"
             "3. Tell me the why. Short sleep because of a deadline is different from short "
             "sleep because of a baby.\n"
             "4. Tell me before life happens: trips, sick days, crazy weeks at work.\n"
             "5. Watch the weekly trend, not the daily number. /summary once a week is plenty."),
    "commands": ("Commands & privacy",
                 "/summary: your last 14 days. /summary 30 for more. Forward it to your trainer.\n"
                 "/reminders: change, pause or turn off my check-ins.\n"
                 "/mydata: everything I hold about you.\n"
                 "/delete: erase all of it.\n\n"
                 "I won't write multi-week programmes, make up calorie targets, or give medical "
                 "advice. I'm an AI, not a doctor."),
}

# End of onboarding, with the three reminder buttons (label, reminders setting)
ALL_SET = (
    "You're in. Text me like you'd text a mate who coaches you: rough is fine, "
    "any order. Try \"82kg slept 7h legs today\". /help shows everything you can "
    "tell me.\n\n"
    "One last thing. Want me to check in each day? I'll message at 10am and 9pm, "
    "only if I haven't heard from you, and I'll ease off if you're busy or away."
)
ALL_SET_BUTTONS = [("Morning and night", "both"), ("Just mornings", "morning"), ("No thanks", "off")]

# What he won't do: verb phrases, so they read after "You won't"
WONT = [
    "write multi-week training programmes",
    "make up calorie or macro targets",
    "give medical or rehab advice",
]

# Telegram command menu (setMyCommands): command -> one-line description
COMMANDS = {
    "help": "What Coach Bob can do",
    "summary": "Your recent check-ins, to send a trainer",
    "reminders": "Change, pause or turn off check-ins",
    "mydata": "Everything Coach Bob holds about you",
    "delete": "Erase all your data",
}


def help_text() -> str:
    return HELP_MAIN


def help_buttons() -> list:
    """Two rows of two: (label, callback data)."""
    keys = list(HELP_SECTIONS)
    return [[(HELP_SECTIONS[k][0], f"help:{k}") for k in keys[i:i + 2]] for i in range(0, len(keys), 2)]


def help_section(key: str):
    section = HELP_SECTIONS.get(key)
    return section[1] if section else None


def all_set_text() -> str:
    return ALL_SET


def prompt_text() -> str:
    """For the system prompt: what to answer when they ask what you can do. The
    same sections /help shows, so the coach's answer matches the buttons."""
    lines = ["# What you can help with",
             "",
             "When they ask what you can do, or seem unsure, answer from this in your own "
             "words, briefly, with an example or two. Don't recite it. It's what /help shows "
             "them, so you can also point them to /help.",
             ""]
    for label, text in HELP_SECTIONS.values():
        lines += [f"## {label}", text, ""]
    lines += ["You won't: " + "; ".join(WONT) + ". Targets they or their coach give, you keep track of.",
              "Whenever you say no to something, offer the closest thing you can do."]
    return "\n".join(lines)
