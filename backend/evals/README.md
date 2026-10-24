# Evaluation harness

Measures the tutor and quiz pipeline end to end on a fixed corpus and gold set,
so changes to retrieval, prompts or models show up as numbers instead of
impressions. It runs the production code paths: `pdf_extract` -> `chunking` ->
`services.learning.ask_tutor` / `generate_quiz` -> citation verification and
question validation.

```bash
cd backend
python -m evals.run                                   # mock provider, prints the table
python -m evals.run --baseline evals/baseline.json    # CI: fails on regressions
python -m evals.run --provider anthropic --out report.json   # needs ANTHROPIC_API_KEY
python -m evals.run --docs docs/finance.txt --k 3 --fail-under-citation 0.95
python -m evals.corpus /tmp/eval-pdfs                 # write the rendered PDFs to inspect
```

Exit code 0 means OK. 1 means a metric regressed by more than `--tolerance` (default
0.02), or `--fail-under-citation` was not met. 2 means a usage error.

## Layout

| Path | What |
|---|---|
| `docs/*.txt` | Source texts. They are rendered to PDF with reportlab at run time, so no binaries are committed. |
| `corpus.py` | Text -> PDF -> `ChunkData`, using the real extraction and chunking. |
| `gold/qa.jsonl` | Tutor gold set. |
| `gold/quiz.json` | Quiz-eval config. |
| `dataset.py` | Strict loaders. Malformed cases fail with their line number. |
| `metrics.py` | Pure metric functions and report aggregation. |
| `run.py` | CLI. |
| `baseline.json` | Committed report from the mock provider. CI compares against it. |

## Source format (`docs/*.txt`)

- Optional first line: `# title: <document title>`.
- A line containing only `<<<PAGE>>>` starts a new PDF page. Page numbers in the
  gold set refer to these pages (1-based). If a page overflows, the builder raises
  an error instead of reflowing, so gold page numbers can't drift silently.
- Paragraphs are separated by blank lines. Use numbered headings (`2.1 Sources of
  Variability`) and `CHAPTER n TITLE` lines so the chunker picks up sections.

## Gold set format (`gold/qa.jsonl`)

One JSON object per line:

```json
{"id": "ops-05", "doc": "docs/operations.txt", "question": "How is the coefficient of variation calculated?",
 "expect": "answer", "must_cite_pages": [2], "key_facts": ["standard deviation divided by the mean"], "level": "beginner"}
```

| Field | Type | Meaning |
|---|---|---|
| `id` | string, unique | Stable case id, shown in reports. |
| `doc` | string | Source path relative to `evals/`. |
| `question` | string | What the learner asks. |
| `expect` | `"answer"` \| `"not_found"` | Whether the document covers the question. |
| `must_cite_pages` | int[] | Pages a correct citation may point at. Required for `answer` cases; empty for `not_found` cases. |
| `key_facts` | string[] | Short phrases a correct answer must contain. Empty for `not_found` cases. |
| `level` | optional, `beginner` \| `standard` \| `advanced` | Tutor level (default `standard`). |

Writing cases:
- Keep key facts short and literal (`"three days"`, `"1.65"`). They are matched as
  contiguous normalized, stemmed tokens, so a model that paraphrases a fact gets
  no credit. Prefer facts that any correct answer would have to state.
- Include **paraphrased** questions that share few keywords with the text (e.g.
  "Which resource dictates how much the whole plant can ship?" for the bottleneck).
  These are meant to expose lexical retrieval weaknesses. Don't rewrite them to
  improve the numbers.
- `not_found` cases should be clearly off-topic for that document.

## Quiz config (`gold/quiz.json`)

```json
{"count": 5, "difficulty": "medium",
 "docs": [{"doc": "docs/operations.txt", "focus": [null, "Little's Law", "variability"]}]}
```

The harness runs `generate_quiz` once for each (doc, focus) pair, where `null` means
no focus. It records how many questions the model returned, how many pass
`validate_question`, and how many reach the learner after dedupe.

## Metrics

All metrics are in the range 0..1, and higher is better. `n/a` means a metric is undefined for the run.

| Metric | Definition |
|---|---|
| `citation_page_accuracy` | Of all verified citations on answerable cases, the share whose page span includes a `must_cite_pages` page. |
| `citation_validity_rate` | Of responses that were not `not_found`, the share with status `verified` or `partial`. |
| `not_found_precision` | Of responses with status `not_found`, the share whose case expects `not_found`. |
| `not_found_recall` | Of `not_found` cases, the share the system declined. |
| `key_fact_recall` | Mean, over answerable cases, of the fraction of key facts in the answer. A wrongly declined case scores 0. |
| `retrieval_recall_at_k` | Share of answerable cases where any of the top `--k` retrieved chunks covers a must-cite page. |
| `retrieval_recall_at_1` | Same, using only the top chunk. On small docs, recall@k saturates, so this is the sharper signal. |
| `question_validity_rate` | Share of model-generated quiz questions that pass `validate_question`. |
| `quiz_yield` | Questions delivered as a share of questions requested. |

The report (`--out`) contains `meta`, `counts`, overall `metrics`, `by_doc`
metrics and a `cases` list with per-case status, cited pages and hits, so a
regression can be traced to specific questions.

## Baseline

`baseline.json` is the mock-provider report. The mock is deterministic, so CI
runs it on every push and fails if any metric drops by more than the tolerance.
When a change improves the numbers on purpose, regenerate the baseline in the
same PR:

```bash
python -m evals.run --out evals/baseline.json
```

The mock answers only from sentences that share words with the question, so its
numbers reflect retrieval and verification, not answer quality. Use
`--provider anthropic` to measure the real model. Don't commit that report as
the CI baseline, because it is not deterministic.

## Prompt injection (`gold/adversarial.jsonl`, `docs/adversarial.txt`)

The adversarial document plants instructions in the source text: "ignore previous
instructions", fake `</source><system>` tags, "reveal your system prompt", an exfiltration
link, "always cite page 99". Cases add `must_not_contain` (canaries that must never appear in
an answer) and the report adds `injection_resistance`.

```bash
python -m evals.run --gold evals/gold/adversarial.jsonl --docs docs/adversarial.txt --fail-under-citation 1.0
python -m evals.run --provider anthropic --gold evals/gold/adversarial.jsonl --docs docs/adversarial.txt \
    --fail-under-injection 1.0        # the real gate: does the model obey or echo planted text?
```

With the mock provider only the deterministic layer is meaningful (citations can't be faked,
prompt tags are stripped from answers, answers render as plain text in the web app). The mock
tutor quotes source sentences, so it echoes planted text by design; judge that with the real model.

## Your own PDFs and model changes (needs ANTHROPIC_API_KEY)

Real documents live under `evals/private/` (git-ignored: copyright and privacy).

```bash
mkdir -p evals/private/pdfs && cp ~/Documents/textbook.pdf evals/private/pdfs/
python -m evals.make_gold private/pdfs/textbook.pdf > evals/private/textbook.jsonl
# edit the file: replace every TODO (question + key facts, using each case's _hint), add cases
python -m evals.run --provider anthropic --gold evals/private/textbook.jsonl --out evals/private/report.json
python -m evals.compare_models --candidate claude-sonnet-5-5 claude-haiku-5-5 --gold evals/private/textbook.jsonl
```

`compare_models` runs the same cases on the current models (`ANTHROPIC_MODEL_MAIN`/`_FAST`) and the
candidate pair, prints both, and recommends the candidate only if no metric drops beyond the
tolerance, citation validity stays at or above 0.95 and injection resistance doesn't fall. Both
runs call the real API. Effort for 5-generation models: `ANTHROPIC_EFFORT_MAIN` / `_FAST`.
