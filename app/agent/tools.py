import re
from datetime import date, datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from app.db.models import Checkin, Issue, Note, Profile, RawMessage, User
from app.agent.stats import (HISTORY_MAX_DAYS, claim_milestone, compute as compute_stats,
                             daily_history, describe_sleep_run, lead_with_trend, note_end, note_timing,
                             weight_change_since_last, weight_trend)

CALORIE_FLOOR = {"M": 1500, "F": 1200}

# Plausible ranges for check-in numbers. Anything outside is rejected in code
# and handed back to the model to ask about, never saved.
CHECKIN_RANGES = {
    "weight_kg":   (25, 300,  "kg"),
    "sleep_hours": (0,  16,   "h"),
    "energy":      (1,  5,    ""),
    "calories":    (0,  8000, "kcal"),
}

LB_TO_KG = 0.4536
ADULT_AGE = 18
NOTE_MAX_CHARS = 200
MAX_OPEN_NOTES = 30
FOLLOW_UP_MAX_DAYS = 365
GOALS = ("lose_fat", "build_muscle", "perform", "feel_better")

_WEIGHT_DESCRIPTION = (
    "The number exactly as the user gave it. Do not convert: if they gave pounds, "
    "set weight_unit to lb and code converts."
)
_WEIGHT_UNIT = {"type": "string", "enum": ["kg", "lb"], "description": "Unit the user gave. Omit if unclear."}

TOOL_SCHEMAS = [
    {
        "name": "log_checkin",
        "description": (
            "Save a morning or evening check-in. Use whenever the person reports how they "
            "are doing today or yesterday, even if only one value is given. "
            "Do not use when they are only asking about the past."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "is_checkin": {
                    "type": "boolean",
                    "description": (
                        "True only if the message reports check-in data (weight, sleep, training, "
                        "energy, food or water), or confirms a correction to it. False for requests, "
                        "questions and chat, e.g. 'set my calories to 1000 a day' is a request, not "
                        "a check-in. If false, nothing is saved."
                    ),
                },
                "entry_type": {
                    "type": "string",
                    "enum": ["morning", "evening"],
                },
                "date": {
                    "type": "string",
                    "enum": ["today", "yesterday"],
                    "description": "Omit to default to today.",
                },
                "weight_kg":   {"type": "number", "description": _WEIGHT_DESCRIPTION},
                "weight_unit": _WEIGHT_UNIT,
                "sleep_hours": {"type": "number"},
                "training":    {"type": "string", "description": "What they trained or plan to train."},
                "energy": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "description": (
                        "Subjective energy, 1–5. Infer from words when no number is given: "
                        "exhausted or wrecked = 1, tired or flat = 2, okay = 3, good = 4, great = 5."
                    ),
                },
                "calories":  {"type": "integer", "description": "Only a number they gave. Never estimate."},
                "protein_g": {"type": "number", "description": "Only a number they gave. Never estimate."},
                "food_note": {
                    "type": "string",
                    "description": (
                        "What they ate, in their own words, when they describe food without "
                        "numbers: 'ate lighter', 'big dinner out', 'skipped lunch'. Short. Never "
                        "turn it into calories or protein."
                    ),
                },
                "water_l":   {"type": "number"},
                "is_correction": {
                    "type": "boolean",
                    "description": (
                        "Set true when the user explicitly corrects a value already logged "
                        "today ('actually 63.0 not 63.2', 'sorry I meant 7h'), or says yes to "
                        "your question about changing it. A new value with no sign of a "
                        "correction is not a correction: leave this out."
                    ),
                },
            },
            "required": ["is_checkin", "entry_type"],
        },
    },
    {
        "name": "save_profile",
        "description": (
            "Save lasting information: name, age, sex, goal, start weight, injuries, "
            "calorie/protein targets, disciplines, or trainer. Use during onboarding and "
            "when the user updates their profile. Not for daily numbers, use log_checkin for those. "
            "Leave out any field the user did not answer. After onboarding, a saved value only "
            "changes if the person's message explicitly says so; code checks the message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "First name only."},
                "age": {
                    "type": ["integer", "string"],
                    "description": "As the user gave it. Words like 'twenty seven' are fine, code converts.",
                },
                "sex":  {"type": "string", "enum": ["M", "F"]},
                "goal": {
                    "type": "string",
                    "enum": ["lose_fat", "build_muscle", "perform", "feel_better"],
                },
                "start_weight":     {"type": "number", "description": "Current weight. " + _WEIGHT_DESCRIPTION},
                "weight_unit":      _WEIGHT_UNIT,
                "disciplines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": ("Sports or kinds of training they do, e.g. ['gym', 'Muay Thai']. "
                                    "Added to what's saved, so pass only new ones."),
                },
                "calorie_target":   {"type": "integer", "description": "Daily calories, theirs or their coach's. Never one you suggest."},
                "protein_target_g": {"type": "integer", "description": "Daily protein in grams, theirs or their coach's."},
                "water_target_l":   {"type": "number", "description": "Daily water in litres, theirs or their coach's."},
                "targets_set_by": {
                    "type": "string", "enum": ["user", "coach"],
                    "description": "Whose targets these are: the person's own, or their coach's or trainer's.",
                },
                "issue": {
                    "type": "string",
                    "description": (
                        "An injury or health condition. Pass an empty string only if the user said "
                        "they have none. That is how the injuries question is marked answered."
                    ),
                },
                "trainer_name": {
                    "type": "string",
                    "description": (
                        "Who coaches them or keeps them accountable: a trainer, coach, or anyone "
                        "who tracks their training or food. Their name, or a short description "
                        "if there's no name (e.g. 'accountability coach who tracks food and "
                        "weight'). Pass an empty string only if they said they have no one."
                    ),
                },
                "motivation": {
                    "type": "string",
                    "description": (
                        "What made them want to start now, shortened to a few words in their own "
                        "words, e.g. 'keep up with my kids'. Any answer counts. Pass an empty "
                        "string if they aren't sure."
                    ),
                },
            },
        },
    },
    {
        "name": "remember",
        "description": (
            "Save something about the person that will matter in later conversations: "
            "schedule, travel, events, likes and dislikes, work or family context that "
            "affects training. Not check-in numbers (log_checkin) and not injuries or "
            "health issues (save_profile issue). One fact per note, under 200 characters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Short and specific, e.g. 'Work trip to Tokyo 5 to 9 Oct, hotel gym only'.",
                },
                "follow_up_on": {
                    "type": "string",
                    "description": (
                        "YYYY-MM-DD. The day to ask how it went, if it's worth asking about: "
                        "usually the day after an event or trip ends. Work it out from "
                        "today's date in the context block. Omit if there's nothing to follow up."
                    ),
                },
                "starts_on": {
                    "type": "string",
                    "description": (
                        "YYYY-MM-DD. For a trip or event with dates: the first day. Work it out "
                        "from today's date. Code uses it to say whether it's upcoming, happening "
                        "now or over. Omit for notes without dates."
                    ),
                },
                "ends_on": {
                    "type": "string",
                    "description": "YYYY-MM-DD. The last day of the trip or event. Omit for a one-day event.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "get_history",
        "description": (
            "Their check-ins over the last N days (max 60), one row per day: weight, sleep, "
            "training, energy, calories, protein, water, plus active issues. The context block "
            "only shows the last 3 days. Call this before saying anything about older days, and "
            "always before saying something wasn't logged."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "description": "How many days back, today included. 1 to 60."}},
            "required": ["days"],
        },
    },
    {
        "name": "resolve_note",
        "description": (
            "Mark a note as done: its follow-up has been asked about, or it's no longer true. "
            "Use the id shown in brackets in the context block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"note_id": {"type": "integer"}},
            "required": ["note_id"],
        },
    },
]


def dispatch(name: str, inp: dict, user_id: int, raw_msg_id: int, db: Session) -> dict:
    if name == "log_checkin":
        return _log_checkin(inp, user_id, raw_msg_id, db)
    if name == "save_profile":
        return _save_profile(inp, user_id, raw_msg_id, db)
    if name == "remember":
        return _remember(inp, user_id, db)
    if name == "resolve_note":
        return _resolve_note(inp, user_id, db)
    if name == "get_history":
        return _get_history(inp, user_id, db)
    return {"error": f"unknown tool: {name}"}


def is_adult(age: Optional[int]) -> bool:
    """None never passes: an unknown age is not an adult age."""
    return age is not None and age >= ADULT_AGE


# ---------------------------------------------------------------------------
# Number parsing: "27", "twenty seven", "twenty-seven", "180 lbs"
# ---------------------------------------------------------------------------

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_LB_RE = re.compile(r"\b(lbs?|pounds?)\b", re.I)


def parse_number(value) -> Optional[float]:
    """A number from an int, a float, a digit string or English number words. None if unreadable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[a-z]*", text)
    if m:
        return float(m.group(1))
    words = [w for w in re.split(r"[\s-]+", text) if w and w != "and"]
    if not words:
        return None
    total = current = 0
    for w in words:
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred" and current:
            current *= 100
        else:
            return None
    return float(total + current)


def _to_kg(value, unit: Optional[str], raw_body: str) -> Optional[float]:
    """Weight in kg. Converts when the unit is lb, or when the model left the unit out,
    the raw message says lb or pounds and the number is the one the user typed."""
    if isinstance(value, str) and _LB_RE.search(value):
        unit = "lb"
    number = parse_number(value)
    if number is None:
        return None
    if unit is None and _LB_RE.search(raw_body):
        typed = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw_body)]
        if any(abs(number - n) < 0.01 for n in typed):
            unit = "lb"
    if unit == "lb":
        number *= LB_TO_KG
    return round(number, 1)


# ---------------------------------------------------------------------------
# log_checkin
# ---------------------------------------------------------------------------

def _check_range(field: str, value) -> Optional[str]:
    """Return a rejection reason if value is outside CHECKIN_RANGES, else None."""
    lo, hi, unit = CHECKIN_RANGES[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{value!r} is not a number."
    if not lo <= value <= hi:
        return (
            f"{value}{unit} is outside the plausible range of {lo} to {hi}{unit}. "
            "Not saved. Ask the user what they meant."
        )
    return None


# A value that clashes with one already saved today only changes when the user
# signalled it in this message: an explicit correction ("actually 63.0 not 63.2",
# "sorry I meant 7h") or a yes to the confirmation question. The model setting
# is_correction is not enough on its own.
_CORRECTION_RE = re.compile(
    r"\b(actually|meant|i mean|sorry|oops|typo|wrong|mistake|correction|misread)\b|\bnot\s+\d",
    re.I,
)
_YES_RE = re.compile(
    r"^\W*(y|yes|yeah|yep|yup|ya|yas|sure|ok|okay|correct|right|please|do it|go ahead|update it)\b",
    re.I,
)


def _signals_correction(raw_body: str, we_asked: bool) -> bool:
    """An explicit correction in their words, or a yes to a question we asked."""
    return bool(_CORRECTION_RE.search(raw_body) or (we_asked and _YES_RE.match(raw_body)))


def _last_reply_asked(user_id: int, raw_msg_id: int, db: Session) -> bool:
    """Whether our previous reply to this user ended in a question."""
    prev = (
        db.query(RawMessage.reply_text)
        .filter(RawMessage.user_id == user_id, RawMessage.id < raw_msg_id,
                RawMessage.reply_text.isnot(None))
        .order_by(RawMessage.id.desc())
        .first()
    )
    return bool(prev and "?" in prev.reply_text)


_TEXT_STOP = {"the", "and", "today", "with", "did", "had", "was", "for", "this", "that", "too", "day",
              "session", "some", "bit", "got", "went", "then", "later", "earlier", "plus"}


def _shares_word(value: str, message: str) -> bool:
    """At least half the value's words are in the message: "legs" from "legs
    today" passes, "Muay Thai (with Dan earlier)" from a message naming Dan doesn't."""
    words = set(re.findall(r"[a-z]{3,}", value.lower())) - _TEXT_STOP
    if not words:
        return True
    found = sum(1 for w in words if re.search(rf"\b{re.escape(w)}", message, re.I))
    return found * 2 >= len(words)


def only_from_message(inp: dict, message: str) -> tuple[dict, list]:
    """For a check-in the safety net forced: keep only values found in this
    message, so nothing said earlier is logged again under it. Numbers must
    appear in it; training and food text must be mostly its words. Energy is
    read from words like "tired", so it stays."""
    kept, dropped = dict(inp), []
    for field in ("weight_kg", "sleep_hours", "calories", "protein_g", "water_l"):
        if kept.get(field) is not None and not _says_number(message, kept[field]):
            dropped.append(field)
            del kept[field]
    for field in ("training", "food_note"):
        if kept.get(field) and not _shares_word(str(kept[field]), message):
            dropped.append(field)
            del kept[field]
    return kept, dropped


def _log_checkin(inp: dict, user_id: int, raw_msg_id: int, db: Session) -> dict:
    user = db.get(User, user_id)
    if not _onboarded(user):
        return _NOT_ONBOARDED

    # Missing counts as false: a check-in has to be declared, so a forced call on a
    # request like "set my calories to 1000" saves nothing
    if not inp.get("is_checkin"):
        return {"saved": False, "reason": "Not a check-in, nothing saved."}

    today = date.today()
    target_date = today if inp.get("date", "today") == "today" else today - timedelta(days=1)
    entry_type = inp["entry_type"]

    DATA_FIELDS = ("weight_kg", "sleep_hours", "training", "energy", "calories", "protein_g", "water_l",
                   "food_note")
    NUDGE_FIELDS = ("weight_kg", "sleep_hours")
    # Weight and sleep happen once a day, so a value in the day's other entry
    # (morning vs evening) counts as already saved. Energy, training and food
    # can differ between morning and evening.
    ONCE_A_DAY = ("weight_kg", "sleep_hours")

    raw_msg = db.get(RawMessage, raw_msg_id)
    raw_body = raw_msg.body if raw_msg else ""
    is_correction = (bool(inp.get("is_correction"))
                     and _signals_correction(raw_body, _last_reply_asked(user_id, raw_msg_id, db)))

    inp = dict(inp)
    rejected: dict = {}
    if inp.get("weight_kg") is not None:
        kg = _to_kg(inp["weight_kg"], inp.get("weight_unit"), raw_body)
        if kg is None:
            rejected["weight_kg"] = f"{inp['weight_kg']!r} is not a number."
            del inp["weight_kg"]
        else:
            inp["weight_kg"] = kg

    # Food numbers only come from them. "Big dinner out" is a food_note, never an
    # estimate in calories; a yes to a correction can carry a number from before.
    for field in ("calories", "protein_g"):
        if inp.get(field) is not None and not is_correction and not _says_number(raw_body, inp[field]):
            rejected[field] = ("Not in their message, so not saved. Only save food numbers they "
                               "give; describe what they ate in food_note instead.")
            del inp[field]
    if inp.get("food_note"):
        inp["food_note"] = " ".join(str(inp["food_note"]).split())[:NOTE_MAX_CHARS]

    # Range checks before anything else: rejected values are dropped from the input
    for field in CHECKIN_RANGES:
        if field in inp and inp[field] is not None:
            reason = _check_range(field, inp[field])
            if reason:
                rejected[field] = reason
                del inp[field]

    same_day = (
        db.query(Checkin)
        .filter(Checkin.user_id == user_id, Checkin.date == target_date)
        .all()
    )
    existing = next((c for c in same_day if c.entry_type == entry_type), None)

    def holder(field: str) -> Optional[Checkin]:
        """The row holding today's value for this field, if there is one."""
        if existing is not None and getattr(existing, field) is not None:
            return existing
        if field in ONCE_A_DAY:
            return next((c for c in same_day if getattr(c, field) is not None), None)
        return None

    # Never overwrite a value that is already there unless the user corrected it
    # or said yes to the change. Empty fields can still be filled in.
    needs_confirmation: dict = {}
    elsewhere: dict = {}   # corrections to a value held in the day's other entry
    for field in DATA_FIELDS:
        new = inp.get(field)
        row = holder(field) if new is not None else None
        if row is None:
            continue
        old = getattr(row, field)
        if _same(old, new):
            if row is not existing:
                del inp[field]
            continue
        if not is_correction:
            needs_confirmation[field] = {"logged": old, "new": new}
            del inp[field]
        elif row is not existing:
            elsewhere[field] = (row, new)
            del inp[field]

    to_write = {f: inp[f] for f in DATA_FIELDS if inp.get(f) is not None}
    if existing:
        to_write = {f: v for f, v in to_write.items() if not _same(getattr(existing, f), v)}

    if not to_write and not elsewhere:
        # Nothing new to save; don't create or touch a row
        result = {"saved": False, "date": str(target_date), "entry_type": entry_type}
        if same_day and not rejected and not needs_confirmation:
            result["already_logged"] = True
        _add_refusals(result, rejected, needs_confirmation)
        return result

    for field, (row, value) in elsewhere.items():
        setattr(row, field, value)
        row.corrected_at = datetime.utcnow()
        row.raw_message = raw_body

    if not to_write:
        checkin = next(iter(elsewhere.values()))[0]
    elif existing:
        overwritten = [f for f in to_write if getattr(existing, f) is not None]
        for field, value in to_write.items():
            setattr(existing, field, value)
        if overwritten:
            existing.corrected_at = datetime.utcnow()
            existing.raw_message = raw_body
        checkin = existing
    else:
        checkin = Checkin(
            user_id=user_id,
            date=target_date,
            entry_type=entry_type,
            raw_message=raw_body,
            **to_write,
        )
        db.add(checkin)
        same_day.append(checkin)

    db.flush()  # populate checkin_id before linking

    # Read from the row, not the input, so a correction that only changes one
    # field doesn't report the untouched fields as missing. Rejected fields are
    # reported under "rejected" instead.
    fields_saved   = list(to_write) + list(elsewhere)
    fields_missing = [f for f in NUDGE_FIELDS
                      if all(getattr(c, f) is None for c in same_day) and f not in rejected]

    # Record what the model is about to remind them about, so the context block
    # can list it under "Fields already reminded about today" and the bot never asks twice
    if fields_missing:
        nudged = set(filter(None, (checkin.nudged_fields or "").split(",")))
        checkin.nudged_fields = ",".join(sorted(nudged | set(fields_missing)))

    if raw_msg:
        raw_msg.checkin_id = checkin.checkin_id
        raw_msg.status = "processed"

    db.commit()

    stats = compute_stats(user_id, db, today)
    # The raw run stays in code; the model gets the one wording of it
    sleep_run = stats.pop("sleep_run")
    stats.pop("short_sleep_streak")
    milestone = claim_milestone(user_id, db, today)

    result = {
        "saved": True,
        "date": str(target_date),
        "entry_type": entry_type,
        "fields_saved": fields_saved,
        "fields_missing": fields_missing,
        **stats,
    }
    if milestone:
        # With an active issue there's usually a safety point to make first, so the
        # ordering rule goes where the model reads the milestone
        if any(i.status == "active" for i in user.issues):
            result["milestone_today"] = (f"{milestone}. Mention it once, briefly, at the END of "
                                         "the reply, after any safety point.")
        else:
            result["milestone_today"] = f"{milestone}. Mention it once, briefly."
    # Weight saved: the change since the previous weigh-in and the 7-day trend,
    # computed here
    if "weight_kg" in fields_saved:
        change = weight_change_since_last(user_id, db, target_date)
        if change:
            result["weight_change"] = change
        else:
            result["weight_change"] = "first weigh-in, no earlier weight to compare"
        goal = user.profile.goal if user.profile else None
        trend = weight_trend(user_id, db, target_date, goal)
        if trend:
            result["trend"] = trend["in_words"]
            lead = lead_with_trend(change, trend, goal)
            if lead:
                result["lead_with_trend"] = lead
    # Sleep saved: the short-sleep run, counted here so the model never counts nights
    if "sleep_hours" in fields_saved:
        result["sleep_run"] = (describe_sleep_run(sleep_run)
                               or "no short-sleep run: the latest night was 6h or more")
    _add_refusals(result, rejected, needs_confirmation)
    return result


def _same(old, new) -> bool:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(old - new) < 1e-6
    return old == new


def _add_refusals(result: dict, rejected: dict, needs_confirmation: dict) -> None:
    if rejected:
        result["rejected"] = rejected
    if needs_confirmation:
        result["needs_confirmation"] = needs_confirmation
        result["message"] = (
            "These fields already have a value today and were NOT changed, because the "
            "message didn't say it was a correction. Your whole reply is one short yes/no "
            "question naming the new value, like 'Update today's weight to 63.0?'. No other "
            "question and nothing before it. Only after they say yes, "
            "call log_checkin again with the new value and is_correction=true."
        )


# ---------------------------------------------------------------------------
# save_profile
# ---------------------------------------------------------------------------

ONBOARDING_LABELS = {
    0: "name",
    1: "age and sex",
    2: "sex",
    3: "current weight",
    4: "main goal",
    5: "why they're starting now",
    6: "injuries or health issues",
    7: "trainer",
}
# onboarding_step == ONBOARDING_STEPS means onboarding is complete
ONBOARDING_STEPS = len(ONBOARDING_LABELS)

_NOT_ONBOARDED = {
    "saved": False,
    "error": (
        "Onboarding is not complete, so nothing can be saved yet. Nothing was "
        "saved. Tell them you need a couple of details first, then ask the next "
        "onboarding question."
    ),
}


def _onboarded(user: User) -> bool:
    return not user.blocked and user.onboarding_step >= ONBOARDING_STEPS and is_adult(user.age)


_SEX_WORDS = {
    "m": "M", "male": "M", "man": "M", "guy": "M",
    "f": "F", "female": "F", "woman": "F", "girl": "F",
}


def _profile(user: User, db: Session) -> Profile:
    # Created on first use, so a user blocked at the age question never gets one
    if user.profile is None:
        user.profile = Profile(user_id=user.user_id)
        db.add(user.profile)
    return user.profile


_LOCKED = (
    "{field} is already saved and this message doesn't say to change it. Not changed. "
    "Don't ask them about it; it only changes when they bring it up themselves."
)


def _numbers(text: str) -> list[float]:
    """Every number in the text: digits ("94", "94.5") and number words ("sixteen")."""
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)   # 2,200 -> 2200
    found = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    # Longest first, whole words only, so "sixteen" isn't read as "six"
    words = "|".join(sorted(list(_UNITS) + list(_TENS) + ["hundred"], key=len, reverse=True))
    for run in re.findall(rf"\b(?:(?:{words})\b[\s-]*)+", text.lower()):
        n = parse_number(run.strip(" -"))
        if n is not None:
            found.append(n)
    return found


def _says_number(text: str, value) -> bool:
    n = parse_number(value)
    return n is not None and any(abs(n - x) < 0.05 for x in _numbers(text))


def _mentions(pattern: str):
    return lambda text: bool(re.search(pattern, text, re.I))


_START_WEIGHT_WORDS = _mentions(r"\b(start(ing|ed)?|original(ly)?|initial|first|signed up|joined)\b")
_AGE_WORDS = _mentions(r"\b(i'?m|i am|age|aged|turned|turning|years? old|birthday)\b")
_GOAL_CHANGE_WORDS = _mentions(r"\b(goal|focus|switch\w*|chang\w*|instead|rather|actually|now|aim)\b")

# What the user's own message must contain before a saved value can change
# after onboarding. Targets (confirmed with a yes) and the trainer (not locked)
# are handled on their own. Each takes (raw message, new value as the user gave it).
_EVIDENCE = {
    "name": lambda raw, v: bool(re.search(r"\b(name|call me|i'?m called|go by)\b", raw, re.I))
                           and str(v).lower() in raw.lower(),
    "age": lambda raw, v: _AGE_WORDS(raw) and _says_number(raw, v),
    "sex": lambda raw, v: bool(re.search(r"\b(sex|gender|male|female|man|woman)\b", raw, re.I)),
    "start_weight": lambda raw, v: _START_WEIGHT_WORDS(raw) and _says_number(raw, v),
    "goal": lambda raw, v: _GOAL_CHANGE_WORDS(raw)
                           and bool(re.search(rf"\b({_GOAL_WORDS[v]})\b", raw, re.I)),
    "motivation": lambda raw, v: bool(re.search(
        r"\b(reason|why i (started|start)|motivat\w*|started because|got me started|what made me)\b", raw, re.I)),
    "disciplines": lambda raw, v: any(str(d).lower() in raw.lower() for d in v),
}


# Words that name each goal. An answer maps to a goal only if it names exactly one.
_GOAL_WORDS = {
    "lose_fat":     r"lose|losing|fat|weight loss|lean|leaner|slim|cut|shred|drop",
    "build_muscle": r"muscle|muscles|jacked|bulk|build|gain|swole|bigger|stronger|strength",
    "perform":      r"perform|performance|race|racing|compete|competition|sport|faster|endurance|athletic",
    "feel_better":  r"feel|health|healthier|healthy|energy|wellbeing|mood",
}


def parse_goal(value) -> Optional[str]:
    """One of GOALS from an enum value or natural language; None if unclear."""
    text = str(value or "").strip().lower()
    key = re.sub(r"[\s-]+", "_", text)
    if key in GOALS:
        return key
    if key in ("perform_better", "performance"):
        return "perform"
    hits = [g for g, words in _GOAL_WORDS.items() if re.search(rf"\b({words})\b", text)]
    return hits[0] if len(hits) == 1 else None


def _block_minor(user: User, db: Session) -> None:
    """Under 18: delete everything we hold about them, including every message they
    sent (the current one too). Only the user row with telegram_chat_id and
    blocked=true is kept, so they stay blocked."""
    if user.profile is not None:
        db.delete(user.profile)
    for row in (list(user.raw_messages) + list(user.issues) + list(user.checkins)
                + list(user.notes) + list(user.milestones)):
        db.delete(row)
    user.name = user.age = user.sex = user.trainer_name = None
    user.consent_given_at = None
    user.blocked = True
    db.commit()
    db.refresh(user)


def _save_profile(inp: dict, user_id: int, raw_msg_id: int, db: Session) -> dict:
    user = db.get(User, user_id)
    if user.blocked:
        return {"saved": {}, "onboarding_blocked": True}

    raw_msg = db.get(RawMessage, raw_msg_id)
    raw_body = raw_msg.body if raw_msg else ""

    saved: dict = {}
    refused: dict = {}

    # After onboarding, a saved value is locked: it only changes if this message
    # explicitly talks about that field. Checked against the user's own words,
    # never a flag the model sets.
    onboarded = user.onboarding_step >= ONBOARDING_STEPS

    def locked(field: str, current, new, evidence_value=None) -> bool:
        if not onboarded or current is None or _same(current, new):
            return False
        if _EVIDENCE[field](raw_body, new if evidence_value is None else evidence_value):
            return False
        refused[field] = _LOCKED.format(field=field)
        return True

    # Age first, before anything else is written. While the age question is open and
    # the model passed no age, read a bare answer like "16" or "sixteen" straight
    # from the message, so an under-18 answer is never missed.
    age_in = inp.get("age")
    if age_in in (None, "") and user.onboarding_step == 1:
        # Age and sex share one question, so the answer may be "34, male" or
        # "I'm sixteen": one number in the message is the age
        found = _numbers(raw_body)
        age_in = found[0] if len(found) == 1 else None
    if age_in not in (None, ""):
        age = parse_number(age_in)
        if age is None or age != int(age) or not 0 < age < 120:
            refused["age"] = f"Couldn't read an age from {age_in!r}. Not saved. Ask again."
        elif locked("age", user.age, int(age)):
            pass
        elif not is_adult(int(age)):
            _block_minor(user, db)
            return {"saved": {}, "onboarding_blocked": True}
        else:
            user.age = int(age)
            saved["age"] = user.age

    if inp.get("name"):
        name = inp["name"].strip(" \t!?.,")
        if not name or len(name) > 40 or any(c.isdigit() for c in name):
            refused["name"] = f"{inp['name']!r} doesn't look like a first name. Not saved. Ask again."
        elif locked("name", user.name, name.title() if name.islower() else name, name):
            pass
        else:
            user.name = name.title() if name.islower() else name
            saved["name"] = user.name

    if not inp.get("sex") and user.onboarding_step in (1, 2) and not user.sex:
        # Read from the message when the model left it out ("34, male", "f")
        word = re.search(r"\b(male|female|man|woman|guy|girl|m|f)\b", raw_body, re.I)
        if word:
            inp = {**inp, "sex": word.group(1)}
    if inp.get("sex"):
        sex = _SEX_WORDS.get(str(inp["sex"]).strip().lower())
        if sex is None:
            refused["sex"] = f"{inp['sex']!r} isn't M or F. Not saved. Ask again."
        elif locked("sex", user.sex, sex):
            pass
        else:
            user.sex = sex
            saved["sex"] = sex

    needs_confirmation = _save_targets(inp, user, raw_msg_id, raw_body, onboarded, saved, refused, db)

    # The model may pass "perform better" or leave the goal out of a bare answer
    # like "perform". Code maps it; while the goal question is open, the message
    # itself is read as the answer.
    goal_in = inp.get("goal")
    if user.onboarding_step == 4 and names_several_goals(raw_body):
        # "All of the above", "both", or two goals named: the model must not pick
        # one for them. Ask which matters most.
        refused["goal"] = _SEVERAL_GOALS
        goal_in = None
    elif not goal_in and user.onboarding_step == 4 and "?" not in raw_body:
        goal_in = raw_body if parse_goal(raw_body) else None
    if goal_in:
        goal = parse_goal(goal_in)
        if goal is None:
            refused["goal"] = f"{goal_in!r} is not one of {', '.join(GOALS)}. Not saved. Ask again."
        elif locked("goal", user.profile.goal if user.profile else None, goal):
            pass
        else:
            _profile(user, db).goal = goal
            saved["goal"] = goal

    if inp.get("start_weight") not in (None, ""):
        kg = _to_kg(inp["start_weight"], inp.get("weight_unit"), raw_body)
        reason = _check_range("weight_kg", kg) if kg is not None else "Couldn't read a weight. Not saved. Ask again."
        current = user.profile.start_weight if user.profile else None
        if reason:
            refused["start_weight"] = reason
        elif locked("start_weight", current, kg, inp["start_weight"]):
            pass
        else:
            _profile(user, db).start_weight = kg
            saved["start_weight_kg"] = kg

    # Sports are added to, never replaced. After onboarding each new one has to
    # be named in their message.
    if inp.get("disciplines"):
        current = [d for d in ((user.profile.disciplines if user.profile else None) or "").split(",") if d]
        have = {d.lower() for d in current}
        new = []
        for d in inp["disciplines"]:
            d = " ".join(str(d).split())[:40]
            if not d or d.lower() in have:
                continue
            if onboarded and not _EVIDENCE["disciplines"](raw_body, [d]):
                refused["disciplines"] = f"{d!r} isn't in their message. Not saved."
                continue
            new.append(d)
            have.add(d.lower())
        if new:
            _profile(user, db).disciplines = ",".join(current + new)
            saved["disciplines_added"] = new

    # While the trainer question is open, "nobody" needs a message that says so.
    # If the model passed "" for a message that describes someone, the message
    # itself is the answer, the same fallback as motivation.
    if (user.onboarding_step == 7 and inp.get("trainer_name") == "" and raw_body.strip()
            and "?" not in raw_body and not _NO_TRAINER_RE.fullmatch(raw_body.strip())):
        inp = {**inp, "trainer_name": " ".join(raw_body.split())[:NOTE_MAX_CHARS]}
    if inp.get("trainer_name"):
        inp = {**inp, "trainer_name": " ".join(str(inp["trainer_name"]).split())[:NOTE_MAX_CHARS]}
    # Who coaches them isn't locked: it's saved whenever they mention it. After
    # onboarding an empty value only clears it if their message says so, since
    # the model tends to replay old onboarding answers.
    if (onboarded and inp.get("trainer_name") == ""
            and not re.search(r"\b(no longer|stopped|quit|left|fired|don'?t have|not with|no (more )?(coach|trainer|pt))\b",
                              raw_body, re.I)):
        inp = {k: v for k, v in inp.items() if k != "trainer_name"}
    if "trainer_name" in inp:
        user.trainer_name = inp["trainer_name"] or None
        saved["trainer_name"] = inp["trainer_name"]

    # One row per issue. During onboarding an issue is only taken while the
    # injuries question is open (later saves tend to repeat earlier answers),
    # and an issue already active is never saved again, however it's worded.
    if "issue" in inp and inp["issue"]:
        duplicate = same_active_issue(inp["issue"], user.issues)
        if not onboarded and user.onboarding_step != 6:
            pass
        elif duplicate is not None:
            saved["issue_already_on_file"] = duplicate.what
        else:
            db.add(Issue(user_id=user_id, what=inp["issue"]))
            saved["issue"] = inp["issue"]

    # Any answer to "what made you start now" counts. If the model left it out
    # while that question is open, the message itself is the answer, unless it
    # is a question back to us.
    motivation_answered = "motivation" in inp
    motivation = inp.get("motivation")
    if not motivation_answered and user.onboarding_step == 5 and raw_body.strip() and "?" not in raw_body:
        motivation_answered, motivation = True, raw_body
    if motivation_answered:
        motivation = " ".join(str(motivation or "").split())[:NOTE_MAX_CHARS]
        if _NO_REASON_RE.fullmatch(motivation):
            motivation = ""
        current = user.profile.motivation if user.profile else None
        if not locked("motivation", current, motivation or None):
            _profile(user, db).motivation = motivation or None
            saved["motivation"] = motivation

    # Advance onboarding step past every question whose answer is now saved and valid.
    # Steps 5, 6 and 7 are "asked" steps: they advance when the question was answered,
    # even if the answer was "not sure" or "none".
    profile = user.profile
    step = user.onboarding_step
    while step < ONBOARDING_STEPS:
        if   step == 0 and user.name:
            step = 1
        elif step == 1 and is_adult(user.age):
            step = 2
        elif step == 2 and user.sex:
            step = 3
        elif step == 3 and profile and profile.start_weight:
            step = 4
        elif step == 4 and profile and profile.goal:
            step = 5
        elif step == 5 and motivation_answered:
            step = 6
        elif step == 6 and "issue" in inp:
            step = 7
        elif step == 7 and "trainer_name" in inp:
            step = 8
        else:
            break

    user.onboarding_step = step
    db.commit()

    result = {
        "saved": saved,
        "refused": refused,
        "onboarding_step": step,
        "next_question": ONBOARDING_LABELS.get(step),
        "onboarding_complete": step >= ONBOARDING_STEPS,
    }
    if needs_confirmation:
        result["needs_confirmation"] = needs_confirmation
        result["message"] = _TARGETS_ASK
    return result


# Targets come from the person or their coach, never from us. After onboarding
# they're saved only on a yes to our question naming them, and only if the
# person said the number first. The calorie floor applies before anything else.
_TARGET_FIELDS = {
    # field: (label, unit, plausible range)
    "calorie_target":   ("calories", " cal", (min(CALORIE_FLOOR.values()), 6000)),
    "protein_target_g": ("protein", "g", (20, 400)),
    "water_target_l":   ("water", "L", (0.5, 8)),
}
_TARGETS_ASK = (
    "Targets not saved yet. Ask one yes/no question naming them and whose they are, like "
    "'Want me to save 2200 cal and 160g protein as Dan's targets for you?'. Only after they "
    "say yes, call save_profile again with the same values and targets_set_by."
)
_TARGETS_NOT_THEIRS = (
    "Not saved: targets only come from the person or their coach, in their own words. "
    "Never suggest one."
)


def _save_targets(inp: dict, user: User, raw_msg_id: int, raw_body: str, onboarded: bool,
                  saved: dict, refused: dict, db: Session) -> dict:
    """Saves the targets in inp that pass; returns those waiting on a yes."""
    asked = {}
    confirmed = {}
    for field, (label, unit, (low, high)) in _TARGET_FIELDS.items():
        if inp.get(field) in (None, ""):
            continue
        value = parse_number(inp[field])
        if value is None:
            refused[field] = f"Couldn't read a number from {inp[field]!r}. Not saved."
            continue
        if field == "calorie_target":
            floor = CALORIE_FLOOR.get(user.sex, 1200)  # conservative default when sex unknown
            if value < floor:
                refused[field] = (
                    f"Refused: {value:g} kcal is below the safe minimum of {floor} kcal for "
                    f"{'women' if user.sex == 'F' else 'men'}. Explain this to the user and carry "
                    "on without setting a calorie target."
                )
                continue
        if not low <= value <= high:
            refused[field] = f"{value:g}{unit} isn't a plausible daily {label} target. Not saved."
            continue
        if onboarded:
            said_first = _user_said_number(user.user_id, raw_msg_id, value, db, include_current=True)
            if not said_first:
                refused[field] = _TARGETS_NOT_THEIRS
                continue
            if not (_YES_RE.match(raw_body) and _last_reply_names(user.user_id, raw_msg_id, value, db)
                    and _user_said_number(user.user_id, raw_msg_id, value, db, include_current=False)):
                asked[field] = f"{value:g}{unit}"
                continue
        confirmed[field] = int(value) if field != "water_target_l" else round(value, 1)

    if confirmed:
        profile = _profile(user, db)
        for field, value in confirmed.items():
            setattr(profile, field, value)
            saved[field] = value
        profile.targets_set_by = inp.get("targets_set_by") if inp.get("targets_set_by") in ("user", "coach") else "user"
        saved["targets_set_by"] = profile.targets_set_by
    return asked


def _recent_rows(user_id: int, raw_msg_id: int, db: Session, limit: int = 6) -> list:
    """This user's messages before this one, newest first, from the last 24 hours."""
    return (db.query(RawMessage)
            .filter(RawMessage.user_id == user_id, RawMessage.id < raw_msg_id,
                    RawMessage.created_at >= datetime.utcnow() - timedelta(hours=24))
            .order_by(RawMessage.id.desc())
            .limit(limit)
            .all())


def _user_said_number(user_id: int, raw_msg_id: int, value: float, db: Session,
                      include_current: bool) -> bool:
    bodies = [r.body for r in _recent_rows(user_id, raw_msg_id, db)]
    if include_current:
        current = db.get(RawMessage, raw_msg_id)
        bodies.append(current.body if current else "")
    return any(_says_number(b or "", value) for b in bodies)


def _last_reply_names(user_id: int, raw_msg_id: int, value: float, db: Session) -> bool:
    """Our previous reply asked a question and named this number."""
    rows = [r for r in _recent_rows(user_id, raw_msg_id, db, limit=1) if r.reply_text]
    return bool(rows and "?" in rows[0].reply_text and _says_number(rows[0].reply_text, value))


_NO_TRAINER_RE = re.compile(
    r"(no|nope|nah|none|nobody|no one|not really|n/?a|never|just me|myself|"
    r"(i )?(don'?t|do not) have (one|any|a (personal )?(trainer|coach|pt))|"
    r"no (personal )?(trainer|coach|pt)|not at the moment|not right now|not yet)"
    r"([\s,]+(tbh|really|honestly|lol|haha|yet|atm|at the moment|right now|sadly))*[\s.!]*",
    re.I,
)

_SEVERAL_GOALS = (
    "They picked more than one goal. Not saved. Ask which one matters most to them "
    "right now, in one question. Don't say how the goals relate or that one covers "
    "the others."
)
_ALL_GOALS_RE = re.compile(
    r"\b(all of (the|them|those|it)|all the above|all (four|three|those)|both of (them|those)|"
    r"everything|a mix|mix of|combination of)\b|^\s*(all|both)\b",
    re.I,
)


def names_several_goals(text: str) -> bool:
    """'All of the above', 'both', or two or more goals named in one answer."""
    t = str(text or "")
    if _ALL_GOALS_RE.search(t):
        return True
    return sum(bool(re.search(rf"\b({words})\b", t, re.I)) for words in _GOAL_WORDS.values()) >= 2


_ISSUE_STOP = {"the", "and", "but", "from", "with", "that", "this", "now", "few", "some", "it's", "its",
               "was", "had", "has", "have", "been", "not", "back", "ago", "months", "years", "last",
               "year", "month", "week", "weeks", "certain", "can", "mostly", "bit", "little", "my"}


def _issue_words(text: str) -> set:
    words = set(re.findall(r"[a-z]{3,}", text.lower())) - _ISSUE_STOP
    # "back" is a stop word as in "a few months back", so keep it when it's the body part
    if re.search(r"\b(lower|upper|mid|my|left|right)\s+back\b|\bback\s+(pain|strain|injury|surgery)", text, re.I):
        words.add("back")
    return words


def same_active_issue(text: str, issues) -> Optional["Issue"]:
    """An active issue this text describes again: most of the shorter text's words
    appear in the other. Different wordings of one injury match; a different
    injury to the same body part usually doesn't."""
    new = _issue_words(text)
    for issue in issues:
        if issue.status != "active":
            continue
        old = _issue_words(issue.what)
        if not new or not old:
            if text.strip().lower() == issue.what.strip().lower():
                return issue
            continue
        if len(new & old) / min(len(new), len(old)) >= 0.75:
            return issue
    return None


_NO_REASON_RE = re.compile(
    r"(not (really )?sure|unsure|idk|i don'?t know|dunno|no idea|no reason( really)?|nothing( really)?|"
    r"no|nope|nah|none|n/?a|not really|pass|skip)"
    r"([\s,]+(tbh|really|honestly|lol|haha|yet|atm))*[\s.!]*",
    re.I,
)


# ---------------------------------------------------------------------------
# remember / resolve_note: long-term memory
# ---------------------------------------------------------------------------

# Injuries belong in the issues table, check-in numbers in checkins. Refused
# here so they can't end up in notes instead.
_INJURY_RE = re.compile(
    r"\b(injur\w*|pain\w*|sore\w*|surgery|surgeries|sprain\w*|strain(ed)?|physio\w*|hurts?|"
    r"torn|fractur\w*|tendon\w*|ligament\w*|herniat\w*|disc|sciatica|arthritis|acl|mcl)\b",
    re.I,
)
_NUMBERS_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(kg|kgs|lbs?|pounds|kcal|cals?|calories)\b|\b(weighed|slept)\s+\d",
    re.I,
)


def _remember(inp: dict, user_id: int, db: Session) -> dict:
    user = db.get(User, user_id)
    if not _onboarded(user):
        return _NOT_ONBOARDED

    text = " ".join(str(inp.get("text") or "").split())
    if not text:
        return {"saved": False, "error": "Empty note. Nothing saved."}
    if len(text) > NOTE_MAX_CHARS:
        return {"saved": False, "error": f"Note is {len(text)} characters. Shorten it to under "
                                         f"{NOTE_MAX_CHARS} and call remember again."}
    if _INJURY_RE.search(text):
        return {"saved": False, "error": "Injuries and health issues aren't notes. Not saved. "
                                         "Use save_profile with issue instead."}
    if _NUMBERS_RE.search(text):
        return {"saved": False, "error": "Check-in numbers aren't notes. Not saved. "
                                         "Use log_checkin for those."}

    follow_up_on = None
    if inp.get("follow_up_on"):
        today = date.today()
        try:
            follow_up_on = date.fromisoformat(str(inp["follow_up_on"]))
        except ValueError:
            return {"saved": False, "error": f"follow_up_on {inp['follow_up_on']!r} isn't YYYY-MM-DD. Not saved."}
        if not today <= follow_up_on <= today + timedelta(days=FOLLOW_UP_MAX_DAYS):
            return {"saved": False, "error": (
                f"follow_up_on {follow_up_on} must be between today ({today}) and a year from "
                "now. Not saved. Work it out again from today's date."
            )}

    dates = {}
    for field in ("starts_on", "ends_on"):
        if inp.get(field):
            try:
                dates[field] = date.fromisoformat(str(inp[field]))
            except ValueError:
                return {"saved": False, "error": f"{field} {inp[field]!r} isn't YYYY-MM-DD. Not saved."}
            if abs((dates[field] - date.today()).days) > FOLLOW_UP_MAX_DAYS:
                return {"saved": False, "error": (
                    f"{field} {dates[field]} is more than a year from today ({date.today()}). "
                    "Not saved. Work it out again from today's date."
                )}
    starts_on, ends_on = dates.get("starts_on"), dates.get("ends_on")
    if starts_on and ends_on and ends_on < starts_on:
        return {"saved": False, "error": f"ends_on {ends_on} is before starts_on {starts_on}. Not saved."}

    open_notes = db.query(Note).filter(Note.user_id == user_id, Note.resolved.is_(False)).all()
    if any(n.text.lower() == text.lower() for n in open_notes):
        return {"saved": False, "already_saved": True}
    if len(open_notes) >= MAX_OPEN_NOTES:
        return {"saved": False, "error": (
            f"They already have {MAX_OPEN_NOTES} open notes, the most allowed. Not saved. "
            "Resolve one that no longer matters first."
        )}

    # A dated note always gets a follow-up: the day after it ends, if the model
    # didn't set one (a trip with no end counts as 7 days, see note_end)
    end = note_end(starts_on, ends_on, text)
    if follow_up_on is None and end is not None:
        follow_up_on = end + timedelta(days=1)
    note = Note(user_id=user_id, text=text, follow_up_on=follow_up_on, starts_on=starts_on, ends_on=ends_on)
    db.add(note)
    db.commit()
    result = {"saved": True, "note_id": note.note_id,
              "follow_up_on": str(follow_up_on) if follow_up_on else None}
    timing = note_timing(starts_on, end, date.today())
    if timing:
        result["timing"] = timing
    return result


def _resolve_note(inp: dict, user_id: int, db: Session) -> dict:
    user = db.get(User, user_id)
    if not _onboarded(user):
        return _NOT_ONBOARDED
    note_id = parse_number(inp.get("note_id"))
    note = db.get(Note, int(note_id)) if note_id is not None else None
    # Another user's note looks the same as a missing one
    if note is None or note.user_id != user_id:
        return {"resolved": False, "error": f"No note {inp.get('note_id')!r}. Use an id from the context block."}
    note.resolved = True
    db.commit()
    return {"resolved": True, "note_id": note.note_id}



# ---------------------------------------------------------------------------
# get_history: check-ins beyond the 3 days in the context block
# ---------------------------------------------------------------------------

def _get_history(inp: dict, user_id: int, db: Session) -> dict:
    user = db.get(User, user_id)
    if not _onboarded(user):
        return _NOT_ONBOARDED
    days = parse_number(inp.get("days"))
    if days is None or days < 1:
        return {"error": "days must be a whole number from 1 to 60."}
    days = min(int(days), HISTORY_MAX_DAYS)
    today = date.today()
    rows = daily_history(user_id, db, days, today)
    return {
        "from": str(today - timedelta(days=days - 1)),
        "to": str(today),
        "days_with_checkins": len(rows),
        "checkins": [{k: (str(v) if k == "date" else v) for k, v in r.items() if v is not None}
                     for r in rows],
        "missing_means": ("A day not listed has no check-in. A field left out of a day "
                          "wasn't logged that day. This is the whole record for these days."),
        "active_issues": [i.what for i in user.issues if i.status == "active"],
    }



# ---------------------------------------------------------------------------
# Sports named in a message, added to disciplines in code (the model doesn't
# always call save_profile for "did Muay Thai today")
# ---------------------------------------------------------------------------

SPORTS = {
    "Muay Thai":   r"muay\s*thai|thai\s*boxing",
    "Boxing":      r"(?<!thai )(?<!kick)boxing|boxed",
    "Kickboxing":  r"kick\s*boxing",
    "BJJ":         r"bjj|jiu[\s-]*jitsu|grappling",
    "MMA":         r"mma",
    "Running":     (r"running(?!\s+(late|out|low|behind|errands|around|a\b))|jogg?ing|parkrun|"
                    r"\d+\s*(k|km)\s+(\w+\s+)?run|(easy|long|tempo|morning|evening) run|"
                    r"went for a run|ran \d+\s*(k|km|miles?)"),
    "Cycling":     r"cycling|bike ride|spin class|spinning",
    "Swimming":    r"swimming|swim session|laps in the pool|swam",
    "Gym":         r"gym",
    "Weights":     r"weights|weight\s*lifting|lifting|powerlifting",
    "Yoga":        r"yoga",
    "Pilates":     r"pilates",
    "HIIT":        r"hiit",
    "CrossFit":    r"cross\s*fit",
    "Football":    r"football|futsal|soccer",
    "Badminton":   r"badminton",
    "Tennis":      r"tennis",
    "Squash":      r"squash",
    "Basketball":  r"basketball",
    "Climbing":    r"climbing|bouldering",
    "Rowing":      r"rowing",
    "Hiking":      r"hiking|hike",
    "Dance":       r"dance class|dancing|zumba",
    "Netball":     r"netball",
}
_SPORT_RES = {name: re.compile(rf"\b({pattern})\b", re.I) for name, pattern in SPORTS.items()}


def sports_in(message: str) -> list[str]:
    """Sports and kinds of training named in the message, in SPORTS order."""
    return [name for name, rx in _SPORT_RES.items() if rx.search(message or "")]


def add_sports_from_message(user_id: int, message: str, db: Session) -> list[str]:
    """Adds any sport the message names that isn't saved yet. Returns what was added."""
    found = sports_in(message)
    if not found:
        return []
    user = db.get(User, user_id)
    if user is None or not _onboarded(user):
        return []
    profile = _profile(user, db)
    current = [d for d in (profile.disciplines or "").split(",") if d]
    have = {d.lower() for d in current}
    new = [s for s in found if s.lower() not in have]
    if new:
        profile.disciplines = ",".join(current + new)
        db.commit()
    return new
