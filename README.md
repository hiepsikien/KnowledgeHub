# Knowledge Hub

Central catalog and distribution layer for literary corpora. **Knowledge Hub** is the single source of truth for works (plain-text manuscripts, authors, licenses, and publication state). Consumer apps subscribe to published snapshots — they do not own the canonical corpus.

## Related projects

| Project | Role |
|---------|------|
| [Think](https://github.com/hiepsikien/Think) | Origin CMS (in `apps/`) — evolves into Hub admin + ingest |
| [Read](https://github.com/hiepsikien/Read) | Reading platform — syncs materialized copies for in-app reading |

## Problem

Corpus today:

- Works are **plain `.txt` files** (no DOCX, no character glossary, no series hierarchy).
- **Author and metadata exist but are inconsistent** — needs normalization.
- **License information** is tracked in Think CMS but not yet exposed as a platform API.
- Think and Read each need the same content with different delivery shapes.

Building a separate greenfield CMS would duplicate corpus and license work already done in Think.

## Solution

Evolve **Think CMS** into **Knowledge Hub**:

1. **Hub owns** canonical text + metadata + license + publish workflow.
2. **Think app** consumes Hub via API (internal consumer).
3. **Read** syncs **materialized copies** (metadata + full text + split chapters) — not live proxy on every page turn.

```
Think CMS (apps/)  ──evolve──▶  Knowledge Hub
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
              Think app                           Read sync job
           (study / AI / corpus)              (library + reader + TTS)
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

## Repository layout (future)

This repo may hold cross-cutting docs, OpenAPI specs, and shared schemas. Runtime implementation initially lives in **Think monorepo** (`apps/cms` → Hub) until the API stabilizes enough to extract.

```
KnowledgeHub/          ← this repo (docs + contracts)
Think/                 ← CMS + corpus + Hub implementation
Read/                  ← sync adapter + reader
```

## Status

**Planning / documentation.** Implementation starts after Think corpus and CMS audit.

## Links

- Read project docs: https://github.com/hiepsikien/Read/blob/main/docs/PROJECT.md
- Think (private): https://github.com/hiepsikien/Think

---

*Maintained as the canonical product brief for Knowledge Hub.*
