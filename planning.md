# Provenance Guard - planning.md

## Overview 
--- 
Provenance Guard is a backend API designed to seamlessly integrate with creative platforms to analyze submitted content and identify whether it is human-authored or AI-generated.  It classifies submitted text as human- or AI-generated, attaches a calibrated confidence score, surfaces a plain-language transparency label to readers, and gives creators a path to appeal a decision they believe is wrong.

**Core Capabilities:**
* **Attribution Analysis API:** An endpoint that ingests text-based submissions and returns a structured evaluation containing the attribution verdict, a calculated confidence score, and the corresponding user-facing transparency label.
* **Multi-Signal Detection Pipeline:** An evaluation engine utilizing at least two distinct, well-documented signals to cross-reference and classify content comprehensively.
* **Nuanced Confidence Scoring:** A scoring framework that actively reflects genuine uncertainty rather than relying on strict binary outputs, ensuring borderline results are handled distinctly.
* **User-Centric Transparency Labels:** Plain-language indicators designed for non-technical readers that clearly communicate whether the content is high-confidence human, high-confidence AI, or uncertain.
* **Creator Appeals Workflow:** A formal mechanism allowing creators to contest classifications, capture their reasoning, log the dispute, and transition the content's status to a review state.
* **Endpoint Rate Limiting:** Deliberate submission thresholds designed to facilitate realistic platform usage while preventing adversarial abuse.
* **Structured Audit Logging:** A comprehensive record capturing every attribution decision, including specific signals used, individual confidence scores, and any associated appeals.
* **Advanced Ensemble Detection:** An expanded processing pipeline incorporating three or more detection signals governed by a defined voting or weighting strategy.
* **Verified Human Credentials:** An earnable provenance certificate demonstrating verified human authorship achieved through additional validation steps.
* **System Analytics Dashboard:** A centralized view visualizing key operational metrics like overall detection patterns and appeal rates.
* **Multi-Modal Content Support:** An extended architecture capable of analyzing a secondary content type, such as image descriptions or structured metadata, alongside standard text.
---

## Detection Signals
### Signal 1 — LLM Semantic Assessment (Groq / llama-3.3-70b-versatile)

**What it measures:** Holistic semantic and stylistic coherence. The LLM is prompted to read the text as a writing-platform reviewer would and answer: does this read as produced by a human or by an AI? It picks up on things like unnatural smoothness, over-hedged phrasing, suspiciously even paragraph lengths, and the absence of the kind of minor inconsistencies that characterise human expression.

**Why this differs between human and AI writing:** AI models are trained to be fluent and on-topic, which paradoxically produces a particular kind of polish — every sentence is serviceable, transitions are logical, the argument lands cleanly. Human writers make micro-choices that violate those patterns: a sudden tonal shift, an unexpected digression, a sentence that trails off. The LLM signal captures that gestalt.

**Prompt strategy:** Chain-of-thought, single call. The model is asked to first explain its reasoning in 2–3 sentences (what patterns it notices, what feels human or artificial), then provide its verdict as JSON. This produces better-calibrated scores than a single-shot "classify this" prompt because the model discovers evidence before committing to a number. The reasoning text is stored in the audit log so reviewers can understand why the LLM reached its conclusion.

**Output format:** A JSON object extracted from the end of the model's response:
```json
{ "verdict": "ai" | "human" | "uncertain", "llm_score": 0.0–1.0, "reasoning": "..." }
```
`llm_score` represents the model's stated confidence that the text is AI-generated (0 = definitely human, 1 = definitely AI). The chain-of-thought approach helps the model express genuine uncertainty when signals are mixed, producing scores in the 0.4–0.6 range rather than always snapping to the extremes.

**Token cost:** ~input length + 200–400 output tokens per call (the reasoning adds ~150–350 tokens over a single-shot prompt). Every submission triggers one Groq call.

**Blind spots:** The LLM can be fooled by deliberately rough, typo-laden, or conversational AI text. It may also flag highly polished human prose (academic writing, professional copywriting) as AI-generated. It has no access to structural statistics — it can't count sentences or measure vocabulary diversity.

---

### Signal 2 — Stylometric Heuristics (pure Python)

**What it measures:** Statistical properties of the text's surface structure. Four sub-metrics are computed:

| Sub-metric | Formula | AI tendency |
|---|---|---|
| Sentence-length variance | `stdev(word counts per sentence)` | Low — AI sentences cluster around a mean |
| Type-token ratio (TTR) | `unique_words / total_words` | Slightly high — AI avoids repetition |
| Punctuation density | `punctuation_chars / total_chars` | Low — AI under-uses dashes, ellipses, parentheses |
| Average sentence complexity | `total_clauses / sentence_count` (approximated by comma + semicolon count) | Moderate — AI favours shorter, cleaner sentences |

**Why this differs:** Human writers are less consistent. They write long unwieldy sentences when excited and short punchy ones when making a point. They repeat words in a paragraph because they forgot or for emphasis. They pepper their prose with asides. AI writing is statistically more uniform across all four dimensions.

**Output format:** A single float `stylometric_score` (0 = human-like structure, 1 = AI-like structure), computed by z-scoring each sub-metric against empirically observed human/AI baselines and averaging.

**Blind spots:** Poetry, lists, technical documentation, and children's writing all have unusual structural profiles that may score as AI-like despite being human-authored. Very long submissions (10 000+ words) wash out local variation and may drift toward the middle. Short submissions (< 50 words) have too little statistical signal to be reliable.

### Combining Signals — Parallel Execution

Both signals run on **every submission**. Stylometric heuristics are computed in pure Python (instant). The Groq LLM call runs in parallel (1–3 seconds). Both scores are always present in the response and audit log.

**Combining formula:**

```
raw_score = (0.60 × llm_score) + (0.40 × stylometric_score)
```

The LLM is weighted more heavily because it captures semantic content while the stylometric signal only sees surface structure.

A **disagreement penalty** is applied when the two signals diverge significantly (|llm_score − stylometric_score| > 0.35). In that case the raw score is pulled toward 0.5 — representing genuine uncertainty rather than a forced verdict:

```
if abs(llm_score - stylometric_score) > 0.35:
    raw_score = 0.5 + (raw_score - 0.5) * 0.5   # shrink toward 0.5
```

**Short-text adjustment:** If `word_count < 50`, the stylometric signal is unreliable (variance calculations on three sentences are meaningless). Weights shift to 0.90 LLM / 0.10 stylometric. The audit log records when this adjustment is applied.

The final `confidence_score` is the adjusted score, rounded to two decimal places.

---

## Uncertainty Representation

### What the score means

| Score range | Interpretation                                                         |
| ----------- | ---------------------------------------------------------------------- |
| 0.00 – 0.30 | Strongly human — both signals agree the text has human-like properties |
| 0.31 – 0.44 | Leaning human — one signal is confident; the other is less so          |
| 0.45 – 0.55 | Uncertain — signals disagree or both sit near the boundary             |
| 0.56 – 0.69 | Leaning AI — one signal is confident; the other is less so             |
| 0.70 – 1.00 | Strongly AI — both signals agree the text has AI-like properties       |

A score of **0.60** means the system has a moderate lean toward AI but is not confident. The label and audit log will reflect that lean without asserting it as fact. A score of **0.95** means near-certainty and produces a categorically different label — not just a higher number, but different language.

### Thresholds

Three label categories are separated by two thresholds:

- `score < 0.40` → **high-confidence human** label
- `0.40 ≤ score ≤ 0.65` → **uncertain** label
- `score > 0.65` → **high-confidence AI** label

The thresholds are deliberately asymmetric: the system must be more confident to declare "AI" than to declare "human." This reflects the project's stated principle that a false positive (labelling a human's work as AI) is worse than a false negative. A score of 0.64 produces an "uncertain" label; only above 0.65 does it flip to "high-confidence AI."

---
## Transparency Label Design

All three variants are written out here exactly as they will appear in the API response and any UI that consumes it.

| Variant                               | Condition           | Exact Label Text                                                                                                                                                                                                                                                                                                                     | Appeals Process                                                                                                                             |
| :------------------------------------ | :------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Variant A — High-confidence human** | score < 0.40        | **✅ This content appears to be human-written.** Our analysis found strong signs of human authorship — things like varied sentence rhythm, distinctive word choices, and stylistic patterns that are hard to replicate consistently. Confidence: High                                                                                 | If this is wrong, the creator can file an appeal below.                                                                                     |
| **Variant B — Uncertain**             | 0.40 ≤ score ≤ 0.65 | **⚠️ We're not sure about the origin of this content.** Our analysis found a mix of signals — some that look human-written and some that look AI-generated. We can't say with confidence either way. The creator may want to provide more context, or readers can weigh this themselves. Confidence: Low                             | The creator can file an appeal to add context or request a review.                                                                          |
| **Variant C — High-confidence AI**    | score > 0.65        | **🤖 This content appears to have been AI-generated.** Our analysis found consistent patterns associated with AI-written text — uniform sentence structure, smooth phrasing, and low stylistic variation. This label is applied automatically and may not be accurate. The creator can appeal if this is incorrect. Confidence: High | This does not mean the creator did anything wrong — many platforms allow AI-assisted work. Check the platform's content policy for details. |
## Appeals Workflow

### Who can appeal

Any creator who has a `creator_id` associated with a submission can appeal that submission. There is no waiting period; an appeal can be filed immediately after classification.

### What the creator provides

A `POST /appeal` request must include:
- `content_id` — the ID returned by the original `/submit` call
- `creator_id` — must match the creator on the original submission (basic ownership check)
- `reasoning` — a free-text field (1–2000 characters) where the creator explains why they believe the classification is wrong

### What the system does

1. Validates that `content_id` exists and that `creator_id` matches the original submission.
2. Updates the submission's `status` field from `"classified"` to `"under_review"`.
3. Writes an appeal event to the audit log, linked to the original classification entry by `content_id`. The log entry includes the creator's reasoning, the original verdict and score, and a timestamp.
4. Returns a confirmation response with the updated status and a reference ID for the appeal.

No automated re-classification occurs. A human reviewer would use `GET /log?content_id=<id>` to see the full history (original classification + appeal) and make a manual determination.

### What a reviewer sees

```json
{
  "content_id": "abc123",
  "events": [
    {
      "type": "classification",
      "timestamp": "2025-06-20T14:32:11Z",
      "verdict": "ai",
      "confidence_score": 0.81,
      "llm_score": 0.88,
      "stylometric_score": 0.70,
      "label_variant": "high_confidence_ai"
    },
    {
      "type": "appeal",
      "timestamp": "2025-06-20T15:04:53Z",
      "creator_id": "poet_jane",
      "reasoning": "This is a poem I wrote in 2019, years before modern AI tools existed.",
      "status_change": "classified → under_review"
    }
  ]
}
```

### Anticipated edge cases

**Edge case 1 — Stylistically simple human poetry.** A haiku or a minimalist prose poem will have near-zero sentence-length variance, a high type-token ratio, and almost no punctuation. The stylometric signal may score this above 0.70 (AI-like), while the LLM signal might score it at 0.40 (uncertain). The disagreement penalty will pull the combined score toward 0.5, landing in the uncertain band. The creator will see Variant B and may appeal. *Mitigation:* The label explicitly says we're not sure, and the appeal path is always open.

**Edge case 2 — AI text that has been lightly edited by a human.** A creator who generates a draft with an AI tool and then rewrites 20–30% of it will produce text that the LLM scores at 0.55–0.70 (moderately AI-like) but the stylometric signal scores at 0.40–0.55 (because the human edits introduced variance). This is genuinely hard to classify, and the system should reflect that ambiguity rather than force a verdict. The disagreement penalty helps here. *Mitigation:* The uncertain label acknowledges this case honestly; the platform's content policy (not the classifier) is the right place to address "AI-assisted but human-edited" work.

**Edge case 3 — Very short submissions (< 50 words).** A tweet-length poem or a brief bio gives the stylometric signal almost no data. Variance calculations on three sentences are meaningless. *Mitigation:* If `word_count < 50`, the stylometric weight is reduced to 0.10 and the LLM weight is increased to 0.90. The audit log records this adjustment. The label will almost always be uncertain for very short text.

---

## Rate Limiting

Limits are applied **per-endpoint, per-IP** using Flask-Limiter with in-memory storage.

| Endpoint | Limit | Reasoning |
|---|---|---|
| `POST /submit` | 10/minute, 100/day | Each call triggers the full detection pipeline including a Groq LLM call. On a writing platform, a creator publishes a handful of pieces per day — 100/day is generous for legitimate use while preventing an adversary from probing the classifier at scale or exhausting Groq free-tier tokens. 10/minute stops rapid-fire abuse while still allowing a creator to submit a small batch. |
| `POST /appeal` | 5/minute | Appeals require human review downstream, so flooding the queue is a denial-of-service on the review team. A creator contesting a decision submits one appeal at a time; 5/minute is more than enough for legitimate use. |
| `GET /log` | 30/minute | Read-only, no LLM cost, no downstream side effects. Higher limit so reviewers and dashboards can poll freely. |

**What happens when the limit is hit:** Flask-Limiter returns a `429 Too Many Requests` response with a JSON body:
```json
{ "error": "Rate limit exceeded. Try again later." }
```

---

## Architecture

### Diagram

```
╔══════════════════════════════════════════════════════════════════╗
║                        SUBMISSION FLOW                           ║
╚══════════════════════════════════════════════════════════════════╝

  Client
    │
    │  POST /submit  { text, creator_id }
    ▼
┌─────────────┐
│ Flask Route │  ← Flask-Limiter checks rate limit (10/min, 100/day)
│  /submit    │     429 if exceeded
└──────┬──────┘
       │ raw text
       ▼
┌─────────────────────┐       ┌──────────────────────────┐
│  Signal 1           │       │  Signal 2                │
│  LLM Assessment     │       │  Stylometric Heuristics  │
│  (Groq API, CoT)    │       │  (pure Python, instant)  │
│  → llm_score 0–1    │       │  → stylometric_score 0–1 │
│  → reasoning text   │       │                          │
└──────────┬──────────┘       └────────────┬─────────────┘
           │                               │
           └──────────────┬────────────────┘
                          │ llm_score + stylometric_score
                          ▼
               ┌─────────────────────┐
               │  Confidence Scorer  │
               │  weighted avg +     │
               │  disagreement       │
               │  penalty + short-   │
               │  text adjustment    │
               │  → confidence_score │
               └──────────┬──────────┘
                          │ score + verdict
                          ▼
               ┌──────────────────────┐
               │  Label Generator     │
               │  score < 0.40 → A    │
               │  0.40–0.65  → B      │
               │  score > 0.65 → C    │
               │  → label_text        │
               └──────────┬───────────┘
                          │
                          ▼
               ┌──────────────────────┐
               │  Audit Logger        │
               │  writes structured   │
               │  entry to SQLite     │
               │  (JSON via API)      │
               └──────────┬───────────┘
                          │
                          ▼
               JSON response to client
               { content_id, verdict,
                 confidence_score,
                 label_text,
                 llm_score,
                 stylometric_score }


╔══════════════════════════════════════════════════════════════════╗
║                          APPEAL FLOW                             ║
╚══════════════════════════════════════════════════════════════════╝

  Client
    │
    │  POST /appeal  { content_id, creator_id, reasoning }
    ▼
┌─────────────┐
│ Flask Route │
│  /appeal    │
└──────┬──────┘
       │ validate content_id + creator_id ownership
       ▼
┌─────────────────────────┐
│  Status Updater         │
│  "classified" →         │
│  "under_review"         │
└──────────┬──────────────┘
           │ updated status + reasoning
           ▼
┌──────────────────────┐
│  Audit Logger        │
│  appends appeal      │
│  event to SQLite     │
│  linked by           │
│  content_id          │
└──────────┬───────────┘
           │
           ▼
   JSON response
   { content_id, status: "under_review", appeal_id }
```

**Submission flow:** A `POST /submit` request passes through Flask-Limiter before any processing occurs. The text is then evaluated by two independent signals: the Groq LLM returns a semantic assessment with chain-of-thought reasoning, and the stylometric module computes structural statistics. The Confidence Scorer combines both outputs into a single calibrated score (with a disagreement penalty when they diverge and a short-text weight adjustment for submissions under 50 words), which the Label Generator maps to one of three plain-language variants. Every decision — including both individual signal scores — is written to a SQLite database before the JSON response is returned to the client.

**Appeal flow:** A `POST /appeal` request is validated against the original submission record in SQLite (creator ownership check). On success, the submission status changes to `"under_review"`, an appeal event is appended to the audit log (linked to the original classification by `content_id`), and a confirmation is returned. No re-classification happens automatically; a human reviewer uses `GET /log` to retrieve the full history as JSON.

**Storage:** SQLite is the primary data store for submissions, classifications, and appeals. All API read endpoints (`GET /log`, `GET /log?content_id=<id>`) query SQLite and return structured JSON. This gives queryability for the application while producing grader-friendly JSON output.

**Verification flow**: A `POST /verify_identity` request accepts a creator_id and marks that creator as verified in the users table. On subsequent `POST /submit` requests, the pipeline checks the creator's verification status before generating the label. If the creator is verified, the confidence score is reduced by 0.15 (shifted toward human) — treating identity verification as an additional trust signal that supplements the detection pipeline. If the adjusted score falls below 0.40, the standard transparency label is upgraded to a "🛡️ Verified Human Creator" badge with distinct text. A strong AI signal (e.g., 0.85) still lands in the AI or uncertain range after adjustment — verification biases toward human but does not override the classifier.

---
## **AI Tool Plan**

### Milestone 2 — Architecture brainstorming

**AI Tool:** Claude 3.5 Sonnet
**Input provided:** The full project requirements document, including the required features list, recommended stack, milestone structure, and grading rubric.
**Expected Output:** Brainstorm the key architectural decisions for the system. I asked Claude to present multiple options for each decision with pros, cons, effectiveness, and token-usage implications so I could make informed choices rather than defaulting to the first approach that came to mind.
**Decisions evaluated:**
1. **Signal execution — sequential vs. parallel.** Claude laid out three options: (A) run stylometric heuristics first and skip the LLM when the structural score is confident enough, saving Groq tokens; (B) always run both signals on every submission; (C) parallel with adaptive weighting based on text length. I chose Option B. Option C's short-text adjustment was kept as a targeted enhancement within Option B.
2. **LLM prompt strategy — single-shot vs. chain-of-thought.** Three options: (A) one prompt returning just the JSON verdict; (B) chain-of-thought reasoning followed by JSON extraction; (C) two separate API calls. I chose Option B — the extra ~200 output tokens produce better-calibrated scores and the reasoning text is useful for the audit log and appeal reviews.
3. **Storage — SQLite vs. JSON file.** Three options: (A) SQLite; (B) newline-delimited JSON file; (C) SQLite as primary with JSON output via the API. I chose Option C — SQLite gives queryability for the application while the API returns structured JSON that graders can inspect directly.
4. **Rate limiting scope — global vs. per-endpoint.** Three options: (A) single global limit per IP; (B) different limits per endpoint per IP; (C) per-creator_id application-level limits. I chose Option B — submissions are expensive (LLM call) so they get tighter limits, while read-only log queries get a higher ceiling.
- **Verification:** I will review the options and choose based on the pros and cons of the recommendations.
### **Milestone 3 — Submission endpoint + first signal**
* **AI Tool:** Claude 3.5 Sonnet  
* **Input:** The "Detection Signals (Signal 1)" section and the "Architecture diagram (submission flow)" from this document.  
* **Expected Output:** A minimal Flask app with a POST /submit route stub (accepting { text, creator_id }) and a classify_with_llm(text) function that calls the Groq API (llama-3.3-70b-versatile) using a chain-of-thought prompt with a structured JSON fallback.  
* **Verification:** I will call classify_with_llm() directly in a Python REPL using three test strings (one clearly AI, one clearly human, one ambiguous) to ensure scores vary and the JSON parses correctly without crashing. I will also use a curl command to hit the /submit stub to confirm a 200 OK response with the expected JSON shape.
### **Milestone 4 — Second signal + confidence scoring**
* **AI Tool:** Claude 3.5 Sonnet  
* **Input:** The "Detection Signals (Signal 2)" section, "Uncertainty Representation" section (weighting formula, disagreement penalty, thresholds), and the "Architecture diagram" from this document.  
* **Expected Output:** A compute_stylometric_score(text) function to compute the four sub-metrics, and a combine_scores(llm_score, stylometric_score, word_count) function that accurately applies the weighted average, disagreement penalty, and short-text adjustment.  
* **Verification:** I will run the test paragraphs from Milestone 3 through the combined scoring function. I'll manually verify that the AI text scores > 0.65 and the human text scores < 0.40. I will also feed it a three-sentence haiku to explicitly verify that the short-text penalty triggers and correctly drops the stylometric weight to 0.10.
### **Milestone 5 — Production layer (labels, appeals, rate limiting, audit log)**
* **AI Tool:** Claude 3.5 Sonnet  
* **Input:** The "Transparency Label Design" section (the exact Markdown table), the "Appeals Workflow" section, and the full "Architecture diagram" from this document.  
* **Expected Output:** A generate_label(confidence_score) function, a POST /appeal Flask route that updates SQLite and writes to the audit log, a SQLite database initialization setup, and Flask-Limiter configurations for the /submit, /appeal, and /log endpoints.  
* **Verification:** I will call generate_label() with test scores (0.25, 0.52, 0.80) to assert that the exact label text from my spec is returned. I will use curl to submit an appeal and immediately check GET /log to confirm the status updated to "under_review". Finally, I will run a bash script with 12 rapid /submit requests to ensure Flask-Limiter correctly returns a 429 status code after the 10th request.
### **Milestone 6 — Documentation review and alignment**
* **AI Tool:** Claude 3.5 Sonnet  
* **Input:** The full Project.md requirements document (including the grading rubric), alongside the draft planning.md, README.md, and provenance_guard_app.py.
* **Expected Output**: Audit all three files against every rubric line item and the Milestone 6 submission checklist. Identify gaps where the documentation didn't meet a requirement, where the code diverged from the planning spec, or where a rubric point was at risk.
* **Verification**: I reviewed each finding against the rubric and the code. I accepted fixes that addressed clear spec violations or rubric gaps.
