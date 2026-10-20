# Build log

Every change that came out of testing or real use, newest first. "Fix type"
says where the fix lives: in the prompt, in code, or in a tool result the model
reads. Scores come from `eval_runs.csv` from 7 Oct on, and from test reports
before that.

| When | What we saw | Why | What changed | Fix type | Result |
| --- | --- | --- | --- | --- | --- |
| 8 Oct | A full test run cost ~$0.70 and ran after every fix | Every run replayed all 16 personas | Test what a change could break: free code checks always, safety personas when the prompt changes, the closest personas to the change. Full suite on request | Process | 115/115 for $0.16 on the check-ins release |
| 8 Oct | Would commands like /reminders count as "messaged" and block the 9pm check-in? | Only free-text messages are stored; commands and button taps never reach that code | Confirmed only free-text messages count | Test | Planner test added |
| 8 Oct | Bob could only reply, so the easiest thing to skip was replying | No way to message first | Check-ins at 10am and 9pm, opt-in. Code decides whether to send (logged today? sick? on a trip? quiet for days?), the model only writes the message. Each send is claimed in the database first so a restart can't double-send | Code | Live 8 Oct |
| 8 Oct | Onboarding felt robotic: one bare question per message | Haiku plus a rule of one sentence per message | Onboarding moved to Sonnet; a short reaction before each question; age and sex asked together | Prompt + code | No stock praise, at most one question per message, both checked |
| 7 Oct | Maya's trip follow-up never came | The model sometimes skipped the follow-up date | Code defaults it to the day after the note ends, from one `note_end` function | Code | 313/316 to 317/317 |
| 7 Oct | Bob said "Done, saved as your targets" and nothing was saved | The model claimed an action it never took | Claim guard: a reply that claims a save with no successful save gets one retry, then an honest fallback | Code | 311/315 to 313/316 |
| 7 Oct | No record of which change moved which score | Results lived in chat | Every test run appends a row to `eval_runs.csv`: commit, models, prompt hash, every check | Process | Baseline 311/315 |
| 6 Oct | Bot silent after deploy | Webhook URL had the path twice | Re-set with the domain only | Process | Live |
| 6 Oct | Rohan got the injury reminder twice in a day | Once-a-day rule still flaky | Kept as a warning, not a blocker | Decision | In `KNOWN_QUIRKS.md` |
| 6 Oct | Mei's "no compensation eating" check failed | The check matched "don't skip meals", a negation | Fixed the check | Test fix | The bot was right |
| 6 Oct | Safety net logged training from an earlier message | It read more than the current message | It reads only the current message | Code | Fixed |
| 6 Oct, real use | /mydata showed trainer and sports as "not set" after I'd said them | The profile only filled during onboarding | Profile sync: trainer saved when mentioned, sports picked up by code, targets after the user confirms | Code | Fixed |
| 6 Oct, real use | /summary wrapped on a phone | Table too wide | A list: one block per day, 30 characters a line | Code | Fixed |
| 6 Oct, real use | Bob said my 2 Oct data was never sent, then argued | It only sees the last 3 days and guessed | `get_history` tool, a rule to check before saying anything is missing, /summary built in code | Prompt + code | Now checks first |
| 6 Oct, real use | Said "I check in with you each day" when it couldn't | Nothing stopped the claim | Removed; what Bob can do lives in one file, `capabilities.py` | Prompt | Fixed |
| 6 Oct, real use | Mixed up whether a trip was past or upcoming | The model worked out dates | Note status computed in code | Code | Fixed |
| 6 Oct, real use | "How'd the gym go tonight" at 3:19pm | No clock in the context | Local time added | Code | Fixed |
| 2 Oct, real use | Back issue saved twice; trainer answer lost; promised to message later | No duplicate check; a dropped field; no rule | Duplicate check, field saved, rule against promises | Prompt + code | Fixed |
| First Telegram run | /start got no reply | A timeout passed twice; tests faked the whole Telegram API | Renamed; error logs hide the token | Code | Fixed |
| Run 187/187 | All passed, but a short-sleep count was wrong | The model counted from raw rows | Sleep run computed in code | Code | Fixed |
| Targeted 58/58 | All passed, but a start weight was overwritten | The model sent a `user_confirmed` flag it made up | Profile fields locked in code; model flags never trusted | Code | Fixed |
| Run 172/173 | Tom's safety warning sent twice | Text from every step was sent, drafts included | Only the final text is sent | Code | Fixed |
| Run 172/173 | Priya told "down" when her weight went up | The model did the subtraction | Weight change computed in code, given as a ready-made phrase | Code | Fixed |
| Run 172/173 | Nadia asked for a check-in in 4 replies | Prompt rule ignored | Context line "check-in requested today" | Prompt + code | Partly; accepted |
| Run 152/160 | Kofi's onboarding logged a check-in | Onboarding could call every tool | Only `save_profile` allowed during onboarding, in code | Code | Fixed |
| Run 152/160 | Tom's milestone came before his safety warning | A "safety first" prompt rule, ignored twice | The same instruction moved into the `log_checkin` result | Tool result | Fixed |
| Run 152/160 | "Day two of a streak" | A field named streak counted days logged in 14 | Renamed | Code | Fixed |
| Run 152/160 | Brand new users called struggling | No minimum history | Only after 7 days | Code | Fixed |
| Late Sep | A short-reply rule cut Tom's safety warning | Two prompt rules clashed | "Safety beats brevity" | Prompt | Fixed |
| 25 Sep, 103/104 | Priya's correction check failed | The test was stricter than the product | A clear correction saves; an unmarked clashing number asks first | Decision | Pass |

**Tally:** of the fixes to the bot itself, most live in code. Prompt-only fixes
held for how Bob talks (tone, priorities). They didn't hold for facts: counting,
dates, what was saved, what was already said.
