# Canonical corpus (Knowledge Hub)

This directory is the **source of truth** for manuscripts and ingest metadata. Think and Read consume it; they do not own the original `.txt` files.

```
corpus/
  licenses.json              # license catalog (ids used in works.json)
  sources/<brain>/
    works.json               # one row per .txt (title, year, license, source_url, file)
    raw/<file>.txt           # full text — gitignored, not on public GitHub
```

`<brain>` is still Think’s thinker id (Phase 1 keeps this layout so ingest is a path swap). Work-level UUIDs come later.

## What stays in Think

| Think `corpus/` | Why |
|-----------------|-----|
| `forests/`, `profiles/`, `registry/` | Salon compass + shelf — Think product |
| `sources/<brain>/chunks/` | Derived RAG windows — regenerate via ingest |
| GCS runtime tree | Forests + chunks + a **mirror** of `works.json` |

## Think ingest

On the curator machine:

```bash
# Think repo `.env`
KNOWLEDGEHUB_CORPUS=/Users/andynguyen/projects/KnowledgeHub/corpus
```

Then `python3 scripts/ingest_pd.py --brain <id>` reads `works.json` + `raw/` **from this tree** and writes `chunks.jsonl` into Think.

`scripts/fetch_raw_pd.py` downloads into `corpus/sources/<brain>/raw/` here, not into Think.

Cloud Run does **not** set `KNOWLEDGEHUB_CORPUS`. Runtime retrieve uses Think/GCS chunks plus the mirrored `works.json`.

## Do not commit `raw/`

Public repo = metadata only. Keep manuscripts on disk (or a private bucket) and gitignore `corpus/sources/*/raw/`.
