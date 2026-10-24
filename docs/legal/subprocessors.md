# Subprocessors and contract checklist (DRAFT)

| Provider | Purpose | Data it receives | Region | Contract |
|---|---|---|---|---|
| [DECISION: hosting, e.g. AWS / Fly.io / Render] | Run the app, database, files, backups | Everything stored | [DECISION] | DPA [ ] |
| Anthropic | AI answers, quizzes, grading, resume/JD reading | Document excerpts, questions, answers, resume and job text | [CHECK] | Commercial terms + DPA [ ]; confirm no training on inputs and retention period |
| Clerk | Sign-in (email, Google, LinkedIn) | Email, name, sign-in identities, device/IP metadata | [CHECK: data location] | DPA [ ] |
| [DECISION: email provider, e.g. Resend / Postmark / SES] | Reminder and summary emails | Email address, counts and links (no content) | [CHECK] | DPA [ ] |
| [OPTIONAL: Sentry or similar] | Error tracking | Technical error details; never request bodies or documents | [CHECK] | DPA [ ] |
| Google, LinkedIn | Only if the user chooses "Continue with Google/LinkedIn" | Identity data between the user and that provider | n/a | Their own terms |

For each: sign the DPA, record the cross-border transfer basis if data leaves your jurisdiction
[CHECK: DPDP Act section 16 / GDPR Chapter V], note their breach-notification time, and list
them publicly (link from the privacy policy) before the beta.
