"""What Coach Bob can and can't do: the one list. /help, the "all set" message,
the Telegram command menu and the coach's system prompt are all built from it,
so they never disagree. Change what he offers here, nowhere else.

Examples have no question marks: they're sent in fixed replies, which keep to
one question at most like every other reply.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    group: str        # what users can ask, as a heading
    detail: str       # one line on what that covers
    example: str      # a message they could send


CAN = [
    Capability("Log your day", "numbers or plain words, whatever you have",
               "82kg, slept 7h, legs today"),
    Capability("Today's workout", "a session for today, or a hotel or bodyweight one",
               "hotel gym only today, give me a workout"),
    Capability("What to eat or order", "hawker, kopitiam, food court or convenience store",
               "at a hawker centre, what's a good lunch"),
    Capability("A trip or event", "a short plan for the day itself and getting back on track after",
               "wedding on Saturday, help me plan around it"),
    Capability("Your progress", "your 7-day trend, or /summary for a list of check-ins",
               "how's my weight trending"),
    Capability("Sharing with your PT", "/summary gives a list you can forward",
               "/summary 30"),
    Capability("Your data", "/mydata shows everything held about you, /delete erases it",
               "/mydata"),
]

# Verb phrases, so they read after "He won't" and "You won't"
WONT = [
    "write multi-week training programmes",
    "make up calorie or macro targets",
    "give medical or rehab advice",
]

# Telegram command menu (setMyCommands): command -> one-line description
COMMANDS = {
    "help": "What Coach Bob can do",
    "summary": "Your recent check-ins, to send a trainer",
    "mydata": "Everything Coach Bob holds about you",
    "delete": "Erase all your data",
}

# The three things the "all set" message suggests, by group
ALL_SET_TRIES = ("Log your day", "Today's workout", "A trip or event")


def _by_group(group: str) -> Capability:
    return next(c for c in CAN if c.group == group)


def help_text() -> str:
    lines = ["Coach Bob is an AI fitness coach you check in with by text. Tell him how your "
             "day's going, in numbers or plain words, and he keeps track, spots patterns and "
             "gives you one useful thing to focus on.", "", "You can ask him about:"]
    for c in CAN:
        if c.group in ("Sharing with your PT", "Your data"):
            continue  # covered by the commands below
        lines.append(f"• {c.group}: \"{c.example}\"")
    lines += ["", "Nothing is required. Rough is fine.", ""]
    lines += [f"/{cmd}: {desc}" for cmd, desc in COMMANDS.items() if cmd != "help"]
    lines += ["", "He won't " + ", ".join(WONT[:-1]) + ", or " + WONT[-1] + "."]
    return "\n".join(lines)


def all_set_text() -> str:
    lines = ["You're all set. Three things to try:"]
    for group in ALL_SET_TRIES:
        lines.append(f"• {group}: \"{_by_group(group).example}\"")
    lines.append("Type /help anytime.")
    return "\n".join(lines)


def prompt_text() -> str:
    """For the system prompt: what to answer when they ask what you can do."""
    lines = ["# What you can help with",
             "",
             "When they ask what you can do, or seem unsure, answer from this list in "
             "your own words, briefly, with an example or two. Don't recite it.",
             ""]
    for c in CAN:
        lines.append(f"- {c.group}: {c.detail}. e.g. \"{c.example}\"")
    lines += ["", "You won't: " + "; ".join(WONT) + ". Targets they or their coach give, you keep track of.",
              "Whenever you say no to something, offer the closest thing on the list you can do."]
    return "\n".join(lines)
