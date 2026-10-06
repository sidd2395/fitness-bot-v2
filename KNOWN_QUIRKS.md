# Known quirks

- Nadia gets a check-in invitation in most replies before her first check-in.
  Accepted; revisit if real users complain.
- resolve_note can fire before the user answers the follow-up question.
  Invisible to users; revisit if follow-ups start feeling cut off.
- Struggling users sometimes still get a question (Sam's quitting reply ends
  "What's making the nights so short right now?") although coach.md says no
  questions when struggling, and the coach guesses causes ("Kids make that
  hard"). Style; revisit if real users find it pushy.
- A message being processed when the server stops never gets a reply (it stays
  status=received). Revisit before real users: Railway restarts on every deploy.
- The one-line trainer acknowledgement at the end of onboarding often runs to
  two sentences (lena: "Your nutritionist will keep an eye on the food and
  weight side. I'll help you stay consistent..."). Code keeps it to one line
  with no question. Style; revisit if it reads long on a phone.
- The injury reminder sometimes repeats within a day although the context
  line says it was already given ("keeping half an eye on that back"). rohan
  checks it as a warning, not a failure.
- Trip timing is sometimes stated wrong although the note shows its status in
  code (rohan, trip started yesterday: "heading into Thailand this weekend").
  rohan checks it as a warning, not a failure.
