# Knowledge Hub

Central catalog and distribution layer for literary corpora. **Knowledge Hub** is the single source of truth for works (plain-text manuscripts, authors, licenses, and publication state). Consumer apps subscribe to published snapshots — they do not own the canonical corpus.

> **Tài liệu đầy đủ (Tiếng Việt):** [docs/PROJECT.md](./docs/PROJECT.md)

## Related projects

| Project | Role |
|---------|------|
| [Think](https://github.com/hiepsikien/Think) | Consumer — salon RAG (chunks). Does not own the Hub catalog |
| [Read](https://github.com/hiepsikien/Read) | Consumer — library + reader + TTS; Hub posts plain text to `/api/internal/hub/works` |

## Problem

Corpus today:

- Works are **plain `.txt` files** (no DOCX, no character glossary, no series hierarchy).
- **Author and metadata exist but are inconsistent** — needs normalization.
- **License information** is tracked in Think CMS but not yet exposed as a platform API.
- Think and Read each need the same content with different delivery shapes.

Building a separate greenfield CMS would duplicate corpus and license work already done in Think.

## Solution

**Knowledge Hub** (this repo) owns manuscripts, authors, licenses, and publish state.

1. Catalog: `corpus/catalog/works.json` + `authors.json` (stable work ids).
2. Files: `corpus/sources/<brain>/raw/*.txt` (gitignored).
3. **Read** receives a materialized copy via `knowledgehub publish-read`.
4. **Think** may still chunk from `sources/` for RAG — it is not the catalog admin.

```
KnowledgeHub catalog + raw txt
        │
        ├── knowledgehub publish-read ──▶ Read books (hub_work_id)
        └── optional Think ingest ─────▶ salon chunks
```

## Curator UI

Local admin for the catalog — search works, toggle Read rights, dry-run then publish.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/knowledgehub serve          # http://127.0.0.1:8787
# Publish to Read: /publish/{work_id} — category, split length, price, blurb (Read presets)
```

If `KNOWLEDGEHUB_OPS_SECRET` is unset, the UI is open on localhost. Set the secret to require login.

`serve` and CLI commands load `.env` from the repo root (`cp .env.example .env`). Shell `export` still wins over the file.

Publish still needs `READ_API_URL` (default `http://127.0.0.1:8000`) and `READ_HUB_TOKEN` (same as Read `HUB_SYNC_TOKEN`). Default Read status is `pending_review`. `publish-read` sends a **normalized** edition (Gutenberg wrappers, eBook notes, front TOC dumps stripped, hard-wrap lines joined into paragraphs). Source `raw/*.txt` is unchanged; `content_hash` still hashes the file on disk.

## Translation desk (pilot)

Curator tab **Dịch thuật** (`/translation/{work_id}`) for Grotius — *The Freedom of the Seas*: QA scores, EN ↔ VI, annotations. Pipeline docs: [docs/translation.md](./docs/translation.md). Needs `DEEPSEEK_API_KEY` and `GEMINI_API_KEY` in `.env`.

```bash
.venv/bin/knowledgehub translate init --work grotius--freedom_of_the_seas
.venv/bin/knowledgehub translate draft-sample --work grotius--freedom_of_the_seas --mode tight
.venv/bin/knowledgehub translate select-mode --work grotius--freedom_of_the_seas --mode tight
.venv/bin/knowledgehub translate draft --work grotius--freedom_of_the_seas --chapter II
```

## CLI

```bash
.venv/bin/knowledgehub build-catalog   # from sources/*/works.json
.venv/bin/knowledgehub validate
.venv/bin/knowledgehub hash            # SHA-256 of local raw files
.venv/bin/knowledgehub allow-read --work locke--second_treatise
.venv/bin/knowledgehub publish-read --work locke--second_treatise
.venv/bin/knowledgehub publish-read --work locke--second_treatise --apply
.venv/bin/knowledgehub translate draft --work grotius--freedom_of_the_seas --chapter I
```

## Core concepts

### Work

One published unit = **one `.txt` file** + normalized metadata.

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | Stable slug or UUID — never changes |
| `title` | yes | Display title |
| `author_id` | yes | Reference to `authors` table |
| `language` | yes | BCP-47, e.g. `vi`, `en` |
| `description` | recommended | Blurb for catalogs |
| `tags` / `genre` | optional | Fiction, essay, history, … |
| `content_hash` | yes | SHA-256 of `content.txt` |
| `status` | yes | `draft` · `review` · `published` · `archived` |
| `version` | yes | Incremented when content changes |

**Not in v1:** series, season, episode, character glossary.

### Author

Authors are first-class entities (not free-form strings):

```yaml
id: author-slug
name: "Display Name"
name_sort: "Sort Key"
aliases: []
bio: ""
```

### License & rights

License stays close to the Think CMS model, extended for multi-consumer distribution:

```yaml
rights:
  basis: public_domain | licensed | original | editorial_derivative
  attribution_required: true
  attribution_text: "…"
  consumers:
    think: allowed
    read:
      distribution: allowed | preview_only | blocked
      pricing_default: free
```

**Public domain note:** PD works may still be sold on Read when the fee covers platform service and/or a substantial editorial edition — not exclusive ownership of the PD text. See project discussions for product/legal design (not legal advice).

### Publication

Publishing a work creates a **versioned snapshot** for one or more consumers:

```yaml
work_id: example-work
version: 3
consumers: [think, read]
published_at: "2026-08-26T00:00:00Z"
```

## Read integration model (sync-copy)

Read **stores full text locally** after sync — it does **not** fetch chapter content from Hub on every read.

| Stored in Read | Source |
|----------------|--------|
| `books.hub_work_id`, `hub_version`, `hub_content_hash` | Hub metadata |
| `books.raw_text` | Hub `content.txt` at sync time |
| `chapters.content` | Read smart-split pipeline |
| `hub_license_snapshot` | JSON audit at sync time |

Hub remains authoritative for **editing and republication**. Read re-syncs when `content_hash` / `version` changes.

## Hub API (target)

| Endpoint | Purpose |
|----------|---------|
| `GET /hub/works?status=published&consumer=think` | List for Think |
| `GET /hub/works/{id}` | Work metadata + license |
| `GET /hub/works/{id}/content` | Plain text body |
| `GET /hub/authors/{id}` | Author record |
| `GET /hub/exports/read/delta?since=` | Incremental sync for Read |
| `POST /hub/internal/works/{id}/publish` | Admin publish |

Service tokens authenticate Read sync and automation — separate from human admin sessions.

## Implementation strategy

**Phase 0 — Audit** (blocked on Think repo access)

- Map `apps/cms` models, corpus layout, license fields.
- Document gaps in `docs/hub-evolution.md` inside Think or this repo.

**Phase 1 — Platform layer on Think CMS**

- `content_version`, `content_hash`, `publications`.
- License consumer flags (`think`, `read`).
- Hub read API v1.

**Phase 2 — Think app refactor**

- Replace direct corpus file reads with Hub API (feature-flagged).

**Phase 3 — Read sync**

- `sync_from_hub` job in Read API.
- Pilot works: Hub publish → Read library.

**Phase 4 — Metadata normalization**

- Author deduplication, review queue, bulk publish.

## Repository layout

```
KnowledgeHub/
  corpus/catalog/     ← authors.json + works.json (managed here)
  corpus/sources/     ← Think-shaped works.json + raw/*.txt
  src/knowledgehub/   ← CLI, curator UI, publish-read
Think/                ← salon + derived chunks
Read/                 ← reader; POST /api/internal/hub/works
```

See [corpus/README.md](./corpus/README.md).

## Status

Catalog, curator UI (`knowledgehub serve`), Read publisher, and a Grotius translation desk are in this repo. Phase 0 Think audit: [docs/hub-evolution.md](./docs/hub-evolution.md).

## Links

- Read project docs: https://github.com/hiepsikien/Read/blob/main/docs/PROJECT.md
- Think (private): https://github.com/hiepsikien/Think

---

*Maintained as the canonical product brief for Knowledge Hub.*
