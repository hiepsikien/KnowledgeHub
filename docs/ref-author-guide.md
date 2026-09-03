# Hướng dẫn viết bản thảo

Bạn nộp **một file chữ** (`.txt`). Phần chữ của sách vẫn tiếng Việt. Một số dòng “nhãn” viết đúng như mẫu dưới đây — nhờ vậy sách hiện đủ chương, chú thích và hình khi lên thư viện.

Không nộp file Word, PDF, hay Google Docs. Từ Word: **File → Save As → Plain Text**, encoding **UTF-8**.

---

## Làm đúng 5 điều này

1. **Một sách = một file.**
2. **Hết đoạn thì để một dòng trống.** Đừng bấm Enter giữa câu.
3. **Tên chương đứng một mình một dòng**, có dòng trống phía trên và phía dưới.
4. Đầu sách có **mục lục**, và **mỗi chương trong mục lục phải xuất hiện lại** khi chương đó bắt đầu.
5. Dùng đúng các nhãn trong bảng dưới — đừng dịch chúng ra tiếng Việt.

| Việc | Viết đúng | Ví dụ |
|------|-----------|--------|
| Mục lục | `CONTENTS` | dòng riêng, không viết `Mục lục:` |
| Lời tựa | `PREFACE` | không viết `LỜI TỰA` |
| Chương | `CHAPTER I` rồi `CHAPTER II`… | không viết `CHƯƠNG I` |
| Tập / phần (nếu có) | `BOOK I` hoặc `PART I` | |
| Chú thích cuối chương | `FOOTNOTES:` | không viết `CHÚ THÍCH:` |
| Hình | `[Illustration: lời chú thích]` | không viết `[Hình: …]` |
| In nghiêng | `_chữ này_` | không dùng `*sao*` |
| In đậm | `~chữ này~` | không dùng **in đậm Word** |

---

## Khung một cuốn sách

Copy khung này, thay chữ của bạn:

```
TÊN SÁCH
Tên tác giả

CONTENTS

PREFACE
CHAPTER I.  Câu hỏi
CHAPTER II. Hai lối trả lời

PREFACE

Vài đoạn lời tựa. Hết đoạn thì để một dòng trống như thế này.

Đoạn tựa tiếp theo.

CHAPTER I
Câu hỏi

Đây là đoạn mở đầu chương. Câu sau vẫn thuộc đoạn này vì không có dòng trống ở giữa.

Đây là đoạn mới.

CHAPTER II
Hai lối trả lời

Đoạn đầu chương hai.
```

**Đúng:** tên chương trong mục lục trùng với khi chương bắt đầu (`CHAPTER I` một chỗ, `CHAPTER I` chỗ kia).

**Không đúng:** chỉ liệt kê chương ở mục lục, rồi trong sách không có dòng `CHAPTER I`.  
**Không đúng:** dính tiêu đề vào đoạn — `CHAPTER I Đây là câu đầu…`

---

## Mục lục

Đặt gần đầu sách, **trước** chương 1. Một dòng `CONTENTS`, rồi mỗi mục **một dòng**. Không ghi số trang.

```
CONTENTS

PREFACE
CHAPTER I.  Câu hỏi
CHAPTER II. Hai lối trả lời
CHAPTER III. Kết
```

Sách có nhiều tập:

```
CONTENTS

BOOK I
CHAPTER I.  Mở đầu
CHAPTER II. Trên đường
BOOK II
CHAPTER I.  Bắt đầu lại
```

Viết xong mục lục thì xuống dòng trống, rồi mới tới lời tựa hoặc chương 1. Đừng chen đoạn văn giữa các dòng mục lục.

Bài rất ngắn (một hai phần) có thể không cần mục lục. Sách từ ba chương trở lên thì nên có.

---

## Chương

Mỗi chương bắt đầu như sau — hai dòng, rồi mới tới đoạn văn:

```
CHAPTER I
Câu hỏi

Đoạn văn đầu tiên của chương.
```

Chương không có tên riêng:

```
CHAPTER II

Đoạn văn đầu tiên.
```

Lời tựa, phần phụ:

```
PREFACE

Lời tựa…

APPENDIX

Phần phụ lục…
```

Đánh số đều từ đầu đến cuối: `CHAPTER I`, `CHAPTER II`, `CHAPTER III` — hoặc `CHAPTER 1`, `CHAPTER 2`… Chọn **một** kiểu, dùng suốt sách.

---

## Đoạn văn

Trong file chữ, **Enter giữa câu = cắt đoạn**. Hãy gõ hết một đoạn, rồi mới Enter hai lần (một dòng trống) trước đoạn sau.

Đúng:

```
Câu đầu nối với câu sau trong cùng một đoạn. Bạn không cần bấm Enter cho đến khi hết ý.

Sang ý mới thì để một dòng trống, rồi viết đoạn này.
```

Không đúng:

```
Câu bị cắt giữa chừng vì
bấm Enter sớm.
```

Thơ: mỗi dòng thơ một lần Enter — xem mục thơ bên dưới.

---

## In nghiêng, in đậm, trích dẫn

File chữ không giữ được kiểu chữ Word. Đánh dấu bằng gạch dưới và dấu ngã:

```
Ông nói điều đó là _rất quan trọng_, không phải chuyện nhỏ.

Chữ cần nhấn: ~Quyết định~.

Bà đáp: "Biển không phải của riêng ai."
```

Dòng nghiêng ngắn trong đoạn thì được. Đừng bọc cả một câu dài trong `_…_` rồi để nó một mình một dòng — dễ bị hiểu là tiêu đề.

Đừng tách câu trích thành dòng riêng bắt đầu bằng dấu ngoặc kép.

---

## Chú thích

Trong bài, đặt số trong ngoặc vuông **sát chữ** cần chú:

```
…theo Grotius[1] và sau này Locke[2].
```

Hết chương, xuống dòng trống, viết đúng một dòng `FOOTNOTES:`, rồi từng chú thích:

```
Biển có thể trở thành tài sản riêng hay không[1] là câu hỏi mở đầu.

FOOTNOTES:

[1] Xem Grotius, Mare Liberum.
[2] Tên Latin của tác phẩm.
```

- Số trong bài phải có đủ ở cuối chương (`[1]` thì phải có `[1] …`).
- Sang chương mới, được đánh `[1]` lại từ đầu.
- Sau khối chú thích, chương kế phải bắt đầu bằng `CHAPTER …` (không nhảy thẳng vào đoạn văn của chương sau).
- Đừng viết `(1)` — đó là đánh số danh sách, không phải chú thích.

Có hình trong chú thích: để `[Illustration: …]` **trong dòng chú thích**, không thay số `[1]`.

```
FOOTNOTES:

[1] Bản đồ thời đó. [Illustration: Bản đồ biển Đông, thế kỷ XVII]
```

---

## Hình

Ảnh **không dán vào file chữ**. Làm hai việc:

**1. Trong sách**, chỗ cần hiện hình, một dòng riêng:

```
Đoạn dẫn vào tấm hình.

[Illustration: Bản đồ biển Đông, thế kỷ XVII]

Đoạn tiếp theo.
```

Luôn viết lời chú thích trong ngoặc. Đừng để `[Illustration]` trống.

**2. Nộp kèm** các file ảnh (`png` hoặc `jpg`), đặt tên theo thứ tự xuất hiện:

- `fig-01.png` — tấm thứ nhất  
- `fig-02-ban-do.png` — tấm thứ hai  

Kèm một dòng ghi chú khi gửi bài, ví dụ: `fig-01` = Bản đồ biển Đông.

Bìa sách gửi riêng, không ghi `[Illustration: bìa]` trong thân bài.

---

## Thơ

Mỗi dòng thơ = một dòng trong file. Hết khổ thì một dòng trống. Dòng thơ tiếng Việt nên kết bằng dấu phẩy hoặc chấm phẩy (không kết bằng chấm hết câu).

```
Trăm năm trong cõi người ta,
Chữ tài chữ mệnh khéo là ghét nhau,

Trải qua một cuộc bể dâu,
Những điều trông thấy mà đau đớn lòng,
```

Đừng thụt đầu dòng bằng nhiều khoảng trắng để “trông giống thơ”.

---

## Kịch (nếu viết kịch)

Mở đầu bằng danh sách nhân vật, rồi hồi / cảnh, rồi tên nhân vật một dòng, lời thoại dòng dưới:

```
Dramatis Personæ

HAMLET, Prince of Denmark.
GHOST.

ACT I

SCENE I

HAMLET.
To be, or not to be, that is the question.

[Aside]
A word in your ear.

Enter Ghost.
```

---

## Danh sách đánh số

Câu hỏi / ý liệt kê, không phải chú thích:

```
(1) Biển có thể trở thành tài sản riêng không.
(2) Việc đi lại trên biển có thể bị cấm không.
```

---

## Xem lại trước khi gửi

- [ ] File `.txt`, UTF-8, **một** file cho cả sách.
- [ ] Có `CONTENTS`; mỗi dòng mục lục trùng với `CHAPTER` / `PREFACE` trong sách.
- [ ] Mỗi chương bắt đầu `CHAPTER I`, `CHAPTER II`… một dòng riêng, không trộn với chữ `CHƯƠNG`.
- [ ] Đoạn văn cách nhau bằng một dòng trống; không Enter giữa câu.
- [ ] In nghiêng `_…_`, in đậm `~…~`.
- [ ] Mỗi `[1]` trong bài có dòng tương ứng dưới `FOOTNOTES:` ở **cùng chương**.
- [ ] Mỗi hình có dòng `[Illustration: …]` và file `fig-01`… nộp kèm.
- [ ] Không còn kiểu chữ Word, không còn `Mục lục:`, `CHƯƠNG`, `CHÚ THÍCH:`, `[Hình:]`.

---

## Bản mẫu đủ để copy

```
BIỂN MỞ
Tên tác giả

CONTENTS

PREFACE
CHAPTER I. Câu hỏi
CHAPTER II. Hai lối trả lời

PREFACE

Sách này viết cho người đọc phổ thông, không phải chuyên khảo.

CHAPTER I
Câu hỏi

Biển có thể trở thành tài sản riêng hay không[1] là câu hỏi mở đầu.

FOOTNOTES:

[1] Xem Grotius, Mare Liberum.

CHAPTER II
Hai lối trả lời

[Illustration: Bản đồ các luồng hàng hải Ấn Độ Dương]

Một lối trả lời đặt luật lệ lên trên lực.

Lối kia đặt tập quán lên trên luật lệ.

_Kết._
```

Gửi kèm `fig-01-ban-do.png` nếu dùng hình trong mẫu.
