# Backlog: dọn module / luồng cũ

Nguồn: [unused-modules-audit.md](./unused-modules-audit.md) (2026-09-04).  
Trạng thái: **chưa làm** — tick khi quyết định + merge.

Quy ước: `[ ]` chưa quyết định · `[x]` xong · `[-]` bỏ qua (ghi lý do).

---

## Đợt 1 — an toàn (rủi ro thấp)

Ít đụng test. Có thể làm độc lập từng mục.

- [ ] **C1.1** Xóa `qa_all_chapters` (`edition/read_edition.py`) — 0 callers
- [ ] **C1.2** Xóa `effective_edition` (`edition/read_edition.py`) — 0 callers
- [ ] **C1.3** Xóa `GET /api/authors` (`server.py`)
- [ ] **C1.4** Xóa `GET /api/works/{id}/read-edition/structure` + `get_structure` (`server.py`, `read_edition_service.py`). **Giữ** `POST …/structure/edit`
- [ ] **C1.5** Xóa JSON eval report không phục vụ pytest:
  - `tests/fixtures/ref_corpus/macro_batch_*.json`
  - `macro_qa_report.json`, `macro_completeness_report.json`
  - snapshot `qa_report_v16.json` / `qa_report_v17.json` (cả corpus A/B nếu có)
  - `tests/fixtures/ref_corpus_qa_dual_v16.json`
  - **Giữ** `qa_report.json` nếu còn test skippable, hoặc xóa cả test
- [ ] **C1.6** Xóa hoặc archive `scripts/` eval / one-shot (giữ `hub.sh`):
  - `ingest_group_a.py`
  - `run_macro_batch.py`, `run_macro_corpus_test.py`, `run_macro_completeness_test.py`, `run_macro_profile_compare.py`
  - `expand_ref_corpus_50.py`, `export_ref_corpus_from_hub.py`, `run_dual_corpus_qa.py`, `build_ref_corpus_fixtures.py`

Quyết định trước C1.6: còn rerun eval macro/REF không? Nếu có, archive (`scripts/archive/`) thay vì xóa.

---

## Đợt 2 — gỡ chế bản v1 (rủi ro trung bình)

Sau đợt này `read_edition.py` chỉ còn I/O package 2 bước.

- [ ] **C2.1** Gỡ one-shot: `build_read_edition_package`, `resolve_edition`, `split_edition_chapters`, `read_edition_dir`, `chapter_document`
- [ ] **C2.2** Sửa / xóa `tests/test_ref_bugfixes.py` (và unit test `split_edition_chapters` / `chapter_document` trong `test_read_edition_export.py`)
- [ ] **C2.3** CLI `edition` — **chốt một:**
  - (a) xóa lệnh
  - (b) giữ, ghi help: debug strip+REF cả cuốn, không phải curator flow
- [ ] **C2.4** CLI `ref-qa` — **chốt một:** giữ harness parser / xóa nếu không còn tune REF

Phụ thuộc: C2.1 sau C1.1–C1.2 (các hàm chết nằm trên cùng file).

---

## Đợt 3 — một đường UI ↔ server (rủi ro cao hơn)

- [ ] **C3.1** Gộp sync POST chế bản (`macro` / `parse` / `qa`) vào jobs; chuyển pytest (`test_hitl_ops`, `test_edition_jobs`, `test_read_edition_export`) sang enqueue + worker hoặc gọi service layer trực tiếp
- [ ] **C3.2** Gộp sync POST dịch `draft` / `qa` / `annotate` vào jobs; giữ approve / reopen. Sửa `test_translation_api.py`
- [ ] **C3.3** `translate init` dùng chapter chế bản (`sync-ref-chapters` / `chapters_for_translation`) thay vì `normalize_manuscript` cả cuốn
- [ ] **C3.4** Sau C3.3: cân nhắc xóa `classify.py` + cache `corpus/editions/` nếu không còn full-book parse

Không làm C3.4 trước C3.3 / C2.3 — `translate init` và CLI `edition` vẫn wired vào full-book.

---

## Docs (có thể làm bất kỳ lúc nào)

- [ ] **D1** README + `PROJECT.md`: publish require chế bản; Hub API `GET /hub/works` là mục tiêu chưa implement
- [ ] **D2** Giữ `hub-evolution.md` / `final-touch-plan.md` như lịch sử, hoặc đánh dấu “archived sprint note” ở đầu file

---

## Không đụng (trừ khi thu hẹp scope sản phẩm)

- Catalog UI, chế bản 2 bước, publish-read, desk dịch Grotius
- Text fixture `tests/fixtures/ref_corpus/` và `ref_corpus_b/`
- `grotius_extract.py`, `translation/fetch.py` khi desk dịch còn
- `scripts/hub.sh`

---

## Ghi chú quyết định

| Ngày | Mục | Quyết định |
|------|-----|------------|
|  |  |  |
