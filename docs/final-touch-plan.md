# Kế hoạch: Final Touch + custom rules (pilot 3 cuốn)

Checklist đọc thử Bach (Abdy Williams) trên Read, cộng `arnold--essays_in_criticism` và `bastiat--economic_sophisms`. Kế hoạch đã implement trên Hub (parser 1.10, matchers, Final Touch bước 5, inherit dịch). Read-app lockstep vẫn nằm ở repo Read.

## Kết luận

Làm đúng bản EN trên **block graph**, rồi VI kế thừa `type` / `hidden` / `block_id` và chỉ dịch `text`. Không vá bằng chuỗi tiếng Anh cứng, và **đừng nhét hết vào Final Touch**.

Ba lớp, **một màn hình curator** (view chương đã pass):

| Lớp | Việc | Ví dụ |
|-----|------|-------|
| **A. Parser** | Lỗi lặp Gutenberg | heading giả, quote giữa câu thành blockquote, `~bold~` |
| **B. Rule theo sách** | Pattern chỉ cuốn này, **chạy tự động** trong code | `[Sidenote:]`, khổ `--` đầu chương, gia phả Bach |
| **C. Final Touch** | Bước 5: xem đúng layout Read, rồi ẩn / ghép / tách / đổi type | chỗ rule còn miss |

“Custom rules nằm trong final touch” đúng về **UX** (curator chỉ thấy view chương đã pass), sai nếu hiểu là sửa tay từng dòng sidenote/gia phả. Rule tự gắn type; Final Touch chỉ sửa phần còn lệch.

Không làm **rules engine**. Không `work.read.edition.rules[]` + UI bật/tắt từng rule. Catalog/code: vài matcher Bach; curator chỉ thấy kết quả trên bước 5.

```
raw → strip → macro → parse (wrap/fn/quotes)
                 → matcher theo sách (Bach sidenote, synopsis, genealogy)
                 → Final Touch (ẩn / ghép / tách / type)   ← sau, optional
                 → publish REF + notes[]
                           ↓
              Read render  |  dịch (sau): align block_id, dịch text, giữ type/hidden
```

---

## Sprint hẹp vs để sau

| Làm trước (Hub) | Không chặn sprint này |
|-----------------|------------------------|
| Parser heading / quote / `~bold~` | Ảnh / nốt nhạc (`figure`, zip Gutenberg) |
| `block_id` lúc parse | Rewrite dịch theo block |
| Matcher Bach: sidenote, synopsis, genealogy | Dropdown ngôn ngữ Read |
| `host_block_id` + `host_text` trên notes | Bắt buộc confirm bước 5 trước Publish |
| Fixture **cả 3 pilot** (Arnold italic title vẫn heading) | CMS rules, type mới nếu Read chưa honor |

Contract REF đang **đóng băng**. Type mới (`synopsis`, `figure`, `strong`, `hidden`) Read chưa honor. Sprint 1: sửa type sang thứ Read **đã biết** (`paragraph`, `list_item`, `dialogue`) thì ship Hub trước. Field mới cần Read lockstep, hoặc tạm render synopsis như paragraph italic.

Không republish 3 cuốn cho đến khi Phase 1+2 xong trên Bach (tối thiểu quotes, heading, sidenote, genealogy, `~bold~`). Confirm-view để sau.

---

## Checklist → xử lý

### 1. Trùng tên chapter (Read chrome + sách)

Hub gửi `chapters[].title` (sidebar) và `blocks[0]` vẫn là heading `CHAPTER III`.

Sửa nhỏ: đánh heading trùng title là `suppress_in_reader` (hoặc `role: chapter_banner`). Read không render. Không xóa text — TTS/dịch vẫn thấy. Không cần Final Touch trừ khi title macro sai.

Ship Hub có thể gắn flag ngay; Read honor flag ở Phase 4. Tạm thời Read có thể so sánh title vs heading đầu chương.

### 2. Musical notes / ảnh Gutenberg

Plain `.txt` không có nốt. HTML Footnote 77 mới có illustration. Lấy ảnh được (`43650-h.zip` / `images/`). Đây là **ingest + type `figure`**, tách khỏi sprint parser. Pilot: Bach trước.

`￼` = OBJECT REPLACEMENT (ảnh/nốt không có trong txt). Đi cùng ingest figure; còn sót thì ẩn hoặc caption `[Music example]`. **Không chặn** 5 / 6 / 8 / 10.

### 3. “Giải thích thêm” lúc EN / Đức / Ý

Toàn bộ là **Read** (LLM), không phải Hub. Default = `book.language` (`en` với 3 pilot). Dropdown persist per user. Prompt: đừng nhảy theo ngôn ngữ câu trích.

### 4. Giải thích lệch một paragraph

Hai nguyên nhân chồng: parser tách `"An Wasserflüssen…"[12]` thành block lạ, rồi Read map footnote theo index sau reflow.

Hub gửi `host_block_id` + `host_text` (đoạn chứa marker). Read explain = host + note body, không lấy “paragraph đang highlight” nếu lệch.

### 5. Double quotes nhầm

Bug trong code: dòng bắt đầu `"` / `“`, ngắn → `verse_line`, rồi `merge_blocks` đổi thành `blockquote`. HITL `short_blockquote` chỉ để curator reject từng cái.

Sửa parser: quoted fragment giữa prose (có `;` / `[n]` / dòng sau lowercase) không được thành verse/blockquote. Span `quote` chỉ khi cặp đóng đủ.

### 6. Đoạn thành heading

Cũng đúng code: ALL CAPS ≥8 chữ, &lt;90 ký tự → heading (`JOHANN NICOLAUS, 1653-1682.`, `DER SUPERINTEND.`). Cả dòng `_italic_` → heading (`_Sons of Johann…_`).

- Cue thoại ngắn ALLCAPS+`.` → `dialogue`, không heading.
- ALLCAPS+năm → `list_item`.
- Italic-line **không** auto heading nếu không phải CHAPTER/BOOK.

**Cảnh báo:** sửa heading toàn cục dễ gãy Arnold. Essay title italic có thể đang sống nhờ `ITALIC_LINE` → heading. Fixture **cả 3 pilot**, không chỉ Bach.

`list_item` và `dialogue` Read đã render như paragraph — dùng được ngay, không cần type mới.

### 7. Khổ đầu chương nối bằng `--` / `—`

Synopsis in-book, không phải body. Matcher Bach (và Master Musicians cùng layout): block đầu sau heading chương, mật độ `—` cao → `synopsis`. Không bắt em-dash trong đoạn thường.

Cho đến khi Read honor `synopsis`: Hub vẫn gắn type (TTS/dịch cần biết) **hoặc** tạm `paragraph` + `role: synopsis` / italic spans. Chốt trước khi code (mục Quyết định).

### 8. `[Sidenote: …]`

Parser hiện không nhận — thành prose/heading. Parse → aside, **default ẩn** (`hidden: true`; nhiều cái là running header). Curator hiện lại trong Final Touch nếu là nhãn mục. Không để literal `[Sidenote:` trong body.

Strip Gutenberg **không** nuốt `[Sidenote:]` trước matcher.

`hidden` là field mới — Read lockstep (Phase 4) hoặc Hub drop sidenote khỏi `reading_markdown` / reader blocks nhưng giữ trong edition để dịch. Đề xuất: ẩn default, curator lật trong Final Touch.

### 9. Final Touch

Bước 5 Chế bản, preview sát Read. Ops: ẩn (soft `hidden: true`, không xóa), hiện, ghép, tách tại caret, đổi type. JSON editor giữ cho debug.

Patch theo **`block_id`**, không theo `block_index` (index gãy khi merge/re-parse).

`block_id` **phải có ở Phase 1**, không để Phase 5. Hash “vị trí + prefix” cũng gãy. Matcher: `(chapter_id, prefix, type)` — re-parse → UI **stale patch** rõ ràng.

`set_text` đánh `lexical: true` — không copy sang VI.

Mở rộng `apply_block_patches` (hiện chỉ đổi type/text + `merge_with_next`).

Publish: **chưa** bắt buộc confirm bước 5. Sách bẩn thì curator dùng bước 5 rồi mới gửi. Trước mắt: re-publish sau Phase parser + matcher Bach.

### 10. Gia phả Bach

Nguồn Gutenberg đã wrap sai cột (`8. … 9.` cùng dòng). Matcher `bach_genealogy` lúc parse: mỗi `\d+\. NAME, dddd` = một `list_item`; tách dù cùng physical line. Final Touch chỉ chỗ miss — đừng bắt curator xuống dòng từng người.

### 11. Kế thừa khi dịch (sau)

Hôm nay `sync-ref-chapters` copy plain `source_text`. Patch EN không đi theo VI.

Cần: dịch theo `block_id`, copy `type`/`hidden`, chỉ dịch `text` + `note.body` + caption. `set_text` lexical không copy. Không parse lại REF từ VI. Không re-detect synopsis/sidenote trên VI.

### 12. `~bold~` (không phải Markdown `~~`)

Gutenberg (Bach / Beethoven) dùng `~bold~`. Thêm span `strong`. Read render `<strong>`. Kiểm tra raw 3 pilot trước khi bật.

Contract: cập nhật `docs/ref-read-contract.md` khi Read cần hiểu `strong` / `hidden`. Hub có thể emit `strong` sớm; Read bỏ qua cho đến lockstep (span text vẫn hiện, chỉ chưa đậm).

### 13. Footnote + đoạn chủ

`notes[]` hiện chỉ `marker` / `body` / `anchor` ngắn. Thêm `host_block_id` + `host_text`. Card chú thích + “Giải thích thêm” = host + dump, ngôn ngữ sách.

---

## Thứ tự làm

### Phase 1 — Parser (Hub, mọi Gutenberg) — làm trước

Mục tiêu: Bach đọc được hơn mà **chưa cần** Final Touch.

1. False heading: speaker ALLCAPS; ALLCAPS+năm; `_italic_` không heading mặc định (Arnold/Bastiat title italic **vẫn** heading nếu đúng là title).
2. False blockquote: quoted fragment giữa prose; join quote wrap trước classify.
3. Span `strong` cho `~…~`.
4. Heading trùng `chapter.title` → `suppress_in_reader`.
5. Note payload: `host_block_id` + `host_text`.
6. Gắn `block_id` lúc parse — ổn định trong một `edition_hash`; identity = matcher `(chapter_id, prefix, type)`, không phải index.
7. Tests excerpt Bach: genealogy (parser chưa tách số — Phase 2), `ILLE.` / `DER SUPERINTEND.`, Wasserflüssen, `~Adlung~`. Arnold/Bastiat: italic title vẫn ra heading.

### Phase 2 — Matcher 3 cuốn (không phải CMS)

Chạy sau parse, trước HITL quotes / trước Final Touch. Code theo `work_id` (và family Gutenberg), không phải engine cấu hình.

| Matcher | Bach | Arnold / Bastiat |
|---------|------|------------------|
| `pg_sidenote` | aside + default hide | bật nếu raw có |
| `chapter_synopsis_emdash` | block đầu sau heading, nhiều `—` → synopsis | chỉ nếu cùng layout |
| `bach_genealogy` | vùng Hilgenfeldt → `list_item` | tắt |
| `pg_illustration` | map `[Illustration:]` (chưa cần file ảnh) | nếu HTML có hình |

Strip Gutenberg không nuốt `[Sidenote:]` trước matcher.

### Phase 3 — Final Touch UI (bước 5)

- Preview sát Read (heading, quote, footnote; figure sau).
- Ops: ẩn/hiện, merge, split, `set_type`. Không bắt sửa JSON.
- Patch theo `block_id`; re-parse → stale rõ ràng.
- `set_text` → `lexical: true`.
- Publish optional confirm.

### Phase 4 — Read + figures (song song Phase 3)

**Read:** ẩn heading trùng title; `strong` / `hidden` / `synopsis`; default ngôn ngữ explain = `book.language`; dropdown persist; explain(host+note).

**Hub:** ingest ảnh Bach từ zip Gutenberg vào `corpus/assets/` (gitignore file lớn); `notes[].figures[]` cho footnote 77. Không hotlink Gutenberg.

### Phase 5 — Dịch kế thừa

Segment theo `block_id`, không slice plain chapter. Copy `type`/`hidden`/spans; dịch `text` + note + caption.

---

## Tiêu chí xong (Bach)

- Không duplicate `CHAPTER N` trên Read.
- `ILLE.` / `DER SUPERINTEND.` cùng style thoại.
- `"An Wasserflüssen…"` nằm trong đoạn, không blockquote.
- Gia phả: mỗi số một dòng; không `9.` dính cuối 8; tên không phải heading.
- `[Sidenote: …]` không còn trong body.
- Khổ `—` đầu chương là synopsis.
- `~Name~` đậm.
- Footnote + Giải thích thêm: đúng đoạn chủ + dump; mặc định tiếng Anh.
- Re-parse không mất hide/type (hoặc báo stale).
- Ảnh nhạc: **không** chặn các mục trên.

Arnold/Bastiat: không regress italic essay titles thành paragraph.

---

## Quyết định chốt trước khi code

1. **`synopsis` / `figure` là type mới** (nên — TTS và dịch cần biết) hay `paragraph` + flag? Sprint 1 có thể emit `paragraph` + `role` nếu chưa muốn đụng contract; type chính thức khi Read lockstep.
2. **Sidenote:** ẩn hết, hay hiện sidenote italic (nhãn mục) và ẩn running header? **Chốt: ẩn default**, curator lật trong Final Touch.
3. **Ảnh:** `corpus/assets/` gitignored + URL Hub, không hotlink Gutenberg.
4. **Bước 5 bắt buộc trước Publish?** **Chốt: optional** cho đến khi UI ổn.

Khi implement: parser + matcher Bach trước; Final Touch là editor view, không phải rules engine; ảnh và rewrite dịch để sau.
