# Mindmesh Privacy Policy (DRAFT, needs legal review)

_Last updated: [DECISION: date]. Controller: [DECISION: legal entity, address, contact email]._

Mindmesh helps you prepare for interviews and learn from your own documents. This policy explains
what we collect, why, who helps us process it, and the choices you have.

## What we collect
| Data | When | Why |
|---|---|---|
| Account: email address, name (optional), sign-in identity (Clerk) or a password hash | You sign up | To give you an account |
| Documents you upload (PDF) and their extracted text | You upload | Tutor answers, quizzes and plans from your own material |
| Resume and job-description text you paste or upload, and what we extract from them | You create a gap report or role prep | The skill matrix and interview practice |
| Questions you ask the tutor and its answers; quiz answers and scores; interview practice answers | You use those features | Feedback, progress and "what you know" |
| Goals, study plans, practice sessions, preferences (including your time zone) | You use those features | Plans and reminders in your own time |
| Reports you make about questions | You report a question | To stop it counting towards your progress, and to improve question quality |
| Technical records: request IDs, page paths, response codes, timings; AI usage counts (tokens, no content) | Every request | Security, reliability, cost and abuse limits |
| Product usage events: which steps you took and when (for example "uploaded a document", "answered a question"), never what you wrote or uploaded | You use the product | To see which onboarding works better and where people get stuck; kept in our own database, never shared with analytics or advertising companies [DECISION: legal basis, e.g. legitimate interests, and whether an opt-out is offered] |
| A job-ad web link you ask us to import | You use "Job ad link" | We fetch that one page and show you its text; the link and the page aren't stored |

**Signed-out gap reports** are kept for up to 30 minutes so you can save them by creating an
account. If you don't, they are discarded. We don't store your resume or job text otherwise.

We do not collect payment details. [DECISION: if billing is added, update this.] We do not
use advertising trackers.

## How AI is used
To answer questions, write quizzes, grade answers and read resumes, we send the relevant excerpts
of your documents and your text to our AI provider, Anthropic. [CHECK: Under Anthropic's
commercial terms, API inputs and outputs are not used to train their models; confirm against your
signed agreement and its retention terms.] We never use your content to train models ourselves.
Answers cite the pages they come from, and we check those citations, but AI can still be wrong.

## Who processes your data
See `subprocessors.md`: hosting [DECISION: provider and region], Anthropic (AI), Clerk (sign-in),
[DECISION: email provider] (reminder emails, only if you turn them on), and optionally an error
tracker that receives technical details but never your documents, answers or request bodies.

## Your choices and rights
- **Export:** Settings > Your data > Export downloads everything we hold about you as JSON.
- **Delete:** Settings > Delete account removes your account, documents, files and everything
  derived from them immediately, and your sign-in identity shortly after. Backups expire as
  described in `retention-policy.md`.
- **Correct:** you can edit or delete documents, preps, goals and plan items in the app.
- **Emails:** reminders are off until you turn them on, and every email has one-click unsubscribe.
- **Reports:** you can withdraw a report on a question at any time.
[CHECK: list the statutory rights that apply to you (access, correction, erasure, grievance
redress, nomination, objection, portability) and how to exercise them, including a grievance
officer or DPO contact if required.]

## Security
Encryption in transit (TLS); each user's data is isolated by the application and by database
row-level security; uploads are type-checked and can be virus-scanned; access to production
data is limited and logged. [DECISION: encryption at rest by your hosting provider.]

## Children
[DECISION: minimum age, e.g. 18, or the age of digital consent where you operate.]

## Changes
We will tell you about material changes by email or in the app before they take effect.
