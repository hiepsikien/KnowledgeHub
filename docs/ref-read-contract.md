# REF ↔ Read contract (pilot)

Frozen surface for the first three English Hub → Read pilots. Hub may send richer REF; Read **must** honor this subset. Anything outside this list is best-effort / ignored.

## Pilot works

| Hub work id | Title on Read |
|-------------|---------------|
| `arnold--essays_in_criticism` | Essays in Criticism (Arnold) |
| `bastiat--economic_sophisms` | Economic Sophisms (Bastiat) |
| `bach--abdy_williams` | Bach (Abdy Williams) |

Re-publish only after every Chế bản chapter is **Ready** (`micro_status=complete`).

## Payload Hub → `POST /api/internal/hub/works`

### Always (legacy + REF)

| Field | Type | Read behavior |
|-------|------|----------------|
| `hub_work_id` | string | upsert key |
| `hub_version` | int | version stamp |
| `hub_content_hash` | string | idempotency |
| `title`, `description`, `language`, `license`, `category_slug`, `price_cents`, `status` | — | catalog |
| `raw_text` | string | **fallback** body if `chapters` absent; still required (≥1 char) |
| `credits` | object? | author / translator lines |
| `glossary` | list? | cast / term entries |
| `notes` | list? | footnote cards (preferred over scraping `raw_text`) |

### REF/1 (required for pilots)

| Field | Type | Read behavior |
|-------|------|----------------|
| `edition_format` | `"ref/1"` | store; gate structured path |
| `edition_hash` | sha256 hex | store; detect unchanged edition |
| `content_kind` | `prose` \| `verse` \| `scholastic` \| `mixed` \| `drama` | store; reader layout hint |
| `reading_markdown` | string | full-book markdown; used if chapters omitted |
| `blocks` | array | full-book blocks; store for future / TTS; chapter path preferred |
| `split_hints` | array? | heading indices; used only if `chapters` omitted |
| `quotation_profile` | object? | ignored in pilot UI |
| `chapters` | array? | **preferred split** — do **not** re-run `split_into_chapters` when present |

### `chapters[]` item

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | stable Hub chapter id (`ch-001`, …) |
| `title` | yes | sidebar / reader title |
| `content` | yes | chapter `reading_markdown` (plain + `_em_` + footnote markers) |
| `blocks` | no | REF blocks for this chapter; when present, reader prefers block render |
| `word_count` | no | Hub hint; Read may recompute |

### `notes[]` item (footnote)

| Field | Required | Notes |
|-------|----------|-------|
| `id` | no | Hub id if any |
| `kind` | yes | `footnote` for pilot |
| `label` | yes | display name, e.g. `Seneca [4]` |
| `marker` | yes | in-text marker, e.g. `[4]` |
| `anchor` | no | nearby phrase |
| `chapter` | no | Hub chapter label / id |
| `body` | yes | note text |
| `group_label` | no | default `Chú thích` |

Hub builds `notes` from REF `span.note` / chapter `notes[]` (not from FOOTNOTES dumps left in `raw_text` — dumps are already stripped from reading flow).

## Block types Read honors (pilot)

| `type` | Render |
|--------|--------|
| `heading` | `<h{level}>` (1–4) |
| `paragraph` | `<p>` + inline spans |
| `blockquote` | `<blockquote>` |
| `verse_line` | line in verse block (no reflow) |
| `stanza` | verse group; lines separated by `\n` |
| `hr` | thematic break |
| `metadata` | skip in reader (apparatus) |
| `list_item`, `dialogue`, `stage_direction` | render as paragraph for pilot |

## Inline span styles Read honors (pilot)

| `style` | Render |
|---------|--------|
| `em` | italic |
| `footnote` | tappable marker → note body (`span.note` or `notes[]`) |
| `quote` | keep glyphs; optional subtle style |
| `bracket_note`, `paren_cite`, `paren_quote`, `paren_aside`, `paren_page`, `bracket_cite`, `bracket_other`, `list_marker` | keep text; no special chrome in pilot |

Offsets are into the block `text` after Hub merge. Read must not re-parse markers when `blocks` are present.

## Split rules

1. If `chapters` non-empty → use as-is (order preserved).
2. Else if `split_hints` + `blocks` → Hub-compatible split (future).
3. Else → legacy `split_into_chapters(raw_text)`.

## Out of scope for this pilot

- Read editing Hub REF
- Dual package layouts / override re-apply
- OCR column repair
- Full chrome for every span style
- TTS SSML from spans (plain chapter text still used)

## Acceptance (per pilot book)

1. Chế bản: all chapters Ready → Publish unlocked.
2. Read library shows one book; chapter list matches Hub macro sections.
3. Footnote markers open the Hub note body (Bach / Arnold where present).
4. `_italic_` / `em` spans render italic.
5. Re-publish with same `edition_hash` is a no-op (or updates metadata only).
