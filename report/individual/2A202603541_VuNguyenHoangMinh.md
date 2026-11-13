# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:
  - Giáo trình *Introduction to Python Programming* (OpenStax, Rice University, 2024), <https://openstax.org/details/books/introduction-python-programming>. Giấy phép **CC BY-NC-SA 4.0**, được dùng cho bài học phi thương mại; dòng ghi nguồn "Access for free at openstax.org" có sẵn trên mọi trang.
  - PDF gốc có 397 trang; corpus dùng **chương 4–6** (Decisions, Loops, Functions), tức trang PDF 95–174.
  - Quy tắc tính trang: số trang PDF bắt đầu từ 1; chỉ tính trang có ≥ 200 ký tự sau chuẩn hóa. Bị loại: trang 124, 146, 174 (chỉ có header/footer). Kết quả: **77 trang, 86.765 ký tự** (Decisions 29, Loops 21, Functions 27). Chi tiết từng trang: `data/manifest.json`, `starter/results/ingest_log.json`.
- Chuẩn hóa, lỗi và giới hạn:
  - Đọc lớp text bằng `pypdf` 6.21.4 (không cần OCR). `normalize_text`: Unicode NFKC, đổi `\r\n`/`\r` thành `\n`, gộp khoảng trắng trong từng dòng, giữ xuống dòng và ngắt đoạn (tối đa `\n\n`). Có 15 test case (`scripts/try_normalize.py`, 15/15 pass).
  - Lỗi: 0 trang trích xuất lỗi; 2 trang không có text (bìa, ngoài phạm vi).
  - Giới hạn: header/footer vẫn nằm trong text; bảng bị dồn dòng (ví dụ bảng chân trị); thụt lề của code bị mất; câu có thể bị ngắt qua hai trang (trang 140–141) và chunk không nối qua trang; chương trình và video tương tác trong sách không có trong PDF.
- Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:
  - OpenAI `text-embedding-3-small`, **1536 chiều**, SDK `openai` 3.50.0. Query và document được embed cùng một cách (model không cần prefix). Nếu API lỗi thì báo lỗi, không fallback sang vector giả.
  - PostgreSQL 16.16 + **pgvector 0.8.7** (Docker `pgvector/pgvector:0.8.7-pg16`), `psycopg` 3.3.8, Python 3.13.17. Metric **cosine** (`<=>`), **exact search** (không dùng index ANN, để kết quả có filter luôn đủ k bản ghi).
  - Lệnh chạy (trong `starter/`): `python -m src.run --split dev`, rồi `python -m src.run --split test`.
  - Chi phí: ≈ 49.800 tokens ≈ **$0,001 mỗi lần chạy** (đã chạy 2 lần).
- Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:
  - Bắt buộc: `document_id` (`openstax-intro-python`), `source` (đường dẫn PDF), `page` (số trang PDF); `chunk_id` ổn định có dạng `<document>:p<page>:<chunker>:<stt>`.
  - Trường lọc: **`chapter`** (text) và `chapter_number` (int), lấy từ **bookmark cấp 1 của PDF** (`Chapter 5 Loops` → `Loops`, 5) và đã đối chiếu với header/footer in trên trang. Lý do chọn: corpus chỉ có một cuốn sách, một năm, nên `year`/`version` không phân biệt được gì; chương là phạm vi tự nhiên mà người học hay nêu khi hỏi ("trong chương Loops…").

## Cấu hình và benchmark
- A / B / C (tham số cụ thể, khác biệt duy nhất B–C):
  - A: `fixed_size(size=500, overlap=50)`, không filter.
  - B: `by_paragraph(max_size=500)` (ranh giới hết câu/heading, đoạn quá dài cắt theo câu), không filter.
  - C: cùng chunk và vector với B; khác duy nhất là filter `chapter` khi câu hỏi có `filter`.
  - Chung cho cả ba: chương 4–6 (77 trang), `text-embedding-3-small` (1536 chiều), pgvector 0.8.7, exact cosine, top-3. Chi tiết: `artifacts/experiment_log.csv`.
  - **Cấu hình chốt ngày 2026-11-13, sau khi chạy dev và trước khi chạy test. Không chỉnh tham số sau khi xem dev.** Điểm yếu đã thấy trên dev (chunk B nhỏ, trung bình 242 so với 420 ký tự của A) được giữ nguyên và ghi là hạn chế, không sửa để tránh tối ưu theo dev.
- ≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence:
  - `benchmark/questions.json`: **20 câu**, tiếng Anh (cùng ngôn ngữ với sách). Mỗi câu có `expected_answer`, `gold_source_id`, `gold_page` (dạng list, q13 có 2 trang hợp lệ), `evidence_quote`, `filter`.
  - Chia **15 dev** (q01–q15: chương 4, 5 và mục 6.1) / **5 test** (q16–q20: mục 6.3–6.6). Hai tập không dùng chung trang nào; chia xong trước khi chạy retrieval.
  - Loại câu: direct 5 · paraphrase 5 · condition 6 · **filter 4** (q09 Decisions, q10 Loops, q15 Functions thuộc dev; **q20 Functions thuộc test**). Câu có filter nêu phạm vi ngay trong câu hỏi ("In the Functions chapter, …").
  - Kiểm chứng evidence tự động trên text đã chuẩn hóa (bỏ qua khác biệt khoảng trắng): **20/20** câu trích có mặt trên mọi trang gold và không có trên trang nào khác trong 95–174; trang gold của câu có filter đúng là thuộc chương đã ghi. q14 được chủ động chọn ở trang 143, vì cùng câu đó ở mục 5.5 bị cắt qua trang 140–141.
  - Nguy cơ: cả 5 câu test đều thuộc chương Functions nên test chưa đại diện cho toàn corpus; tập test chỉ có 1 câu có filter.
- Tiêu chí chọn chiến lược đã chốt trước khi xem test (ghi ngày 2026-11-13, trước khi chạy `--split test`):
  1. Chiến lược được **chọn trên dev**, theo thứ tự ưu tiên: (a) Evidence Hit@3 dev cao hơn; (b) nếu bằng nhau, Hit@1 dev cao hơn; (c) nếu vẫn bằng, chọn chiến lược đơn giản hơn / ít chunk và token hơn.
  2. Chênh lệch ≤ 1 câu trên 15 câu dev được ghi là **không phân biệt được** về mặt thống kê; vẫn áp dụng thứ tự trên để có một lựa chọn, nhưng kết luận phải nói rõ điều này.
  3. Test (5 câu) chỉ dùng để **báo cáo** chiến lược đã chọn và so sánh, **không dùng để đổi lựa chọn**. Coherence, metadata và grounding chấm thủ công sau đó được báo cáo cạnh Hit, không dùng để chọn lại.
  4. Áp dụng lên kết quả dev (A 11/15, B 10/15, C 10/15 Hit@3; Hit@1 đều 6/15): **chọn A**. Chênh lệch A–B chỉ 1 câu nên ghi là không phân biệt được; B–C bằng nhau trên dev.

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 6/15 | 11/15 | 224 | embed 5,19 s | 25.894 tokens ≈ $0,00052 |
| B | dev | 6/15 | 10/15 | 357 | embed 2,36 s | 23.705 tokens ≈ $0,00047 |
| C | dev | 6/15 | 10/15 | 357 (dùng lại của B) | 0 s (dùng lại vector B) | 0 |
| A | test | 1/5 | 2/5 | 224 | embed 2,75 s | 25.894 tokens ≈ $0,00052 |
| B | test | 4/5 | 4/5 | 357 | embed 2,97 s | 23.705 tokens ≈ $0,00047 |
| C | test | 4/5 | 4/5 | 357 (dùng lại của B) | 0 s (dùng lại vector B) | 0 |

> **Ghi chú**
>
> - **Thời gian** — thời gian gọi embedding API lúc ingest. Mỗi lần chạy (`--split dev`, `--split test`) đều ingest lại, nên có hai lần đo; chênh lệch là do độ trễ mạng. Chunking không đáng kể (< 0,01 s cho 77 trang).
> - **Chi phí** — ước tính theo giá $0,02 / 1M tokens của `text-embedding-3-small` lúc làm bài. Embedding câu hỏi tốn thêm 254 tokens (dev) và 86 tokens (test).
>   Tổng mỗi lần chạy ≈ 49.700–49.900 tokens ≈ **$0,001** (`results/metrics_dev.json`, `results/metrics_test.json`).
> - **Mức trần do chunking** — số câu có evidence nằm trọn trong một chunk (trên cả 20 câu):
>   A **18/20** (cắt q16, q20) · B **19/20** (cắt q05) — `results/chunk_stats.json`.
> - **Nạp lại không nhân đôi** — sau mỗi lần chạy, số dòng trong pgvector bằng đúng số chunk: A 224 · B 357 · C 357.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1,0 (n=10; 0: 0 · 1: 10 · 2: 0) | 15/15 | N/A (không áp dụng filter) | 0: 1 · 1: 2 · 2: 2 — 1,2 |
| B | 1,6 (n=10; 0: 0 · 1: 4 · 2: 6) | 15/15 | N/A (không áp dụng filter) | 0: 1 · 1: 0 · 2: 4 — 1,6 |
| C | 1,6 (cùng chunk với B) | 15/15 | 1/1 (q20, `chapter = Functions`) | 0: 1 · 1: 0 · 2: 4 — 1,6 |

> **Ghi chú**
>
> - **Phạm vi đo** — metadata và grounding đo trên 5 câu test × top-3, tức 15 bản ghi mỗi chiến lược.
> - **Metadata** — không có lỗi: `source`, `page`, `chapter` đều đúng ở cả 45 bản ghi.
> - **Filter** — tập test chỉ có 1 câu có filter (q20). A và B không áp dụng filter, nhưng top-3 của chúng cho q20 tình cờ đều thuộc chương Functions, nên filter của C không làm thay đổi kết quả.
> - **Coherence của C** — không chấm riêng, vì C dùng đúng các chunk của B.

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:
- Trace top-3 đầy đủ (câu hỏi, chunk ID, text, score, metadata, nhãn hit): `starter/results/traces_dev.jsonl`, `starter/results/traces_test.jsonl`.
- Chỉ số tổng hợp: `starter/results/metrics_dev.json`, `starter/results/metrics_test.json`, `starter/results/manual/summary.json`.
- Nhãn thủ công kèm lý do: `starter/results/manual/coherence_labels.csv`, `metadata_labels.csv`, `grounding_labels.csv`. Tạo bảng bằng `python scripts/label_sheets.py make`, tổng hợp bằng `python scripts/label_sheets.py summarize`.
- Cách chọn mẫu coherence (cố định trước khi chấm): 10 trang đầu của corpus (trang 95–104); ở mỗi trang lấy dòng đầu tiên bắt đầu từ giữa trang trở đi (dài ≥ 20 ký tự), rồi chấm chunk chứa dòng đó ở A và ở B.
- Grounding và metadata: toàn bộ 5 câu test × top-3 của A, B, C.
- Metadata được kiểm tra bán tự động: text của chunk phải có trên đúng trang PDF (đọc text thô bằng pypdf, bỏ qua khoảng trắng); chương phải khớp header/footer in trên trang (ví dụ `6 • Functions`, `6.3 • Variable scope`), không dùng bookmark.
- Người chấm: **Vũ Nguyễn Hoàng Minh** (tác giả), theo thang 0–2 của GUIDE.md, mỗi nhãn có lý do. Nguy cơ thiên lệch: chỉ có một người chấm, cũng là tác giả, và nhãn được chấm sau khi đã biết kết quả Hit và giả thuyết "B giữ ý tốt hơn A".

## Phân tích và kết luận
- So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:
  - **A–B (chỉ đổi cách chunk).** Hai tập cho kết luận ngược nhau. Dev: A nhỉnh hơn (Hit@3 11/15 so với 10/15; Hit@1 bằng nhau 6/15). Test: B tốt hơn rõ (Hit@3 4/5 so với 2/5; Hit@1 4/5 so với 1/5). Chấm thủ công nghiêng về B: coherence 1,6 so với 1,0, grounding 1,6 so với 1,2. A thường cắt giữa chữ và trộn 2–3 chủ đề trong một chunk; B giữ trọn đoạn định nghĩa nhưng tạo nhiều chunk nhỏ (trung bình 242 ký tự so với 420 của A, 51 chunk dưới 100 ký tự).
  - **B–C (chỉ thêm filter `chapter`).** Giống hệt nhau trên cả dev lẫn test. Với 4 câu có filter (q09, q10, q15, q20), top-3 không lọc của B vốn đã nằm đúng chương, nên filter không loại bỏ được chunk nhiễu nào. Ba chương chọn khác nhau rõ về chủ đề, nên với corpus này filter theo chương không thêm giá trị cho Hit.
  - **Ví dụ sai 1: q16 (test), cấu hình A, trang gold 156.** Evidence "A local variable cannot be accessed outside of the function… no longer exist." bị cửa sổ 500 ký tự cắt đôi: chunk `p156:fixed500o50:001` (hạng 2) bắt đầu bằng "executing, the function's local variables no longer exist.", nên không chunk nào chứa trọn câu. Đây là lỗi do chunking, đã dự báo trước khi search (mức trần của A: q16, q20). B lấy được trọn mục "Local scope" ở hạng 1 (`p156:para500:001`).
  - **Ví dụ sai 2: q05 (dev), cấu hình B, trang gold 109.** Đoạn "Associativity" dài ~560 ký tự, vượt `max_size=500`, nên bị cắt theo câu đúng vào giữa evidence 2 câu. Top-1 là chunk một câu "Ex: 2 ** 3 ** 4 is evaluated as 2 ** (3**4)." (score 0,724): đúng chủ đề, nhưng không có câu "Exponentiation is… right associative" nên bị tính trượt. A lấy được cả hai câu ở hạng 1.
  - **Ví dụ sai 3 (cả ba cấu hình): q20 (test), trang gold 170.** Chunk duy nhất được lấy từ trang 170 ở B/C là chunk chỉ có tiêu đề checkpoint/video ("Using default parameter values; ch 6, video 14…"), còn chunk chứa ghi chú "mutable objects… should not be used as default values" không vào top-3. Cùng loại lỗi với q07, q08, q11 trên dev: retrieval chọn đúng trang nhưng sai chunk (template, bảng, link video thay cho câu định nghĩa).
- Chiến lược chọn, đánh đổi, điều kiện áp dụng:
  - Theo tiêu chí đã chốt trước khi chạy test, **chiến lược được chọn là A** (dev Hit@3 11/15 > 10/15). Mình giữ nguyên lựa chọn này và không đổi sau khi thấy test. Tuy nhiên chênh lệch trên dev chỉ 1 câu (đã ghi trước là không phân biệt được), trong khi test và cả hai chỉ số chấm thủ công đều nghiêng về B. **Kết luận trung thực: dữ liệu hiện có chưa đủ để khẳng định A hay B tốt hơn với corpus này.** Nếu được chọn lại trên một tập dev mới, B (cắt theo ranh giới câu/heading) là ứng viên hợp lý hơn, vì nó ít cắt đôi evidence và chunk tự đọc hiểu được.
  - Đánh đổi: A có ít chunk hơn (224 so với 357) và chunk đủ dài để giữ các ý gồm nhiều câu, nhưng cắt giữa chữ và trộn chủ đề. B tập trung hơn và dễ đọc hơn, nhưng có chunk vụn (chỉ có footer hoặc link) và có thể tách một ý dài khi vượt `max_size`. Kích thước chunk khác nhau giữa A và B là một **biến nhiễu**: so sánh A–B không chỉ đo riêng cách cắt.
  - Điều kiện áp dụng: kết quả chỉ đúng cho chương 4–6 của sách này, câu hỏi tiếng Anh, `text-embedding-3-small`, top-3. Heuristic heading của B được viết riêng cho bố cục OpenStax. Filter theo chương chỉ đáng dùng khi các phạm vi có nội dung chồng lấn, điều không xảy ra ở corpus này.
- Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:
  - **Mẫu nhỏ:** 15 dev / 5 test; một câu thay đổi 6,7 điểm % trên dev và 20 điểm % trên test. Không có khoảng tin cậy. Test chỉ thuộc chương Functions và chỉ có 1 câu có filter.
  - **Dữ liệu:** một nguồn duy nhất; header/footer và các khối CHECKPOINT/TRY IT gây nhiễu (nhiều chunk chỉ là link video); bảng và thụt lề code bị mất; chunk không nối qua trang.
  - **Chỉ số tự động:** Hit chỉ tính khi chunk chứa **trọn** `evidence_quote`, nên nghiêm hơn mức người đọc cần (q05/B và q16/A có chunk đúng chủ đề nhưng vẫn bị tính trượt).
  - **Nhãn thủ công:** chỉ có một người chấm, không đo độ đồng thuận giữa người chấm; 10 vị trí coherence đều nằm ở chương 4 (trang 95–104).
  - **Thời gian/chi phí:** đo một lần cho mỗi lần chạy, phụ thuộc độ trễ mạng; chi phí là ước tính theo bảng giá lúc làm bài, chưa đối chiếu với hóa đơn.
  - **Sử dụng AI:** dùng Claude Code để hỗ trợ viết code pipeline, soạn nháp câu hỏi benchmark và đề xuất nhãn chấm ban đầu; tác giả xem lại và chịu trách nhiệm kết quả cuối cùng. Cách kiểm tra: test `normalize_text` (15/15), kiểm chứng evidence tự động (20/20), kiểm tra chạy lại không nhân đôi, kiểm tra metadata độc lập với pipeline, đọc trace của các câu trượt.
- Nếu làm lại hoặc mở rộng, cải tiến gì?
  - Bỏ header/footer và tách riêng các khối CHECKPOINT/TRY IT/video trước khi chunk; cho phép chunk nối qua trang.
  - Tách biến kích thước khỏi cách cắt: thêm cấu hình A' = `fixed_size(250, 25)` có cùng độ dài trung bình với B, hoặc B' = `by_paragraph(800)`.
  - Trích `section` (ví dụ 6.3) từ footer làm trường filter chi tiết hơn chương; viết thêm câu hỏi giữa các chương có chủ đề gần nhau để filter thật sự được kiểm tra.
  - Mở rộng benchmark (≥ 50 câu, test trải đều các chương), báo cáo kèm khoảng tin cậy; thêm người chấm thứ hai để đo độ đồng thuận.
  - Thử hybrid retrieval (BM25 + dense) cho các câu hỏi chứa từ khóa như `elif`, `global`, `range()`.
