# Usability test kit (P1 exit criterion: 8-10 users)

Two weeks, following `ux-research.md` > "How to validate this in two weeks", but on the real app
(staging) instead of a prototype. You run the sessions; this kit has everything else.

## Before you start
- [ ] Staging URL with real AI (`ANTHROPIC_API_KEY`), Clerk sign-in, reminders via SMTP.
- [ ] Reset staging data between participants (each signs up with their own email).
- [ ] Consent form signed (below). Recording only with consent; store recordings privately and
      delete them after synthesis [DECISION: within N days].
- [ ] Incentive ready [DECISION: amount/voucher].

## Who (8-10 people)
Working professionals with an interview in the next 1-4 weeks, mixed by industry and seniority;
at least 3 on phones; at least 2 who are wary of uploading a resume. Recruit via LinkedIn, alumni
networks or a career coach. Screener: "Do you have a job interview booked in the next month?",
"How do you prepare today?", "Phone or computer?".

## Week 1: 30-minute interviews (no product)
How do you prepare today? What did you do last time, step by step? Where did you get stuck?
What have you tried (ChatGPT, courses, mentors)? What did you trust or not trust, and why? How
would you feel about uploading your resume to a new tool? What would make you pay?
Listen for: whether "what does this role need vs what my resume proves" comes up unprompted.

## Week 2: 30-minute sessions on staging
Ask them to think aloud. Don't help unless they're stuck for over a minute; note where.
1. **Gap report:** "Use your real resume and a job ad you care about. What does this role need,
   and what's your biggest gap?" (Activation target: report in under 3 minutes.)
2. **Explain a ranking:** "Why is the top skill ranked first? Do you agree?"
3. **Sign up and keep it:** "Save this so you can come back." (Google/LinkedIn/email.)
4. **Learn from a document:** "Upload something you're studying, ask it a question, and check
   where the answer came from." (Watch for the citation click.)
5. **Today:** "You have 15 minutes. Start today's session." Answer one question; "What does the
   feedback tell you?"
6. **Trust and control:** "Where would you delete all your data? Turn on reminders, but not after 9pm."
7. **Wrap-up (2 min):** SUS questionnaire; "What would stop you using this next week?"

## Observation sheet (one per task)
| Task | Completed? (yes / with help / no) | Time | Hesitations / misreadings (quote) | Severity (1 cosmetic ... 4 blocker) |
|---|---|---|---|---|

## After the sessions
- Metrics: task success per task, time-to-gap-report, SUS mean, number of severity 3-4 issues.
- One findings document: each hypothesis in `ux-research.md` > Experiments confirmed / overturned
  / unclear, with quotes; then a prioritised change list (severity x frequency).
- Feed product changes into the next build wave; feed AI-quality issues (wrong answers, bad
  questions) into `backend/evals/private/` cases and `python -m app.tools.flag_report`.

## Consent form (template, needs legal review)
I agree to take part in a usability study of Mindmesh run by [DECISION: entity]. I understand
that: the session lasts about 30 minutes; it [is / is not] recorded (screen and voice); I can stop
at any time without giving a reason and still receive the incentive; anything I upload is used
only for this study and deleted afterwards [DECISION: when]; quotes may be used anonymously in
internal findings. Name, date, signature.
