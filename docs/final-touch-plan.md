# Kế hoạch: Final Touch + custom rules (pilot 3 cuốn)

Checklist từ lần đọc thử Bach (Abdy Williams) trên Read, cộng hai cuốn còn lại (`arnold--essays_in_criticism`, `bastiat--economic_sophisms`). Đây là kế hoạch kỹ thuật — chưa implement.

Nguyên tắc: **làm đúng bản gốc (EN) trên block graph ổn định**, rồi bản dịch (VI) kế thừa cấu trúc. Không vá bằng cách sửa chuỗi tiếng Anh cứng.

---

## 0. Hai lớp sửa — đừng trộn

| Lớp | Khi nào | Sống ở đâu | Kế thừa khi dịch? |
|-----|---------|------------|-------------------|
| **A. Parser / span / schema** | Lỗi lặp lại trên nhiều sách Gutenberg | `label_rules.py`, `inline_spans.py`, REF schema | Có — cùng rule chạy lại trên bản dịch nếu bản dịch giữ cấu trúc |
| **B. Custom rule theo sách** | Pattern chỉ cuốn này (sidenote, khổ mở chương `--`, gia phả Bach) | `work.read.edition.rules[]` — declarative, không hard-code English | Có nếu rule khớp *hình dạng* (regex/role), không phải literal EN |
| **C. Final Touch** | Việc mắt người thấy trên *view chương đã pass* | Patch trên `block_id` ổn định (ẩn/ghép/tách/đổi type) | Có nếu patch là structural; không nếu curator sửa *chữ* |

Hiện tại Chế bản dừng ở 4 bước: Phân đoạn → Nối dòng → Chú thích → Trích dẫn. Editor JSON block đã có (`block_patches`: đổi type/text, `merge_with_next`) nhưng giấu trong `<details>`, không đủ hide/split, không có `block_id`, và **không phải bước duyệt view**.

**Final Touch = bước 5.** Curator xem đúng layout sẽ lên Read, rồi chỉnh. Custom rules của cuốn chạy *trước* Final Touch (đề xuất + auto-apply an toàn), người duyệt/sửa trong bước 5.

```
raw → strip → macro → parse (wrap/fn/quotes)
                 → work rules (Bach sidenote, synopsis, genealogy, …)
                 → Final Touch (ẩn / ghép / tách / type)
                 → publish REF + notes[] + figures
                           ↓
              Read render  |  dịch: align block_id, dịch text, giữ type/hidden
```

---

## 1. Chẩn đoán từng mục (Bach trên Read)

### 1.1 Duplicate tên chapter (Read chrome + sách)

**Hiện tượng:** cùng một “CHAPTER III” hiện hai lần — sidebar/header Read lấy `chapters[].title`, body lại render heading đầu chương.

Hub publish cả hai:

- `chapters[].title` từ macro (`structure.sections[].title`, thường là `CHAPTER I`)
- `chapters[].blocks[0]` vẫn là `heading` cùng text

**Hướng xử lý (Hub + Read, nhỏ):**

1. Hub: đánh `role: "chapter_banner"` (hoặc `suppress_in_reader: true`) lên heading trùng `chapter.title`.
2. Read: không render heading đó khi đã hiện title chrome.
3. Không xóa text — TTS/dịch vẫn thấy.

Không cần Final Touch trừ khi title macro sai (sửa ở bước Phân đoạn).

### 1.2 Nhạc / hình Gutenberg (Footnote 77 + illustrations)

Plain `.txt` **không có nốt**. Gutenberg ghi rõ HTML mới có pictorial/musical illustrations. Trong txt:

- `[Illustration: …]` (nhà Eisenach, organ, facsimile of music, …)
- Ký tự nhạc (sharp/flat/natural) có thể rơi thành replacement character `￼` (mục “￼” trong checklist rất có thể là chỗ này, hoặc ảnh dán không lên)

Có thể lấy ảnh: **có**. Nguồn:

- `https://www.gutenberg.org/cache/epub/43650/pg43650-images.html`
- zip `43650-h.zip` / `images/`
- Internet Archive `bach00will` nếu HTML thiếu nét

**Kế hoạch:**

1. REF thêm block `figure` (`src`, `alt`, `caption`, optional `footnote_marker`).
2. Script ingest: map `[Illustration: …]` → file trong `corpus/assets/{work_id}/`.
3. Footnote có ví dụ nhạc: `notes[].figures[]` + `span.note` vẫn là text; Read hiện ảnh trong card chú thích.
4. Pilot: Bach trước. Arnold/Bastiat chỉ nếu HTML có hình.

License: PD Gutenberg — giữ attribution, không hotlink bền; copy vào Hub.

### 1.3 “Giải thích thêm” lúc EN / Đức / Ý

Đây là **Read** (LLM explain), không phải Hub parse. Bach trích tiếng Đức (`An Wasserflüssen Babylon`, `DER SUPERINTEND.`), Latin, Ý — model đoán sai ngôn ngữ câu.

**Read:**

- Default = `book.language` Hub đã gửi (`en` với 3 pilot).
- Dropdown ngôn ngữ giải thích; lần chọn sau thành default *per user* (và nhớ theo sách nếu muốn).
- Prompt: “sách ngôn ngữ X; đừng đổi sang ngôn ngữ của câu trích trừ khi user chọn.”

**Hub:** không sinh giải thích. Chỉ đảm bảo `language` trên payload và (mục 1.13) gửi *đoạn chủ* kèm footnote.

### 1.4 Giải thích lệch một paragraph (đoạn trên)

Hai nguyên nhân chồng:

1. **Sai block:** câu `"An Wasserflüssen Babylon";[12] …` bị tách thành blockquote/heading. Marker `[12]` nằm block “lạ”, tap/explain bám block sau.
2. **Read** map footnote → paragraph index sau khi reflow, off-by-one.

**Sửa:**

- Hub: mỗi note có `host_block_id` + `host_text` (đoạn chứa marker, không chỉ dump `[12] See …`).
- Parser: đừng tách cụm quote ngắn giữa câu thành block riêng (1.5–1.6).
- Read: explain lấy `host_text + note.body`, không lấy “paragraph đang highlight” nếu lệch.

### 1.5 Double quotes bị nhầm

Hai bug khác nhau trên ảnh:

**A. Quote giữa câu → blockquote** (ảnh *An Wasserflüssen Babylon*)

Trong `label_rules.py`: dòng bắt đầu `"` / `“`, dài &lt; 120, ≤16 từ → `verse_line` (conf 0.86). `merge_blocks.py` rồi đổi `verse_line` bắt đầu bằng quote thành `blockquote`. Đó là thanh xám + italic giữa hai đoạn văn.

HITL quotes đã có `short_blockquote` nhưng curator phải reject từng cái; parser không được tạo chúng.

**B. Ngoặc kép không khớp / thẳng vs cong**

`DQUOTE` bắt cặp `"…"` hoặc `“…”`. Dòng chỉ có mở `“` rồi `;` + `[12]` → span quote hỏng hoặc unclosed. HITL ghi `unclosed_quote` là *not_actionable*.

**Sửa parser (lớp A):**

- Không gán `verse_line` cho quoted fragment giữa prose (có `;` / `[n]` / tiếp tục lowercase ở dòng sau).
- Join quote wrap trước khi classify block.
- Span `quote` chỉ khi cặp đóng đủ; otherwise để nguyên glyph.

Final Touch: đổi type blockquote → paragraph khi rule còn sót.

### 1.6 Đoạn thành heading

Rule hiện tại (`reflow.py` + `label_rules.py`):

| Pattern | Hệ quả trên Bach |
|---------|------------------|
| ALL CAPS, ≥8 chữ cái, &lt;90 ký tự, &lt;2 dấu phẩy | `JOHANN NICOLAUS, 1653-1682.` và `DER SUPERINTEND.` → heading L2 |
| Cả dòng `_italic_` | `_Sons of Johann (No. 4)._` → heading L2 (thực ra là nhãn nhóm list) |
| `ILLE.` quá ngắn | *không* thành heading — đúng như ảnh: ILLE thường, DER SUPERINTEND to |

`is_hard_structural` cũng gọi `is_all_caps_heading` — genealogy/dialogue bị “cứng” như CHAPTER.

**Sửa lớp A (an toàn, mọi sách):**

- Cue thoại ngắn ALLCAPS + `.` (`ILLE.`, `DER SUPERINTEND.`) → `dialogue` / `speaker_cue`, không heading.
- ALLCAPS + năm `dddd-dddd` → `list_item` (gia phả / catalog), không heading.
- Cả dòng `_…_` không còn auto heading nếu không khớp CHAPTER/BOOK hoặc nằm giữa list.

**Lớp B/C:** Bach genealogy còn sót → Final Touch đổi type.

### 1.7 Khổ mở chương = summary nối bằng `--` / `—`

Đúng như Gutenberg: sau `CHAPTER III` là một dòng (hoặc wrap) kiểu *Bach’s salary—He borrows a cart…—His competition with Marchand.* Đó là synopsis in-book, không phải body.

**Custom rule Bach (và sách Master Musicians cùng layout):**

- Ngay sau heading chương L1, một (hoặc vài) dòng nối bằng `—` / `--`, không phải câu văn xuôi bình thường → `type: "synopsis"` (hoặc `heading` level 4 / `metadata` nếu chưa muốn type mới).
- Read: style nhỏ hơn, italic, không TTS như đoạn văn nếu `skip_tts`.

Không nhầm với em-dash *trong* đoạn văn thường (cần: vị trí = block đầu sau chapter banner + mật độ `—`).

### 1.8 `[Sidenote: …]`

Có đầy trong `43650.txt` (`[Sidenote: _The Founder of the Family_]`, `[Sidenote: Music and War]`, …). Parser hiện **không** nhận. Chúng thành prose/heading lộn.

Transcriber: sidenote không italic vốn là running header trang.

**Custom rule Bach:**

- Parse `[Sidenote: …]` → span `sidenote` hoặc block `aside`; default **ẩn trên Read** (`hidden: true`) vì trùng running header / đã có TOC.
- Curator Final Touch: hiện lại nếu sidenote mang thông tin (nhãn mục).
- Không để literal `[Sidenote: ` trong body.

Strip apparatus Gutenberg không được nuốt sidenote trước khi rule chạy.

### 1.9 Final Touch (view chương đã pass)

Đây là **sản phẩm** của checklist, không phải một bug.

**UI:** bước 5 trên đúng preview Reader (heading, quote, footnote, figure). Mỗi block: chọn, ẩn (soft), hiện, ghép với trước/sau, tách tại caret, đổi type.

**Patch model (quan trọng cho dịch):**

```json
{
  "block_id": "ch-003:b-014",
  "op": "hide" | "show" | "merge_next" | "split" | "set_type" | "set_text",
  "type": "list_item",
  "split_offset": 40
}
```

- **Ẩn** mặc định (`hidden: true`), không xóa — dữ liệu còn, bản dịch vẫn align.
- `set_text` đánh dấu `lexical: true` → **không** auto-apply sang VI.
- `block_id` gắn lúc parse (hash ổn định theo vị trí + prefix text), persist qua re-parse nếu matcher còn khớp; mismatch → Final Touch “stale patch”.

Mở rộng `overrides.apply_block_patches` (hiện thiếu hide/split). JSON editor giữ cho debug.

### 1.10 Gia phả Bach không xuống dòng

Nguồn Gutenberg *đã wrap sai cột*:

```
7. JOHANN CHRISTIAN, 1640-1682. 8. JOHANN AEGIDIUS, 1645-1717. 9.
JOHANN NICOLAUS, 1653-1682.
```

Parser join hard-wrap → `9.` dính cuối dòng 8; dòng `JOHANN NICOLAUS…` thành heading (1.6).

**Custom rule Bach “genealogy”:**

- Trong vùng giữa `THE BACH FAMILY` / `(From Hilgenfeldt.)` và hết numbered list: mỗi `\d+\.\s+[A-Z].*?dddd` = một `list_item`.
- Tách `8. … 9.` dù cùng physical line.
- Nhãn `_Sons of …_` = `list_caption` (italic), không heading.

Rule này **nên chạy lúc parse** (rẻ, deterministic). Final Touch chỉ sửa chỗ rule miss.

### 1.11 Ký tự `￼`

Thường là OBJECT REPLACEMENT (ảnh/nốt không có trong txt). Xử lý cùng 1.2: ingest figure; nếu còn `￼` trong text → HITL/Final Touch ẩn hoặc thay caption `[Music example]`.

### 1.12 Kế thừa khi dịch

Hôm nay `sync-ref-chapters` chỉ copy **plain source_text** theo macro, rồi dịch lại từ đầu. Patch Final Touch trên EN **không** đi theo VI.

**Mô hình cần:**

1. Edition EN canonical = blocks có `block_id`.
2. Dịch **theo block** (cùng id, cùng type/hidden/spans offsets sau khi map).
3. Work rules chạy lại trên VI *nếu* pattern không phụ thuộc tiếng (sidenote đã bị strip thì không còn; synopsis `—` có thể còn nếu dịch giữ cấu trúc — thường **không**: synopsis phải dịch như một block `synopsis`, không re-detect bằng regex EN).
4. Do đó: **rule phát hiện trên EN → gắn type/hidden trên block_id → dịch viên chỉ dịch `text`.**

Đừng dịch rồi parse REF lại từ VI (sẽ mất sidenote/genealogy/hide).

### 1.13 `~bold~` (user ghi `~~keyword`)

Transcriber Bach: *Text enclosed by tilde characters is in bold face (`~bold~`).* Beethoven fixtures cùng convention. REF/1 mới có `em` (`_…_`), **không** có `strong`.

**Lớp A:** span `strong` cho `~…~` (và `~~…~~` nếu cuốn nào dùng). Read render `<strong>`. TTS không đổi.

Pilot 3 cuốn: Bach chắc có (thư mục/bibliography). Arnold/Bastiat kiểm tra raw.

### 1.14 Footnote: cả đoạn chủ, không chỉ dump

`notes[]` hiện: `marker`, `body` (FOOTNOTES dump), `anchor` (cụm ngắn gần marker). Read explain nếu chỉ gửi `body` thì thiếu ngữ cảnh; nếu gửi nhầm paragraph thì lệch (1.4).

**Hub publish thêm:**

```json
{
  "marker": "[12]",
  "body": "…dump…",
  "anchor": "An Wasserflüssen Babylon",
  "host_block_id": "ch-002:b-088",
  "host_text": "…Reinken… two chorales … An Wasserflüssen Babylon;[12] and a toccata in G."
}
```

Read: card chú thích + “Giải thích thêm” = host_text + body, ngôn ngữ sách (1.3).

---

## 2. Việc làm theo thứ tự (không ước lịch)

### Phase 1 — Parser/span (lớp A, mọi Gutenberg)

Sửa xong thì nhiều ảnh Bach tự hết, không cần click Final Touch.

1. **False heading:** speaker cue ALLCAPS; ALLCAPS+năm; `_italic_` không còn heading mặc định.
2. **False blockquote/verse:** quoted fragment giữa prose; join trước classify.
3. Span **`strong`** (`~bold~`).
4. **Chapter banner:** heading trùng `chapter.title` → `suppress_in_reader`.
5. Note payload: `host_block_id` + `host_text`.
6. Tests: excerpt Bach (genealogy, ILLE/SUPERINTEND, Wasserflüssen, sidenote, synopsis, `~Adlung~`).

Contract: cập nhật `docs/ref-read-contract.md` — Read phải hiểu `strong`, `hidden`, `figure`, `synopsis` (hoặc tạm render synopsis như paragraph italic).

### Phase 2 — Work rules (lớp B)

Schema `work.read.edition.rules` (JSON trên catalog hoặc `corpus/read-editions/{id}/rules.json`):

| id | Bach | Hành động |
|----|------|-----------|
| `pg_sidenote` | `[Sidenote: …]` | aside + default hide |
| `chapter_synopsis_emdash` | block đầu sau chapter heading, nhiều `—` | type `synopsis` |
| `bach_genealogy` | vùng Hilgenfeldt | split numbered names → `list_item` |
| `pg_illustration` | `[Illustration: …]` | `figure` + asset nếu có |

Rule = matcher (regex/region) + ops giống Final Touch. Chạy sau parse, trước HITL quotes hoặc sau quotes / trước Final Touch. Curator thấy “rule đã áp dụng” và có thể tắt từng rule.

Arnold/Bastiat: bật `pg_sidenote` / `strong` nếu raw có; không bật genealogy.

### Phase 3 — Final Touch UI (lớp C)

1. Bước 5 Chế bản: preview = Read (càng gần càng tốt).
2. Ops: ẩn/hiện, merge, split, set_type. Không bắt sửa JSON.
3. `block_id` + stale detection khi re-parse.
4. Genealogy/Bach còn lệch → sửa tay ở đây (đúng như user nói).

Publish chỉ khi bước 5 confirmed *hoặc* explicit “không cần Final Touch” cho sách sạch.

### Phase 4 — Figures + Read explain

1. Ingest ảnh Bach từ Gutenberg HTML/zip.
2. Read: `figure`; footnote card có ảnh.
3. Read: default ngôn ngữ = `book.language`; dropdown persist; explain(host+note).

Có thể song song Phase 3 (repo Read).

### Phase 5 — Dịch kế thừa

1. Dịch theo `block_id`, không parse lại VI từ đầu.
2. Copy type/hidden/spans; chỉ dịch `text` + `note.body` + caption.
3. `set_text` lexical không copy.
4. Sync REF chapters chuyển từ plain slice → block-aligned segments.

---

## 3. Schema REF cần thêm (tối thiểu)

| Thêm | Dùng cho |
|------|----------|
| `block_id` | patch + dịch |
| `hidden` | sidenote, ￼, banner |
| `type: synopsis` | khổ `--` |
| `type: figure` | nhạc/ảnh |
| `type: list_item` (dùng thật, không “future”) | gia phả |
| span `strong` | `~bold~` |
| span `sidenote` (nếu không tách block) | fallback |
| `notes[].host_text` / `host_block_id` | explain |

Read contract: những field này **phải** honor, không còn “best-effort”, nếu không Final Touch trên Hub không hiện trên app.

---

## 4. Phân repo

| Việc | Repo |
|------|------|
| Parser, work rules, Final Touch CMS, notes host, figures ingest, dịch block-align | **KnowledgeHub** |
| Ẩn heading trùng title, render strong/figure/synopsis/hidden, ngôn ngữ explain, card footnote+host | **Read** |

Pilot lock: không publish lại 3 cuốn cho đến khi Phase 1+2 xong trên Bach (ít nhất 1.5, 1.6, 1.8, 1.10, 1.13). Phase 3 có thể theo sau nếu rule đã sạch view.

---

## 5. Tiêu chí xong (Bach Ch. I genealogy + Ch. II citation + một chương có synopsis)

- Không duplicate “CHAPTER N” trên Read.
- `ILLE.` / `DER SUPERINTEND.` cùng style thoại; không heading.
- `"An Wasserflüssen…"` nằm trong đoạn văn, không blockquote.
- Gia phả: mỗi số một dòng; không `9.` dính cuối 8; tên không phải heading.
- `[Sidenote: …]` không còn trong body (ẩn hoặc aside).
- Khổ `—` đầu chương là synopsis, không paragraph thường.
- `~Name~` đậm.
- Footnote tap + Giải thích thêm: đúng đoạn chủ + dump; mặc định tiếng Anh.
- Có ít nhất facsimile/music từ HTML Gutenberg gắn đúng chỗ (hoặc footnote 77 nếu ảnh map được).
- Re-parse không mất hide/type đã Final Touch (hoặc báo stale rõ).

---

## 6. Quyết định cần chốt khi implement (không chặn kế hoạch)

1. `synopsis` / `figure` là type mới hay reuse `paragraph` + flag? (Nên type mới — TTS và dịch cần biết.)
2. Sidenote default ẩn hết, hay hiện sidenote italic (nhãn mục)? Đề xuất: ẩn running-header, hiện nếu `_italic_` và không trùng heading gần đó — vẫn cho curator lật trong Final Touch.
3. Ảnh: copy vào repo git vs object storage? Pilot: `corpus/assets/` gitignored lớn, publish URL qua Hub.
4. Final Touch bắt buộc trước Publish, hay optional? User: *“cho view mỗi chương như theo đã pass”* → **bắt buộc confirm view**, không nhất thiết phải có patch.
