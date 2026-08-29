# REF/1 format rules (Hub parser)

This document is the rule reference for `parse_manuscript_to_ref()`. Rendering in Read is out of scope here — Hub only produces validated REF/1 JSON.

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
| `Scene I.`, `ACT II`, short title case | `heading` L2–3 | `heading` |
| `_Gutenberg italic line_` | `heading` L2 | `heading` |
| ALL CAPS ≤60 chars, no sentence end | `heading` L2 | `heading` |
| `-----` (≥8 rule chars) | `hr` | `hr` |
| Indented poetry / short lines | `verse_line` | `verse_line` |
| default | `prose` | `paragraph` after merge |

### Join rules (`join_next`)

Join line *i* to *i+1* when both are `prose` and any of:

1. Previous ends with `-` and next starts lowercase → de-hyphenate glue.
2. Previous does not end `.!?` and next starts `[a-z(`.
3. Previous length ≥ ordinal wrap threshold and no sentence end.
4. Previous ends `,;:` and next starts lowercase/`(`.

Never join into/from `heading`, `hr`, `verse_line`, or after a sentence end followed by a capitalized new paragraph.

### Grotius Latin epigraph

When `work_id` starts with `grotius--`, blocks between two `hr` lines containing Latin legal vocabulary (`igitur`, `societatem`, …) promote middle block to `blockquote`.

## Inline spans (rule-only)

Applied to `paragraph`, `blockquote`, `heading`, `verse_line`. Offsets are into block `text` after merge; `text` field on span duplicates the matched substring.

Scan order: `_em_` → straight/curly quotes → guillemets `«»` → corner quotes `「」` → `[brackets]` → `(parens)`.

| `style` | Pattern | Classifier |
|---------|---------|------------|
| `footnote` | `[178]`, `[1, 2]` | digits only inside `[]` |
| `bracket_note` | `[The Cambridge Modern History, …]` | ≥18 chars or ≥3 spaces or long proper noun |
| `bracket_cite` | `[Pol.]` | short alphabetic cite |
| `bracket_other` | other `[…]` | fallback |
| `paren_page` | `(42)` | digits only, 1–4 digits |
| `paren_cite` | `(Politics)`, `(as X also says)` | ≤6 words, or starts `as/see/cf./e.g./i.e.` |
| `paren_quote` | long parenthetical with inner quotes | ≥40 chars or ≥5 words |
| `paren_aside` | other `(…)` | fallback |
| `quote` | `"…"`, `«…»`, `「…」` | matched pair |
| `em` | `_word_` | Gutenberg underscore emphasis |

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

## Corpus test fixtures

Real excerpts live under `tests/fixtures/ref_corpus/`:

- **EN (8):** Grotius, Locke, Dickens, Aquinas, Aristotle, Mill, Whitman, Shakespeare — Project Gutenberg excerpts (~4k chars each).
- **VI (6):** Grotius translation segment, Nam Cao, Hồ Xuân Hương, Lê Kiến, Lê Văn Đại, Bà Huyện Thanh Quan — Wikisource HTML or Hub translation.

Regenerate with `scripts/build_ref_corpus_fixtures.py`. Expectations in `tests/fixtures/ref_corpus/expectations.json`.

## LLM (optional)

`use_llm=True` relabels only low-confidence line segments (`confidence < 0.85`). Inline spans and text merge stay rule-based. Default in tests and publish: `use_llm=False`.

## Not in REF/1 v1

- Read-side rendering of `spans[]`
- Dialogue / speaker attribution for plays
- Verse detection for Vietnamese lục bát (short lines currently become `paragraph`)
- OCR column reflow beyond `archive_scan` unwrap
