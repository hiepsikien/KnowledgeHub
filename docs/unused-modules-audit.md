# Audit: luồng / module không còn dùng

> Snapshot 2026-09-04. Static import + route UI vs `cli.py` / `server.py`.  
> **Chưa xóa code.** Việc dọn nằm ở [cleanup-backlog.md](./cleanup-backlog.md).

**Kết luận:** không có package Python mồ côi. Phần khó maintain là **hai thế hệ chế bản chồng trong cùng module**, cộng harness thử nghiệm parser/macro và vài API không ai gọi.

## Luồng curator hiện tại

```
Tác phẩm → allow Read
        → Chế bản (macro → HITL TOC/layout → parse từng section → QA → Final Touch)
        → Publish to Read
Dịch thuật = desk riêng (pilot Grotius)
```

`publish-read` **bắt buộc** package chế bản đã parse — không còn tự normalize cả cuốn lúc publish.

## Còn dùng (giữ)

| Luồng | Vào từ | Module chính | Ghi chú |
|-------|--------|--------------|---------|
| Catalog + curator | UI Tác phẩm / License / Cài đặt | `catalog`, `server`, `validate`, `hash`, `licenses` | Nguồn sự thật `works.json` |
| Chế bản 2 bước | UI Chế bản + jobs worker | `read_edition_steps`, `macro*`, `hitl_ops`, `ref`, `edition/jobs` | strip → structure → micro parse |
| Publish Read | UI Publish + CLI `publish-read` | `read_publish`, `figures`, `footnotes` | Require package chế bản |
| Dịch thuật | UI Dịch thuật + CLI `translate` | `translation/*`, `grotius_extract`, `translation/fetch` | Pilot Grotius — vẫn live |

## Đã thay — one-shot Read Edition (v1)

`edition/read_edition.py` vẫn chứa pipeline cũ: parse cả cuốn rồi cắt chapter theo `split_hints`. UI / worker / publish **không** đi đường này. Macro + parse từng section sống ở `read_edition_steps.py`.

| Hàm | ~dòng | Ai gọi |
|-----|-------|--------|
| `build_read_edition_package` | 90 | `test_ref_bugfixes` + `qa_all_chapters` |
| `resolve_edition` | 70 | chỉ package builder v1 |
| `split_edition_chapters` | 50 | package builder + 1 unit test |
| `read_edition_dir` | 5 | trùng `package_root` (cùng path) |
| `chapter_document` | 15 | chỉ package builder v1 |
| `qa_all_chapters` | 25 | **không ai gọi** |
| `effective_edition` | 15 | **không ai gọi** |

**Giữ:** `load_manifest`, `load_chapter`, `package_status`, `qa_read_edition_chapter`, `chapters_for_translation` — vẫn phục vụ CMS.

## HTTP

### Chết hẳn (0 callers: UI + pytest)

- `GET /api/authors` — không có trang author
- `GET /api/works/{id}/read-edition/structure` — UI đọc `/review`. `POST …/structure/edit` vẫn live

### Trùng (UI dùng jobs; pytest còn gọi sync)

Không phải dead code. TestClient hit thẳng. Đừng xóa trước khi sửa test.

- Chế bản: `POST …/macro`, `…/parse`, parse-batch, `…/qa`
- Dịch: `POST …/draft/{chapter}`, `…/qa/{chapter}`, `…/annotate/{chapter}` (approve / reopen vẫn dùng từ UI)

## CLI

| Lệnh | Vai trò | Gợi ý |
|------|---------|-------|
| `serve`, `publish-read`, `allow-read`, `hash`, `validate`, `show`, `build-catalog` | Sản phẩm | Giữ |
| `edition` | Preview normalize cả cuốn (pipeline cũ) | Xóa hoặc ghi rõ là debug strip+REF |
| `ref-qa` | Harness QA parser trên fixture | Giữ nếu còn tune parser; không phải curator flow |
| `export-read-edition` | CLI chế bản 2 bước | Giữ — automation / không mở UI |
| `translate *`, `fetch-raw`, `ingest-images` | Song song UI | Giữ. `fetch-raw` chỉ Grotius |

## Script thử nghiệm

`scripts/hub.sh` = `npm run hub` — **giữ**. Chín file còn lại không nằm trên đường curator:

| File | Loại |
|------|------|
| `ingest_group_a.py` | One-shot Wikisource VN |
| `run_macro_batch.py` | Eval macro 50 mẫu |
| `run_macro_corpus_test.py` | Eval macro |
| `run_macro_completeness_test.py` | Eval completeness |
| `run_macro_profile_compare.py` | So strategy macro |
| `expand_ref_corpus_50.py` | Sinh fixture corpus B |
| `export_ref_corpus_from_hub.py` | Export raw → fixture |
| `run_dual_corpus_qa.py` | QA corpus A vs B |
| `build_ref_corpus_fixtures.py` | Build fixture |

JSON report trong `tests/fixtures/ref_corpus/` (`macro_batch_*.json`, `macro_qa_report.json`, `macro_completeness_report.json`, snapshot QA v16/v17) là output chạy tay. Pytest gần như không đọc — trừ `qa_report.json` (test skippable).

**Giữ** text fixture `ref_corpus` / `ref_corpus_b` — regression parser vẫn cần.

## Đừng nhầm là unused

- `normalize.py` → `build_edition` full book: CLI `edition` và `translate init` vẫn gọi. **Strip-only** của cùng pipeline là bước 1 chế bản.
- `classify.py` + `cache.py` (`corpus/editions/`): chỉ chạy trên full-book parse, không trên micro parse. Xóa thì phải đổi `translate init` trước.
- `grotius_extract.py` / `translation/fetch.py`: hẹp (một tác phẩm) nhưng desk dịch còn sống.

## Docs lệch code

- README / `PROJECT.md` mô tả Hub API `GET /hub/works` — chưa implement. Publish được viết như normalize-on-the-fly; code hiện require chế bản.
- `hub-evolution.md` = audit Think Phase 0 (lịch sử).
- `final-touch-plan.md` = sprint note đã phần nào vào parser.

## Phương pháp

Audit tĩnh: import graph từ `cli.py` / `server.py` / `web/app.js` / `web/read-edition.js`, đối chiếu pytest. Không chạy coverage runtime.
