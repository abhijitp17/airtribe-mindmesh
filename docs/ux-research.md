# Mindmesh UX research: acquisition and retention

Prepared 10 October 2026 for the product lead.

## What this research is, and isn't

This is desk research and an expert review, not user research. It draws on three sources: the PRD, a heuristic review of the current Mindmesh interface (the real Next.js screens and `docs/ui-preview.html`), and established patterns from learning, test-prep and career products. No users have been interviewed or tested yet. That means every recommendation below is a hypothesis with a clear way to test it, and the last section is a plan for doing that cheaply in two weeks. Treat this document as where to start looking, not as findings.

## The one-sentence summary

Mindmesh should win new users with a fast, free interview gap report that needs no account. It should keep them with a daily session sized to the time they actually have, and with progress they can see. Underneath both sits one design idea: every claim the product makes is visibly backed by evidence, which is the thing generic AI chat can't do.

## Who we are designing for first

The PRD names the first segment as working professionals preparing for an interview or learning from their own documents. Three facts about this person shape almost every decision below.

First, they arrive with a deadline. Someone with an interview in nine days doesn't want to explore a platform. They want to know what to do tonight. Urgency is the strongest acquisition lever we have, and also our biggest retention risk, because the need ends when the interview happens.

Second, they're short on time and attention. They'll use the product in 10–20 minute gaps: a commute, a lunch break, an evening after work. Any flow that needs a long, uninterrupted sitting will lose them.

Third, they're anxious and sceptical. They've tried ChatGPT and know it can sound confident and be wrong. They worry about uploading a resume. They don't want to be told they're "62% ready" by a machine. Trust is the product.

## Acquisition: getting the first visit to turn into a user

### Lead with the gap report, not the library

Today a new user lands on a sign-in screen, then an empty library that asks them to upload a PDF. That asks for effort and data before giving anything back. It also leads with the feature that looks most like what competitors offer: "chat with your PDF".

The recommendation is to make the resume + job description gap report the front door. A visitor pastes a job description (or a job link) and their resume, and within about a minute sees the top three to five skills the role needs, what their resume already proves, and the biggest gaps, each with the reason it's ranked where it is. Only then do we ask them to create an account to save it, start a plan, or run a mock interview.

This works for three reasons. It gives real, personal value before signup, which is the most reliable way to raise sign-up conversion. It shows the differentiator immediately: evidence-linked analysis, not generic advice. And it creates a natural next step. A gap report raises the question "so how do I close these?", and the study plan and mock interview are the answer.

Privacy has to be designed into this moment, not bolted on. Before the resume is analysed, show a short, plain note: what is analysed, that it isn't used to train models, and a suggestion to remove a phone number or home address first. For signed-out visitors, keep the analysis in the session only, and say so.

### Make the value visible on the landing page

The landing page should show the product working, not describe it. The strongest single image we have is a tutor answer with a page citation that, when clicked, highlights the exact sentence in the source. That one interaction explains "grounded in your documents" faster than any headline. The second strongest is the skill table with a gap marked "your resume doesn't show this yet". Use real-looking, specific examples (an operations textbook, a program manager role), not abstract illustrations.

### Channels that fit this product

Role-specific landing pages are a natural search channel, because people search for things like "Amazon program manager interview questions" or "supply chain analyst interview prep". Each page can offer the gap report pre-filled with a typical job description for that role. A shareable, privacy-safe artefact helps word of mouth: a one-page "prep plan" a user can send to a mentor or friend, showing skills and plan but never resume content unless the user chooses. Career coaches and university career services are a likely partner channel later, but that's a separate product decision.

### Remove friction from sign-up

Offer Google and LinkedIn sign-in alongside email (the current build only has email and password). Ask for nothing at sign-up that we don't use straight away. Move "level", "study time" and goal questions into the moment they're needed, such as creating a plan.

## Activation: reaching the "this is useful" moment fast

### Define the moment

We should agree on what "activated" means, because it decides what the onboarding optimises for. I'd propose two equivalent activation events: a user receives a gap report on their own resume and a real job, or a user gets a verified, cited answer from their own document and then answers at least one question about it. The target is for a new user to reach one of them within three minutes of arriving.

### Ask for the goal first, then the material

The PRD lists "goal-first vs upload-first" as an experiment, and it's the right one to run first. My hypothesis is goal-first wins for this segment. A single opening question ("What are you preparing for?") with three large choices (an interview, an exam, learning a subject) lets the product tailor everything after it. That includes which material to ask for, how to phrase the plan, and what the home screen shows.

### Fill the processing wait

PDF processing takes time, and today the user just watches a "Processing" badge. That's a dead moment right when interest is highest. As soon as the first pages are ready, offer something useful: a short summary of what the document covers, or three quick questions on chapter one. If it's a large book, say how long it will take and offer to notify them.

### Empty states should be invitations

Every empty screen should say what to do and why it's worth it, in one sentence, with one button. For example, the empty skills area could read: "Take a 5-question quiz and we'll start showing what you know." Avoid empty screens that only state the absence of data.

## Retention: why they come back tomorrow and next month

### Size every session to the time available

The single most important retention pattern for time-poor learners is a session that fits the time they have. The home screen should open on "Today", with a plan already chosen, and let the user say how much time they have right now: 5, 15 or 30 minutes. The product then picks the highest-value mix of review, practice and mock-interview questions for that time. Finishing a session should take one tap and end with a visible change: a skill moving from "not enough evidence" to "developing", or a gap closing.

### Use consistency, not streaks

Daily streaks drive return visits in consumer learning apps, but they also create guilt and anxiety, and the PRD explicitly asks for nudges that are "useful, not guilt-driven". A weekly target that the user sets ("3 sessions a week") gives the same sense of progress without punishing a missed day. Show the week as a simple row of days, filled in where they practised.

### Make progress feel real

Progress is the reward that brings people back, and today it's shown as small grey meters and dense explanation text. It should be the most visually satisfying part of the product. Each skill or concept should show a clear state, and the change between visits should be celebrated briefly ("Little's Law moved to strong"). Keep the honesty the product already has. "Not enough evidence" stays visually distinct from "needs work", and there's never a single percentage that pretends to predict a job offer.

### Plan for the end of the deadline

Interview prep has a built-in ending, and most users will leave when the interview is over unless we design for what comes next. A day after the interview date, ask how it went in one tap (offer, next round, rejected, didn't happen). Then offer the right next step: prepare for the next round with the same skills, start prep for another role and carry over what they've already proven, or turn the gaps they found into a longer learning goal. Carrying a user's proven skills from one goal to the next is the PRD's long-term advantage. This moment is where it becomes visible to the user.

### Reminders that respect the user

Notifications should be opt-in, tied to the user's own plan, and limited to a few kinds: today's session is ready, a review is due, the interview is in three days. Quiet hours and per-goal controls are already in the PRD. A short weekly email summarising progress and next week's focus is likely the most valuable re-engagement channel for professionals who don't want another app nagging them.

### Mobile is a retention feature

Review and short practice happen on phones, in commutes and queues. A mobile layout where "Today" and a single question fill the screen, with large tap targets, matters more for retention than any new feature. Document reading and the full skill table can stay desktop-first.

## What the current interface gets right, and what to change

### Strengths to keep

The product is already honest in a way competitors aren't. Citations are verified and clickable. Answers are labelled "Sources verified" or "Not in your documents". "Not enough evidence" is separated from "needs work". There's a single "next step" with a reason. The UI review fixes (plain-language explanations, short section titles, labelled confidence buttons) moved the copy in the right direction. All of this should survive any redesign.

### Problems found in the heuristic review

The home screen now competes with itself. After slice 2 it shows the next step, Today's sessions, interview prep, the library and the mastery list together. The PRD's own principle is "one clear next action on the home screen", and the current layout breaks it. Recommendation: home becomes "Today" only, with everything else one tap away.

The navigation describes the system, not the user's goals. "Home, Goals, Interview prep, Settings", plus a library reached only from home, mirrors how the code is organised. Recommendation: three destinations, **Today**, **Prep** (roles and goals together) and **Library**, with settings under the profile.

Jargon leaks through. "Mastery", "rubric", "unverified", "needs attention", "recompute" and "regenerate" are engineering words. Recommendation: "What you know", "what a good answer covers", "not enough answers yet", "we couldn't read some pages", "update", "rebuild my plan".

Quizzes show every question on one long page. On a phone this is a long scroll, with feedback far from the question. Recommendation: one question at a time, with feedback in place and a clear "next" step. Keep a summary at the end.

The skill table is dense. Seven columns of information per skill is right for analysis, but it's too much as a first view. Recommendation: lead with three columns (skill, how much it matters, what to do next), and reveal resume evidence, assessed level and priority reasons when a row is opened.

The visual identity doesn't match the brief and reads as generic. The current look is a warm off-white background, a serif display face and a muted green accent. It's calm and readable, but quiet rather than bold or bright. It's also very close to a look many AI-generated products now share, which makes it forgettable. The design concepts that accompany this document propose alternatives.

## Recommended structure

| Area | What it holds | Replaces |
|---|---|---|
| Today | Time picker (5, 15, 30 min), the session for right now, weekly target, one progress highlight | Home, Today card, next action |
| Prep | Each role or goal you're preparing for: gap report, plan, mock interviews, readiness | Goals, Interview prep |
| Library | Your documents, reader with tutor, quizzes from a document | Library on home, document pages |
| Profile | Account, privacy, data export, reminders, usage | Settings |

## Metrics to watch

Acquisition is measured by the share of landing visitors who complete a gap report, and the share of those who then create an account. Activation is the share of new accounts reaching the activation event within their first session, and the median time to get there (target under three minutes). Retention is the share of activated users who complete a session in week 2 and week 4, measured separately for users with and without an interview date. The guardrails are notification opt-outs, the rate of reported wrong answers, and whether users override plan suggestions (a high override rate means the plan isn't realistic).

## Experiments, in suggested order

| Experiment | Hypothesis | Success signal |
|---|---|---|
| Gap report before sign-up vs sign-up first | Showing personal value first raises sign-up conversion | Higher visit-to-account rate with no drop in activation |
| Goal-first vs upload-first onboarding | Asking the goal first makes the first session more relevant | More users reach the activation event in session 1 |
| Time picker on Today vs a fixed daily plan | Letting users choose 5/15/30 minutes raises completion | Higher session completion and week-2 return rate |
| Weekly target vs daily streak vs none | A weekly target gives return visits without guilt | Week-4 retention up, notification opt-outs not up |
| One question at a time vs full-page quiz | Single questions raise mobile completion | Higher quiz completion on mobile |
| Post-interview debrief prompt | Asking "how did it go?" converts endings into new goals | Share of users creating a new goal within 14 days of an interview date |

## How to validate this in two weeks

Recruit 8–10 people matching the first segment: working professionals with an interview in the next one to four weeks, mixed by industry and seniority. Pay them for their time, and recruit through LinkedIn, alumni networks or a career coach.

In week one, run 30-minute interviews about how they prepare today: what they use, where they get stuck, what they'd pay for, and how they feel about uploading a resume. Listen especially for whether the gap report solves a problem they describe without prompting.

In week two, run 30-minute usability sessions on a clickable prototype of the recommended direction. Give five tasks: get a gap report for a real job you want, understand why the top skill is ranked first, start today's session with 15 minutes, answer a question and understand the feedback, and find where to delete your data. Record where they hesitate, misread or give up. Five to six sessions will surface most serious usability problems.

The output is a short findings document that confirms or overturns each hypothesis above, and a prioritised change list for the build.
