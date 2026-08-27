# Canonical corpus (Knowledge Hub)

Hub **manages** works here. Think and Read consume; they do not own the catalog.

```
corpus/
  licenses.json
  catalog/
    authors.json             # first-class authors (id = Think brain for now)
    works.json               # Hub Work records — stable ids
  sources/<brain>/
    works.json               # Think-shaped ingest list (legacy layout)
    raw/<file>.txt           # manuscripts — gitignored
```

Work id: `{brain}--{file_stem}` e.g. `locke--second_treatise`. Never reuse an id.

`rights.consumers.read` defaults to `blocked`. Allow then publish (CLI or curator UI):

```bash
knowledgehub serve   # http://127.0.0.1:8787
knowledgehub allow-read --work locke--second_treatise
knowledgehub publish-read --work locke--second_treatise --apply
```

Rebuild catalog after editing Think-shaped `sources/*/works.json`:

```bash
knowledgehub build-catalog && knowledgehub validate
```

Translation projects (pilot): `corpus/translations/<source_work_id>/` — see [docs/translation.md](../docs/translation.md).

## Think

Think may still set `KNOWLEDGEHUB_CORPUS` and ingest `sources/` into RAG chunks. That does not update `catalog/`.

## Do not commit `raw/`

Public GitHub = metadata only.
