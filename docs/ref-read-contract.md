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
| `edition_hash` | sha256 hex | store; detect unchanged edition. Hash includes REF blocks **and** chapter `id`/`title` so a remacro/resplit is a new book. |
| `content_kind` | `prose` \| `verse` \| `scholastic` \| `mixed` \| `drama` | store; reader layout hint |
| `reading_markdown` | string | full-book markdown; used if chapters omitted |
| `blocks` | array | full-book blocks **after** the same hidden/`suppress_in_reader` filter as `chapters[].blocks` (so a Read fallback that uses book-level `blocks` does not resurrect sidenotes). Hub chapter JSON on disk still keeps the full graph. |
| `split_hints` | array? | heading indices into the published `blocks` (visible only); used only if `chapters` omitted |
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
| `host_block_id` | no | block that contains the marker; Read explain = host + body |
| `host_text` | no | full host paragraph text |
| `figures` | no | `{caption, src?}` from `[Illustration:]` in the note (Bach fn. 77); `src` is a Hub asset path. Read stores the bytes from `assets[]` and rewrites `src` to `/api/books/{id}/media/{asset}.jpg`. Never a Gutenberg hotlink. |

Hub builds `notes` from REF `span.note` / chapter `notes[]` (not from FOOTNOTES dumps left in `raw_text` — dumps are already stripped from reading flow).

### `assets[]` item (illustrations)

Hub copies Gutenberg HTML images into `corpus/assets/{work}/` (CLI `ingest-images --work`, or CMS **Lấy minh họa Gutenberg**). Publish binds already-ingested files onto unbound figures and may fetch only when a figure still lacks `src`. Matching uses HTML `alt` / `caption` / poem text under the image, not filename stems (`illot095.png` ≠ “A stronghold sure”). `[Illustration]` and `[Music]` in the TXT both become `role: figure`.

| Field | Required | Notes |
|-------|----------|-------|
| `filename` | yes | Original file name (`illoa002bs.jpg`) |
| `content_type` | yes | `image/jpeg` / `image/png` / … |
| `data` | yes | Base64 of the file bytes |

Read must persist each asset with `save_media_bytes` and rewrite `role: figure` / `notes[].figures[].src` that end with that filename to `/api/books/{book_id}/media/{asset_id}.jpg`. A relative `/assets/{work}/…` path is Hub CMS only and 404s on the Read API.

## Block types Read honors (pilot)

| `type` | Render |
|--------|--------|
| `heading` | `<h{level}>` (1–4). Skip when `suppress_in_reader` is true (duplicate chapter banner). |
| `paragraph` | `<p>` + inline spans. `role: synopsis` → italic paragraph. `role: aside` / `hidden: true` → skip. `role: figure` → caption (image `src` when present). |
| `blockquote` | `<blockquote>` |
| `verse_line` | line in verse block (no reflow) |
| `stanza` | verse group; lines separated by `\n` |
| `hr` | thematic break |
| `metadata` | skip in reader (apparatus) |
| `list_item`, `dialogue`, `stage_direction` | render as paragraph for pilot |

Hub omits `hidden` and `suppress_in_reader` blocks from the published `payload.blocks`, `chapters[].blocks`, and `reading_markdown` so an older Read still looks right. Hub chapter JSON keeps the full graph (including hidden sidenotes) for translation and Final Touch.

Identity: each block has `block_id` = `{chapter_id}:{type}:{prefix}` with `-N` on collision.

## Inline span styles Read honors (pilot)

| `style` | Render |
|---------|--------|
| `em` | italic |
| `strong` | bold (`~Adlung~` in Gutenberg, not Markdown `~~`) |
| `footnote` | tappable marker → note body (`span.note` or `notes[]`) |
| `quote` | keep glyphs; optional subtle style |
| `bracket_note`, `paren_cite`, `paren_quote`, `paren_aside`, `paren_page`, `bracket_cite`, `bracket_other`, `list_marker` | keep text; no special chrome in pilot |

Offsets are into the block `text` after Hub merge. Read must not re-parse markers when `blocks` are present.

## Read-only work (not this repo)

- Default “Giải thích thêm” language = `book.language` (EN for the three pilots); persist the dropdown.
- Explain = `host_text` + note `body`, not the currently highlighted paragraph if it drifted.
- Skip `hidden` / `suppress_in_reader` once Read is updated; until then Hub already drops them from the published payload.

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
