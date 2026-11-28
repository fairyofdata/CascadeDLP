<!-- Source: README_KR.md (Korean is the source; English and Japanese are translations) · synced 2026-11-26 -->

# Prudentia

[English](README.md) · [한국어](README_KR.md) · [日本語](README_JP.md)

Formerly CascadeDLP (renamed 2026-11-24, [ADR-0024](docs/adr/0024-rename-to-prudentia.md)).

**A cascading DLP layer: a small local model stands gate in front of a frontier cloud model — for mixed Korean / Japanese / English work.**

One GPU (RTX 3070, 8 GB) cannot replace a top-tier model, and yet not everything can be sent to the cloud.
In Prudentia **a local model reads the document first and makes a gate decision; only what passes goes to the cloud model, and the answer that comes back is restored to the original values locally.**

*Prudentia* is Latin for "prudence", knowing what to show and what to keep: the local side decides what the cloud gets to see.

## The local DLP gate: detection cascade and gate decision (the criterion is sensitivity)

```
document ─▶ ① local gate (rules + local LLM + a glossary confirmed by a person)
              │
              ├─ nothing detected ─────▶ original text as is ─────────┐
              ├─ detected ────────────▶ masked (replaced by tokens) ──┤
              │                                                       ▼
              │                                        ② the cloud model does the work
              │                                                       │
              │                                                       ▼
              │                                        ③ restored locally (tokens → original values, to a file)
              │
              ├─ suspicious ───────────▶ not sent; ask the user (local pending list)
              │                           └ the answer is remembered: protect → glossary / common word → allow list
              ├─ the meaning itself is secret (L3) ─▶ never sent to the cloud; only the local model handles it (result to a local file)
              └─ cannot be handled ────▶ refused (secret keys, too much to mask, too many unknown terms without a glossary)

Every decision goes to an audit log (no content — only hashes, counts and paths).
```

| Gate decision | Condition | Result |
|---|---|---|
| **pass** (`cloud_raw`) | nothing detected | original text to the cloud |
| **mask** (`cloud_masked`) | personal data, glossary items at L1·L2 | replaced by tokens and sent → the answer is restored locally |
| **confirm** (`needs_confirmation`) | words that look like project terms but are not in the glossary | held. The user marks them `[x]` protect / `[o]` common word in the local pending list |
| **local only** (`local_only`) | glossary items at L3 (the meaning itself is secret) | handled by the local model, result only to a local file |
| **refuse** (`block`) | secret keys, 30% or more to mask, token-shaped strings in the source, too many suspicious items | sent nowhere |

### Two terms
In this project the two words mean different things.

- **Detection cascade** — how the local gate *finds* sensitive material. It filters from cheap and certain to expensive:
  `rules (formats) → glossary confirmed by a person → local LLM (ambiguous cases)`. A later stage cannot overturn what an earlier stage caught.
  In this document "cascade" (including "cascading DLP layer" at the top) means **only this**.
- **Gate decision** — the five outcomes (table above) that decide *what to do* with the document given what was found: pass · mask · confirm · local only · refuse.

This is **not** the usual LLM cascade (a cheap model tries first and hands hard cases to an expensive one, for performance and cost). Whether to hand off to the cloud is decided by **sensitivity**, not by difficulty. Handing off by difficulty would send "hard and sensitive" documents to the cloud, which cannot coexist with DLP.

Prudentia itself never calls the cloud. It returns the decision and the masked text to the caller (Claude Code and the like), and the caller does the cloud work.

## What it promises and what it does not
**It is a risk-reduction layer, not a guarantee** ([threat model, ADR-0022](docs/adr/0022-threat-model.md)).

| Promises | Does not promise |
|---|---|
| Masks **identifiers** such as personal data, client names and project terms before sending (zero exposure if they are in the glossary) | **Compliance with a "no data may leave" policy.** Sending a masked document is still sending it out |
| **Keeps documents whose meaning is marked secret (L3) local** | **Protection of meaning.** Even with every name masked, "what is done and how" reads as well as the original (leakage 0.89–0.94) |
| **Stops and asks** when it sees unknown project terms (87–93%) | Complete detection. About 1 in 8 personal-data items and 7–13% of unknown terms can get through |
| **Records** what went where | Source code support (documents only), enforcement of the gate (it can currently be bypassed) |

The project started from the question "can masking get around a ban on taking source code outside?". The answer after building and measuring it is **no** — there is no criterion for masking core logic, and meaning leaks even when it is masked. If the meaning is secret, the answer is a local or in-house model, not masking. What remains is a safety layer against mistakes for material that may leave, and a framework for deciding what to send (gate decisions, glossary, audit log).

> **Status (2026-10-03)**: the whole flow above is implemented and measured for documents. What remains is support for code repositories (C4) and a pilot on real documents (all numbers so far are on synthetic data). [Roadmap](#roadmap) · background of the change of direction: [ADR-0015](docs/adr/0015-cascade-dlp-direction.md).

**Preparation (once per project)**: document folder → the local LLM drafts a **glossary** (words specific to this project) → a person checks it and sets levels (L0 public · L1 hide the name only · L2 token · L3 local only). The gate decides against this glossary.

```text
Tessellane의 조율기는 Ripple Rank 점수를 쓰고 FastAPI 위에서 돈다.          (glossary: L1·L1·L2·L0)
        ↓
[PROJECT_01: 사내 물류 최적화 플랫폼]의 [COMPONENT_01: 작업 우선순위 스케줄러]는 [ALGORITHM_02] 점수를 쓰고 FastAPI 위에서 돈다.
```

### Stage 1: personal-data entities (implemented)
**Before** sending to an external LLM, personal data is replaced locally by tokens such as `[PERSON_001]`; when the answer comes back, the original values are restored **into a local file**.

```text
昨日、한서윤さんと Tanaka Haruto から連絡。ハン・ソユンさんのメールは seoyun.han@example.com
        ↓
昨日、[PERSON_001]さんと [PERSON_002] から連絡。[PERSON_001]さんのメールは [EMAIL_001]
```

## What is different
There are already many PII/DLP tools (Presidio, GLiNER, commercial DLP …). What only this one does:

1. **Handles project-specific terms** — words like `조율기` or `Adaptive Scheduler` that are also common nouns and cannot be caught by rules are found through a person-confirmed glossary, including spelling variants (`adaptive_scheduler`, `適応スケジューラ`), and handled by level. The glossary draft is made by the local LLM.
2. **Measured the limits of masking** — confirmed with numbers that masking protects names but not meaning (design intent), and solved protection of meaning with local-only routing ([ADR-0019](docs/adr/0019-semantic-leakage.md)).
3. **Mixed Korean / Japanese / English documents** — Hangul names, kana names and romanized names may appear in one sentence.
4. **Cross-script linking** — `한서윤 / 韓瑞允 / ハン・ソユン / Seoyun Han` → the same `[PERSON_001]`.
5. **Long-term stable, reversible pseudonymization** — a person who is `[PERSON_001]` today is `[PERSON_001]` in another conversation next week. Restoration matches the original **byte for byte**.
6. **Measured against existing tools as baselines** — GLiNER splits on whitespace and grabs whole Japanese sentences, which made it hard to use as is for Korean/Japanese documents ([ADR-0009](docs/adr/0009-gliner-baseline.md)).

## Design principles
- **Determinism first; the local LLM only for things without a format.** Mail, phone, postal code, URL and ID formats are regular expressions. The LLM only outputs *candidate strings* for names, addresses and organizations, and the *romanized reading* of names. Locating, token assignment, same-person decisions and restoration are all done by code (hallucinations are not in the source, so they are discarded automatically).
- **The caller is the external LLM.** The MCP tools do not take the source text as an argument (file paths only) and do not return the restored result (local files only).
- **The pseudonym map stays local.** `~/.prudentia/` — it belongs to no repository.
- **Development and evaluation use synthetic data only.**

## Stage 1 (personal-data detection) performance (synthetic evaluation, qwen3.5:9b, RTX 3070 8 GB)
Measurements for the glossary and router are in [key findings](#key-findings-so-far-two-synthetic-fictional-projects-local-models) below.

| | dev set eval_v1 | holdout eval_v2 |
|---|---|---|
| Detection F1 (exact match) — rules only | 0.404 | 0.230 |
| Detection F1 (exact match) — rules + GLiNER | 0.593 | 0.526 |
| **Detection F1 (exact match) — rules + local LLM** | **0.873** | **0.875** |
| Cross-script linking (exact group match) | 7/9 | 7/10 |
| Link pair precision (never merges different people) | 1.000 | 1.000 |
| Latency per sentence | ~2.8s | ~2.8s |

- The holdout was scored once with the code frozen ([ADR-0010](docs/adr/0010-holdout-and-overfitting.md)). A version fixed after looking at the v2 errors reaches v2 F1 0.933 and linking 9/10 (numbers after tuning).
- Token preservation after local translation: **210/210** (no tokens broken or invented) — [ADR-0014](docs/adr/0014-p5-local-transform.md).
- ⚠ All evaluation sets are synthetic sentences generated by the analyst (an LLM). Read them as relative comparisons between methods and models, not as absolute values.

## Install (Windows, Python 3.12+, [Ollama](https://ollama.com))
```powershell
git clone https://github.com/fairyofdata/Prudentia.git
cd Prudentia
.\setup.ps1        # venv · dependencies · pip install -e .[mcp] · Ollama model · smoke test
```
The default model is `qwen3.5:9b` (about 6.6 GB, 100% on GPU with 8 GB VRAM). To use rules only without an LLM, pass `--rules-only`.

## Usage
Details in [USAGE.md](USAGE.md) (Korean).

**CLI**
```powershell
# 1) build the glossary (once per project, local only)
prudentia --project myproj bootstrap D:\work\myproj\docs      # writes a candidate review file
prudentia --project myproj apply-review <review file>          # applies the checked items to the glossary

# 2) gate (router) — the recommended entry point
prudentia --project myproj route design.md -o to_cloud.md     # decision + the text to send if pass/mask
prudentia --project myproj route design.md -q "summarize this" -o answer.md   # if local only, the local model answers
prudentia --project myproj confirm                            # after a 'confirm' decision: mark the pending list, then apply
prudentia audit                                               # what went where

# 3) mask and restore directly
prudentia mask memo.md -o memo.masked.md                      # prints a job id
prudentia unmask answer.md --job <job_id> -o answer.restored.md
```

**MCP (as tools in Claude Code and the like)**
```powershell
claude mcp add --scope user prudentia -- <repository path>\.venv\Scripts\python.exe -m prudentia.mcp_server
```
- Register with `python.exe -m`, not `prudentia-mcp.exe`. The unsigned executable pip creates can be blocked by Windows application control (Smart App Control and the like) (`WinError 4551`).
- Moving or renaming the repository folder breaks the registered path (`uv_spawn` error). Reinstall with `pip install -e .[mcp]` in the new location and register again with the command above.

Tools: `route_file(path, question?, project?)` (recommended) · `mask_file(path, project?)` · `unmask_to_file(masked_text, job_id, out_path)` · `list_entities()`
Drafting a glossary (`bootstrap`) produces the list of "what is core", so it is not exposed over MCP; it is CLI only.
Paths, file names and formats (md/json/txt/csv) are given in the conversation each time. The default allowed scope is the user folder; the pseudonym map folder, `.ssh`, `.claude`, `AppData` and the like are always blocked, and overwriting is refused ([ADR-0013](docs/adr/0013-path-policy.md)).

**Python API**
```python
from prudentia.gate import Gate
g = Gate()
r = g.mask_file("memo.txt")
answer = call_external_llm(r.masked_text)       # only pseudonymized text goes out
g.unmask_to_file(answer, r.job_id, "memo_answer.txt")
```

## Layout
```
prudentia/  spans · rules · llm · linking · pseudo · transform        (detection, linking, pseudonymization)
             glossary · bootstrap                                     (project glossary, automatic draft)
             gate (core API) · router (gate decision, audit log) · confirm (suspicious-item confirmation) · cli · mcp_server
tools/       measurement tools: evaluate · eval_glossary · eval_bootstrap · eval_utility · eval_semantic · eval_doc_pii …
tests/       139 deterministic tests that run without an LLM (round trip, rules, glossary, router, confirmation flow, boundary principles)
data/eval/   synthetic evaluation sets: sentence sets v1·v2, fictional projects Tessellane (dev) and Quillmere (holdout) — authors and counts in its README
results/     measurement results (numbers + error lists on synthetic data)
docs/adr/    design decision records (ADR 0001–0023)
```

## Roadmap
Documents (design documents, ADRs, structure descriptions) first, code after ([ADR-0015](docs/adr/0015-cascade-dlp-direction.md)).

| Stage | Contents | Status |
|---|---|---|
| P0–P5 | Personal-data entities: rule + local LLM detection, cross-script linking, reversible pseudonymization, Gate/CLI/MCP, local translation and summary | ✅ |
| C0 | Redefinition (PII masker → cascading DLP), rename | ✅ |
| C1 | More entities (`PROJECT` `COMPONENT` `ALGORITHM` `TERM` `SECRET`) + sensitivity L0–L3 + safe descriptions + project glossary ([ADR-0016](docs/adr/0016-project-glossary.md)) | ✅ |
| C2 | Glossary bootstrap: the local LLM proposes "words specific to this project" and groups of variant spellings → **a person confirms sensitivity** ([ADR-0017](docs/adr/0017-glossary-bootstrap.md), holdout items 10/10, wrong merges 0) | ✅ |
| C3 | Information-preserving masking: by level, as is / descriptive alias `[COMPONENT_01: scheduler]` / token / block + experimental context reduction (generalization, sentence removal) | ✅ |
| C6 | Measurement: **utility vs name leakage vs meaning leakage** — masking protects names without losing utility but does not protect meaning → meaning is protected by L3 routing ([ADR-0018](docs/adr/0018-utility-vs-leakage.md), [ADR-0019](docs/adr/0019-semantic-leakage.md)) | ✅ |
| C4 | Code: no reading of L3 paths + a masked mirror workspace (core functions as signatures and descriptions only) → reverse-map the changes | next candidate |
| C5 | Router (cloud raw / masked / local only / block) + audit log ([ADR-0020](docs/adr/0020-router.md)) | ✅ |
| C7 | Gate decision completed: **suspicious items are confirmed by the user** (hold → local pending list → remembered), refusal by complexity ([ADR-0021](docs/adr/0021-cascade-confirmation.md)) | ✅ |
| **D** (stage 3) | **Design knowledge base and separation of core logic**: the local side holds thousand-line design documents without dropping anything (section tree, entity index, BM25, ledger of what was sent), and uses that to identify core logic and separate it from the code ([ADR-0023](docs/adr/0023-knowledge-base-direction.md), [scenario](docs/scenario-knowledge.md)) | D0 ✅ · D1 next |
| Later | **Gate enforcement**: Claude Code can currently read files directly without going through the gate tools (it relies on instructions only). Block direct reads of protected folders with permission settings and hooks | later |

### Key findings so far (two synthetic fictional projects, local models)
| Method | Utility | Name exposure | Meaning leakage |
|---|---|---|---|
| Original | baseline | all | 0.83–0.89 |
| **L2 tokens (default)** | same as original | **0** | 0.89–0.94 |
| L2 + sentence generalization | about 45% lower | 0 | 0.44–0.83 |
| L2 + sentence removal | nearly 0 | 0 | 0.39–0.44 |

→ **Masking protects names and personal data without losing utility. But "what is done and how" (design intent) leaks even when masked sentence by sentence.** What is secret in meaning should not be masked but **handled locally only (L3 routing)** — which is why the router (C5) was built.

Other measurements:
- Glossary draft: on a fictional project it had never seen, all 10 answer items appeared among the candidates, with 0 wrong merges ([ADR-0017](docs/adr/0017-glossary-bootstrap.md)).
- Glossary application: 0 term leaks, 0 over-masking, byte-exact restoration ([ADR-0016](docs/adr/0016-project-glossary.md)).
- Suspicious-item confirmation: the gate stopped 87% (holdout) to 93% (dev) of terms deliberately left out of the glossary. With a full glossary, false stops were 0–2 out of 5 documents ([ADR-0021](docs/adr/0021-cascade-confirmation.md)).

## Known limitations
- **Masking does not protect meaning.** If design intent is secret, set it to L3 and handle it locally only.
- **The gate can still be bypassed.** Claude Code can read files directly without the gate tools. Enforcement is later work.
- **Suspicious-item confirmation does not stop every unknown term (7–13% get through).** Korean and Japanese terms are missed in particular. Filling the glossary first is the basic line of defense.
- **Generous L3 assignments make the cloud unusable.** One L3 term appeared in 4 of 5 documents and most became local only — keep L3 to a few items ([ADR-0020](docs/adr/0020-router.md)).
- **Person-name detection sometimes wobbles in long documents.** Splitting into smaller chunks reduced it a lot (exposure 10 → 1), but not to 0 ([ADR-0018](docs/adr/0018-utility-vs-leakage.md)).
- Answers on the local-only path have local-model (8K context) quality. Long documents use only the beginning.
- **All numbers are on synthetic data made by the analyst.** A pilot on real documents has not been done yet.
- Kanji-only names are ambiguous to read (伊藤大翔 → hiroto? daisho?) → cross-script linking fails.
- Two names joined only by a space (`정민호 김민준`) are merged into one person.
- Address boundaries are imprecise (ADDRESS exact F1 0.44–0.57).
- People with the same name in the same spelling are not distinguished.
- The pseudonymized output (the non-personal parts) does go out. **For sensitive documents, check the pseudonymized result before sending.** This tool helps protect personal data; it does not guarantee complete detection.

## About the evaluation data
The names, addresses and contact details in `data/eval/` are all **made up**. Mail and URLs use reserved domains only (`example.com/.jp/.org`). Phone and ID numbers are random digits that only match the format; any match with a real number is coincidence.

## License
[MIT](LICENSE)
