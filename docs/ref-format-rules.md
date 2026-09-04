# REF/1 format rules (Hub parser)

This document is the rule reference for `parse_manuscript_to_ref()`. Rendering in Read is out of scope here — Hub only produces validated REF/1 JSON.

Author-facing manuscript conventions (Vietnamese): [ref-author-guide.md](./ref-author-guide.md).

## Pipeline

```
raw text
  → [optional] build_edition() rule strip (Gutenberg wrappers, TOC, index)
  → iter_lines() — one physical line per entry, UTF-8 offsets preserved
  → label_lines_rules() — role + join_next per line
  → [optional] relabel_uncertain_segments() when use_llm=True
  → labels_to_blocks() — deterministic merge (whitespace / hyphen only)
  → annotate_blocks() — rule-only inline spans
  → build_edition_document() — reading_markdown, split_hints, edition_hash
  → validate_edition()
```

Text tokens are never rewritten. Allowed transforms: join wrapped lines with a single space, de-hyphenate at line breaks, drop apparatus spans marked by `build_edition()`.

## Source families

| `source_family` | Detection | Strip step |
|-----------------|-----------|------------|
| `gutenberg` | `*** START OF … PROJECT GUTENBERG EBOOK ***` | yes — wrappers, transcriber notes, trailing index |
| `scholastic` | ≥4 scholastic markers in first 80k chars, or work override | same as gutenberg when PG markers present |
| `aozora` | Japanese + Aozora boilerplate | ruby / note inline cleanup |
| `archive_scan` | archive.org license / URL | hard-wrap unwrap |
| `plain` | default | none |

Work catalog may override via `work.read.edition.family`.

Scholastic markers (case-sensitive line starts):

- `QUESTION N`
- `Objection N:`
- `_On the contrary`

## Block types

| `type` | Required fields | Merge rule |
|--------|-----------------|------------|
| `heading` | `text`, `level` (1–4) | never merged |
| `paragraph` | `text` | consecutive `prose` lines with `join_next=true` |
| `blockquote` | `text` | consecutive `blockquote` roles |
| `verse_line` | `text` | never merged (poetry one line = one block) |
| `hr` | — | rule line `----`, `====`, etc. |
| `dialogue` | `text`, optional `speaker` | future — Shakespeare pilot uses paragraph |
| `stage_direction` | `text` | future |
| `list_item` | `text` | future |

### Line roles → blocks

| Line pattern | Role | Block |
|--------------|------|-------|
| `CHAPTER I`, `BOOK II`, `PART 1`, `VOLUME 2` | `heading` L1 | `heading` |
| `PREFACE`, `INTRODUCTION`, `APPENDIX`, … (`HARD_GUTENBERG`) | `heading` | `heading` |
| `CHƯƠNG` / `PHẦN` | **macro** chapter split only — not `HARD_GUTENBERG`; becomes `heading` only via ALL-CAPS heuristic | often `paragraph` when short (`CHƯƠNG I` = 7 letters) |
| `Scene I.`, `ACT II` | `heading` L2–3 (play mode) | `heading` |
| Full-line `_italic_` that looks like a title (incl. inner length ≥ 40) | `heading` L2 | `heading` |
| Other full-line `_italic_` | `prose` | `paragraph` |
| ALL CAPS, ≥ 8 letters, **< 90** chars, ≥ ~85% uppercase | `heading` L2 | `heading` |
| `-----` (≥8 rule chars; short rules 3–7 also) | `hr` | `hr` |
| Indented poetry / VI verse (comma/semicolon end) | `verse_line` | `verse_line` / `stanza` |
| default | `prose` | `paragraph` after merge |

### Join rules (v1.2)

- **Blank line = paragraph break** — `iter_lines()` sets `blank_before`; never join across it (except spurious PG wrap: hanging word, or gutenberg imprint lines).
- **Footnote sentence ends** — `.[150]` counts as sentence end (fixes VI over-merge).
- **Quote continuation** — multi-line Gutenberg poetry merges into `blockquote`.
- **Hanging word wrap** — long lines ending in `the`, `her`, `of`, … join to next line (PG hard wrap).
- **Uppercase wrap** — PG lines ≥55 chars without sentence end join to next line even if capitalized (`Philosophical` / `Necessity`).
- **Imprint lines** — publisher lists (Locke-style) merge across wraps and spurious blank lines.
- **Wikisource cleanup** — `normalize_wiki_source()` drops nav/metadata lines for `plain` family.
- **Zero-width lines** dropped at ingest.

### Grotius Latin epigraph

When `work_id` starts with `grotius--`, blocks between two `hr` lines containing Latin legal vocabulary (`igitur`, `societatem`, …) promote middle block to `blockquote`.

## Inline spans (rule-only)

Applied to `paragraph`, `blockquote`, `heading`, `verse_line`. Offsets are into block `text` after merge; `text` field on span duplicates the matched substring.

Scan order: `_em_` → `~strong~` → straight/curly quotes → guillemets `«»` → corner quotes `「」` → `[brackets]` → `(parens)`.

| `style` | Pattern | Classifier |
|---------|---------|------------|
| `footnote` | `[178]`, `[1, 2]` | digits only inside `[]`; optional `note` is the dump body from a chapter-end `FOOTNOTES:` section (heading must be exactly `FOOTNOTES`; dump ends at `CHAPTER`/`BOOK`/`VOLUME`/`PART`, not `CHƯƠNG`) |
| `bracket_note` | `[The Cambridge Modern History, …]` | ≥18 chars or ≥3 spaces or long proper noun |
| `bracket_cite` | `[Pol.]` | short alphabetic cite |
| `bracket_other` | other `[…]` | fallback |
| `paren_page` | `(42)` | 3–4 digit page refs |
| `list_marker` | `(1)`, `(2)` | scholastic article list markers |
| `paren_cite` | `(Politics)`, `(as X also says)` | ≤6 words, or starts `as/see/cf./e.g./i.e.` |
| `paren_quote` | long parenthetical with inner quotes | ≥40 chars or ≥5 words |
| `paren_aside` | other `(…)` | fallback |
| `quote` | `"…"`, `«…»`, `「…」` | matched pair |
| `em` | `_word_` | Gutenberg underscore emphasis |
| `strong` | `~word~` | Gutenberg tilde emphasis (not Markdown `~~`) |

Nested markers: bracket spans suppress re-parsing of inner parens. Overlaps: prefer narrower `footnote` over wide bracket note.

## REF/1 document fields

| Field | Rule |
|-------|------|
| `edition_format` | always `"ref/1"` |
| `edition_hash` | SHA-256 of canonical `blocks` JSON |
| `content_kind` | `prose` / `verse` / `scholastic` / `mixed` from block mix + family |
| `language` | BCP-47 base (`en`, `vi`, …) |
| `source_family` | family used for labeling |
| `blocks` | non-empty array |
| `reading_markdown` | blocks joined with `\n\n`; `hr` → `---`; blockquote → `> ` |
| `split_hints` | headings with `level` ≤ 2 |
| `quotation_profile` | aggregate span counts, `detector: "rule"` |

Validation: `ref_schema.validate_edition()` — zero errors required for publish.

## QA (how to know parse is not wrong)

Two layers — run both before trusting a new parser change.

### 1. Rule checks (free, always on)

`run_fidelity_checks(source, edition)` in `fidelity.py`:

| Check | What it catches |
|-------|-----------------|
| `schema` | Invalid REF/1 fields / span offsets |
| `text_subsequence` | Rewritten words, missing text, garbled joins |
| `markdown_consistency` | `reading_markdown` ≠ `blocks_to_markdown()` |
| `span_offsets` | Span text not matching block slice |
| `block_sanity` | Absurd block counts / empty paragraphs |

Text preservation uses **compact subsequence**: all non-whitespace characters in blocks must appear in the same order in the source text fed to the parser (post-strip). Whitespace-only and apparatus drops are allowed.

### 2. LLM review (optional, uses `translation.models.qa`)

`qa_read_edition()` / `parse_and_qa()` sends source excerpt + block digest to the QA model. Returns scores 1–10:

- `text_preservation`, `block_structure`, `join_quality`, `inline_spans`, `overall`
- `issues[]` with `block_index`, severity, Vietnamese notes
- `verdict`: `pass` | `warn` | `fail`

CLI:

```bash
# Rule checks only (no API cost)
knowledgehub ref-qa --corpus grotius_treatise --no-llm

# Rule + LLM on one sample
knowledgehub ref-qa --corpus nam_cao_chi_pheo

# Full corpus LLM QA (~14 API calls)
knowledgehub ref-qa --corpus all --min-overall 7
```

Python:

```python
from knowledgehub.edition import parse_and_qa

edition, parse_report, qa_report = parse_and_qa(text, language="vi", family="plain", strip_first=False)
assert qa_report["fidelity"]["passed"]
assert qa_report["passed"]  # requires LLM pass when use_llm_qa=True
```

Unit tests mock LLM; live check: `pytest tests/test_ref_qa.py -m llm -v`.

## Corpus test fixtures

Real excerpts live under `tests/fixtures/ref_corpus/`:

- **EN (8):** Grotius, Locke, Dickens, Aquinas, Aristotle, Mill, Whitman, Shakespeare — Project Gutenberg excerpts (~4k chars each).
- **VI (6):** Grotius translation segment, Nam Cao, Hồ Xuân Hương, Lê Kiến, Lê Văn Đại, Bà Huyện Thanh Quan — Wikisource HTML or Hub translation.

Regenerate with `scripts/build_ref_corpus_fixtures.py`. Expectations in `tests/fixtures/ref_corpus/expectations.json`.

## LLM (optional)

`use_llm=True` relabels only low-confidence line segments (`confidence < 0.85`). Inline spans and text merge stay rule-based. Default in tests and publish: `use_llm=False`.

## Not in REF/1 v1

- Read-side rendering of `spans[]`
- OCR column reflow beyond `archive_scan` unwrap

## REF/1 v1.3 block types

| `type` | Notes |
|--------|--------|
| `list_item` | Scholastic `(1) Whether…` items |
| `dialogue` | `speaker` + `text` (Shakespeare PG) |
| `stage_direction` | `Enter …`, `[Aside]` |
| `stanza` | Grouped `verse_line` / lục bát (lines joined with `\n`) |
| `metadata` | Wikisource nav — also listed in `apparatus_dropped[]` when stripped |

`content_kind`: `prose` | `verse` | `scholastic` | `mixed` | `drama`

Corpus: **50 samples** (EN 39 incl. archive_scan, VI 9, JA 2).
CI: `.github/workflows/ref-corpus.yml` runs corpus tests + rule QA on each PR.

## REF/1 v1.4 — PG table of contents

- **TOC detection** — runs of 3+ `CHAPTER`/`BOOK`/`SECT` list lines → single `metadata` block (not `heading`). `CHƯƠNG …` rows are not `is_toc_entry_line`; `MỤC LỤC` is a valid opener but does not by itself merge Vietnamese chapter rows.
- **Split chapter titles** — `CHAPTER III. OF THE RISE…` + continuation line merged before labeling.
- **False heading fix** — `PART`/`BOOK` patterns require numerals (`PART IV` ok; “part of his property” no longer matches).
- **Strip path** — `strip_only` + `preserve_toc` in REF parser; explicit `family=` is no longer overwritten by strip detection.
- **`reading_markdown`** — includes `metadata` text (TOC blocks) for fidelity checks.

## REF/1 v1.5 — drama + corpus markers

- **Speaker cue guard** — `CHAPTER`/`ACT`/`SCENE` lines are never speaker cues (fixes Twain false `dialogue`).
- **Dramatis Personæ** — cast list merged into one `metadata` block before dialogue parsing.
- **Corpus markers** — PG fixtures use body-text markers (`Call me Ishmael`, `It is a truth…`) not TOC `CHAPTER I`.
- **LLM QA prompt** — documents that TOC→`metadata` and `apparatus_dropped[]` are intentional.

## REF/1 v1.7 — QA round 2 (TOC, PG prose, speaker cues)

| Group | Change |
|-------|--------|
| **TOC** | `CHAPTER I.` trailing period; title/em-dash wrap lines; Letter/Chapter N + VI roman numerals; stop TOC at first body paragraph; merge metadata runs |
| **PG prose** | Indented hard-wrap (Smith) → `paragraph` not `stanza`; Whitman comma-ended indent → `verse_line` |
| **Speaker cues** | Exclude `CONTENTS`, `PREFACE`, roman dates (`M. DCC. LXV.`), short words (`TO`, `BY`) |
| **Scholastic/PG notes** | `NOTE TO THIS ELECTRONIC EDITION` → `metadata`; `Prologue, and…` mid-sentence not heading |
| **Quotes** | Long quoted prose → `paragraph`; join quoted continuations; merge adjacent `blockquote` |

Five rule groups (not per-sample hacks):

| Group | Change |
|-------|--------|
| **Scholastic** | `Objection` / `Obj.` / `_On the contrary_` / `_I answer that_` → `paragraph`, not `heading` L3 |
| **Drama** | `ACT` L1 and `SCENE` L2 stay separate; dialogue lines join on comma / bracket-cite wrap |
| **Join/reflow** | Title abbrevs (`Dr.`, `Heb.`) don't end sentences; incomplete `[cite` wraps join; PG wrap joins across sentences when no blank line |
| **Verse** | Poetry runs (footnote/comma lines, blank-separated) → `verse_line` → `stanza` |
| **TOC** | `CONTENTS` blocks → `metadata`; double-space mid-line no longer triggers false TOC (Poe fix) |
| **Inline** | `(1)` list markers; full `paren_aside` spans; QA digest shows complete span text |

## REF/1 v1.9 — per-chapter FOOTNOTES

Gutenberg chapters often end with a `FOOTNOTES:` dump. Inline `[n]` spans now copy that dump onto `span.note`, and the chapter document lists `notes[]`.

| Source form | Example |
|-------------|---------|
| Numbered dump (Abdy Williams) | `[1] See Glossary, "College of Instrumental Musicians."` — publish resolves the quoted headword against the Glossary chapter and sends the entry body on the note |
| Gutenberg bracket (Bergson) | `[Footnote 3: _Matière et mémoire_, Paris, 1896.]` |

Every `FOOTNOTES:` heading followed by those items is a dump (item run only — not until the next `CHAPTER` line, so wrap like `CHAPTER III of the later volume.` stays inside the note, and mid-chapter prose after the dump is kept). Numbering is **per dump**: a later chapter’s `[1]` does not replace an earlier chapter’s `[1]`. Dump blocks are dropped from REF reading flow after the bodies are copied onto inline markers. `NOTES TO …` essays are still kept as body text. CMS Chế bản shows the note body on hover (tooltip truncated) and in a list at the end of the chapter.

