# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:**
  - Corpus là *Introduction to Python Programming* (OpenStax, Rice University; Udayan Das, Aubrey Lawson, Chris Mayfield, Narges Norouzi), chương 4 *Decisions*, 5 *Loops* và 6 *Functions*, tức PDF trang 95–174.
  - Giấy phép **CC BY-NC-SA 4.0**, đã đối chiếu với trang bản quyền (PDF trang 4). Lab dùng phi thương mại và giữ ghi nguồn; PDF gốc không commit, cách tải lại có trong [manifest](../../data/manifest.json).
  - Một trang được tính khi, sau khi bỏ header/footer và phần trang trí ở trang mở chương rồi chuẩn hóa, còn **≥ 300 ký tự**. Số trang là số trang PDF vật lý (1-based), lớn hơn số in trên sách 10 đơn vị.
  - Kết quả: **76 trang được tính** (chương 4: 29, chương 5: 21, chương 6: 26), tổng 84.592 ký tự. Có 4 trang bị loại: p124 và p174 còn 0 ký tự, p146 còn 112, p173 còn 261. Lý do từng trang ghi trong [ingest_log.csv](../../starter/results/ingest_log.csv).
- **Chuẩn hóa, lỗi và giới hạn:**
  - `pypdf` đọc từng trang. Trang rỗng hoặc lỗi được ghi vào log và không đưa vào corpus.
  - Bỏ các dòng header/footer lặp lại bằng regex: "Access for free at openstax.org", số trang kèm tên chương/mục.
  - Chuẩn hóa NFKC, bỏ ký tự điều khiển, gộp khoảng trắng nhưng giữ thụt lề đầu dòng của code.
  - Nối lại dòng sau gạch nối cuối dòng nhưng **giữ dấu `-`**: cả 12/12 trường hợp trong các trang được tính đều là URL bị xuống dòng (ví dụ `.../4-2-if-else-statements`), không có từ văn xuôi nào bị ngắt. Bỏ dấu gạch nối theo kiểu thông thường sẽ làm hỏng URL.
  - Giới hạn còn lại: các nhãn hộp như "TRY IT", chú thích ảnh ("Figure 4.1 credit…") và đáp án trắc nghiệm vẫn nằm trong text. Corpus là PDF số nên không cần OCR.
- **Embedding, vector store, metric, lệnh chạy và chi phí:**
  - Embedding: OpenAI `text-embedding-3-small`, 1536 chiều (SDK `openai==3.50.0`), gửi theo lô 100, thử lại khi gặp lỗi tạm thời. Thiếu key hoặc API lỗi thì dừng hẳn, không có vector giả.
  - Vector store: PostgreSQL 16.16 + pgvector 0.8.7 (image `pgvector/pgvector:0.8.7-pg16`), `psycopg 3.3.8`, `pypdf 6.21.4`, Python 3.14.4.
  - Metric: cosine distance (`<=>`), tìm kiếm chính xác, không dùng index ANN; score = 1 − distance.
  - Lệnh chạy (từ `starter/`): `python scripts/build_manifest.py`, rồi `python scripts/verify_benchmark.py`, rồi `python -m src.run`, rồi `python -m src.run --reingest-check`.
  - Chi phí: 47.997 token cho tài liệu cộng 297 token cho câu hỏi, khoảng **$0,00097**. Chi tiết trong [embedding_usage.csv](../../starter/results/embedding_usage.csv).
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:**
  - Mỗi chunk có `document_id`, `source` (đường dẫn PDF), `page`, `chunk_id` ổn định (`openstax-intro-python:p{page}:{fixed|paragraph}:{idx}`), `char_start`/`char_end` (vị trí chính xác trong text trang) và `content_hash` (sha256).
  - Trường lọc là **`chapter`** (int: 4, 5, 6), cùng với `chapter_title` và `sections`. Giá trị lấy từ **bookmark (outline) của PDF**, không suy đoán.
  - Lý do chọn `chapter`: ba chương dùng lại nhiều từ khóa giống nhau ("else", "nesting", "Boolean", "PEP 8"). Người học thường biết mình đang ở chương nào, nên `chapter` là phạm vi tự nhiên mà người dùng cung cấp trước khi hỏi.

## Cấu hình và benchmark
- **A / B / C (tham số cụ thể, khác biệt duy nhất B–C):**
  - **A:** `fixed_size(size=500, overlap=50)`, cửa sổ ký tự cắt ở khoảng trắng gần nhất. Tạo ra 220 chunk.
  - **B:** `by_paragraph(max_size=1000)`, gom các khối đoạn liên tiếp; khối dài hơn 1000 ký tự thì cắt theo câu. Tạo ra 131 chunk.
    - `pypdf` không xuất dòng trống giữa các đoạn (0 lần `\n\n` trên 76 trang), nên ranh giới đoạn được suy từ độ rộng dòng.
    - Dòng văn xuôi bị PDF ngắt ở khoảng 100–126 ký tự, còn tiêu đề, code và dòng cuối đoạn ngắn hơn. Vì vậy dòng ≥ 90 ký tự được coi là đoạn còn tiếp, dòng ngắn hơn là hết khối.
  - **C:** chunk và vector giống hệt B. **Khác biệt duy nhất với B** là lọc `WHERE chapter = %s`, chỉ áp dụng cho câu có `filter`. 19 câu còn lại chạy không lọc và ghi `filter_applied: null` trong trace.
  - A–B chỉ đổi cách chunk; B–C chỉ đổi filter. Cả ba dùng cùng corpus, model, câu hỏi và top-3.
- **Bộ câu hỏi, phân chia, câu metadata filter và cách kiểm chứng evidence:**
  - Có **24 câu**, chia **18 dev / 6 test**, chốt trước khi chạy retrieval. Loại câu: `direct` 7, `paraphrase` 6, `condition` 6, `filter` 5.
  - **5 câu có `filter: {"chapter": N}`**: 3 câu dev (q08, q09, q10), 2 câu test (q21, q22). Mỗi câu chỉ mơ hồ khi thiếu phạm vi; ví dụ q08 và q09 có cùng câu hỏi về khoảng trắng theo PEP 8 nhưng thuộc chương 4 và chương 6.
  - Câu q21 có thêm trang 141 làm evidence thay thế (`alternative_evidence`).
  - `scripts/verify_benchmark.py` kiểm tra: đủ trường, evidence (sau khi gộp khoảng trắng) nằm trên trang gold, trang gold thuộc đúng chương của filter, đủ số câu theo split và số câu filter. Kết quả là `Benchmark OK`.
  - Cách chia split và nguy cơ rò rỉ ghi trong [benchmark/README.md](../../benchmark/README.md).
- **Tiêu chí chọn chiến lược (chốt trước khi xem test):**
  - Xét trên **dev**, theo thứ tự: Evidence Hit@3, rồi Hit@1, rồi grounding thủ công, cuối cùng là ít chunk hơn hoặc ingest nhanh hơn.
  - Sau khi chọn thì cố định cấu hình và chỉ báo cáo test.

## Kết quả
Hit tự động chỉ được tính khi chunk thuộc đúng nguồn/trang gold **và** chứa **trọn** `evidence_quote` sau khi gộp khoảng trắng.

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 5/18 | 8/18 | 220 | ingest 2,63 s; query TB 14,96 ms | 24.975 token ≈ $0,00050 |
| A | test | 1/6 | 2/6 | 220 | ↑ | ↑ |
| B | dev | 6/18 | 11/18 | 131 | ingest 1,25 s; query TB 13,35 ms | 23.022 token ≈ $0,00046 |
| B | test | 1/6 | 3/6 | 131 | ↑ | ↑ |
| C | dev | **8/18** | **12/18** | 131 (dùng lại của B) | ingest 0,12 s; query TB 14,52 ms | 0 token (dùng lại vector B) |
| C | test | 2/6 | 5/6 | 131 | ↑ | ↑ |

Thời gian ingest gồm gọi API và ghi DB. Thời gian query chỉ tính phần tìm kiếm trong DB. 24 câu hỏi được embed một lần (297 token) và dùng chung cho cả ba cấu hình.

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,7 (n=10; 0: 3, 1: 7, 2: 0) | 11/18 | 0/2 (test); 0/5 (tất cả câu filter) | 1 / 2 / 3 → 1,333 |
| B | 1,8 (n=10; 0: 0, 1: 2, 2: 8) | 12/18 | 0/2 (test); 0/5 | 3 / 0 / 3 → 1,0 |
| C | 1,8 (n=10; cùng chunk với B) | 12/18 | **2/2** (test); **5/5** | 1 / 0 / 5 → **1,667** |

Grounding và metadata được chấm trên 6 câu test. "Filter tuân thủ" nghĩa là cả 3 kết quả top-3 đều đúng chương. A và B không lọc nên số liệu của chúng chỉ để so sánh.

**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Trace top-3 cho 3 cấu hình × 24 câu: [traces.jsonl](../../starter/results/traces.jsonl). Mỗi bản ghi gồm câu hỏi, gold, chunk_id, text, score, metadata, `evidence_hit`, `page_hit_only` và `filter_applied`.
- Các file chỉ số: [summary.json](../../starter/results/summary.json), [stats.json](../../starter/results/stats.json), [reingest_check.json](../../starter/results/reingest_check.json).
- Nhãn thủ công: [coherence.csv](../../starter/results/audit/coherence.csv), [grounding.csv](../../starter/results/audit/grounding.csv), [metadata.csv](../../starter/results/audit/metadata.csv). Tổng hợp trong [audit_summary.json](../../starter/results/audit_summary.json), tạo bằng `scripts/aggregate_audit.py`.
- Cách chọn mẫu coherence: 10 vị trí cố định, chọn trước khi chấm, là **ký tự giữa trang của 10 trang được tính đầu tiên** (p95–p104). Với mỗi cấu hình, chấm chunk chứa vị trí đó.
- Grounding chấm cả top-3 của mỗi câu test. Metadata chấm từng bản ghi top-3 của câu test, mở PDF đúng trang để đối chiếu.
- Nạp lại lần 2: số dòng trước và sau đều là 220/131/131, không ghi thêm dòng nào, không tốn token. Khi đổi tham số chunk (thử trong schema tạm), các chunk thừa bị xóa đúng.

## Phân tích và kết luận
- **So sánh A–B (chỉ đổi chunking):**
  - B hơn A ở dev Hit@3 (11/18 so với 8/18) và coherence (1,8 so với 0,7).
  - Nguyên nhân chính là A cắt đôi evidence: ở dev, **5/18 câu A lấy đúng trang gold nhưng chunk không chứa trọn evidence** (`page_hit_only`), còn B chỉ có 1/18.
  - Đổi lại, chunk nhỏ của A tập trung hơn: A trúng q12, q13 và q19 trong khi B trượt. Ở q19, chunk 1000 ký tự của B trên trang 109 trộn nhiều ý nên không lọt vào top-3; A trúng ngay ở top-1 (`p109:fixed:1`).
- **So sánh B–C (chỉ đổi filter):**
  - Top-3 của B và C giống hệt nhau trên 19 câu không có filter. Mọi khác biệt về Hit nằm ở các câu filter: q08 (từ Hit@3 lên Hit@1), q10 (từ trượt lên Hit@1), q21 và q22 (từ trượt lên trúng). Ở q09, top-3 có thay đổi nhưng cả hai cấu hình đều trúng ở top-1.
  - Câu filter có Hit@3 là 5/5 ở C so với 2/5 ở B; tuân thủ filter là 5/5 so với 0/5.
- **Ví dụ sai 1, q10 (dev, filter, gold p116, chương 4) dưới B:**
  - Câu hỏi "What does nesting allow a programmer to do?" không có filter nên B lấy `p132:paragraph:1` (chương 5, nested loop), `p149:paragraph:1` (chương 6) và `p144:paragraph:0` (chương 5), không chunk nào nói về câu lệnh rẽ nhánh lồng nhau.
  - Với `chapter=4`, C lấy `p116:paragraph:1` ở top-1 và chứa trọn evidence.
  - Đây là lỗi mơ hồ từ vựng giữa các chương; metadata giải quyết được, còn chunking thì không.
- **Ví dụ sai 2, q24 (test, condition, gold p170) dưới A:**
  - A lấy đúng trang 170 (`p170:fixed:1`, rank 2) nhưng chunk bắt đầu giữa câu: "(such as lists) should not be used as default values". Phần lý do "Default parameter values are only defined once…" nằm ở chunk trước.
  - Chunk này thiếu điều kiện nên grounding thủ công chỉ được 1 và Evidence Hit tính là trượt. B giữ trọn câu trong `p170:paragraph:0` nên trúng ở top-1.
- **Lỗi khác:**
  - q01, q04 và q18 trượt ở cả 3 cấu hình (ví dụ q01 "How many comparison operators…" ra p104, p99, p121 thay vì p98). Nguyên nhân nằm ở embedding hoặc cách diễn đạt câu hỏi, không phải ở chunking.
  - q16 đúng trang 157 nhưng sai chunk ở cả 3 cấu hình.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:**
  - Theo tiêu chí đã chốt, chọn **C** (dev Hit@3 12/18, hơn B 11/18 và A 8/18). Test xác nhận cùng chiều: Hit@3 5/6, grounding 1,667/2.
  - Chi phí thêm của C so với B bằng 0 (không tốn token, không thêm chunk). Đánh đổi nằm ở chỗ C **phụ thuộc vào việc người dùng cung cấp đúng chương**: lọc sai chương thì bằng chứng đúng bị loại hoàn toàn. Không có filter thì C chính là B.
  - So với A, B và C có ít chunk hơn (131 so với 220), ingest ít token hơn, chunk dễ đọc hơn, nhưng chunk dài hơn nên đôi khi kém tập trung (q12, q13, q19).
  - C phù hợp khi corpus có phạm vi rõ ràng (chương hoặc mục) và người dùng biết phạm vi đó trước khi hỏi.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - **Test nhỏ:** chỉ 6 câu, mỗi câu tương đương ±16,7 điểm %. Dev có 18 câu, chênh lệch giữa B và C (11 so với 12) chỉ là 1 câu. Kết quả chỉ áp dụng cho corpus này.
  - **Metadata `section` chỉ đúng ở cấp trang:** trang có 2 section thì mọi chunk đều mang cả hai tên. Có 19/54 bản ghi đã kiểm tra mang tên một section mà chunk không thuộc về (đối chiếu vị trí dòng tiêu đề), nên các bản ghi đó bị chấm 0. `source`, `page` và `chapter` đúng cả 54/54.
  - **Gold chưa đủ:** q21 dưới A lấy `p140:fixed:2` có câu tương đương với evidence ("…else statement runs after the loop's execution is completed without being interrupted by a break"), nhưng benchmark chỉ ghi trang 143 và 141. Hit tự động vì vậy tính thiếu cho A, còn grounding thủ công cho 2. Benchmark không được sửa vì đã xem test.
  - **Rò rỉ:** q05 (dev) và q19 (test) cùng ở trang 109; q21 và q22 (test) cùng nằm trong mục 5.5. Câu hỏi do chính người làm bài viết sau khi đọc corpus.
  - **Nhãn:** chỉ có một người chấm, không có người chấm thứ hai để đo độ đồng thuận.
  - **Mẫu coherence lệch về chương 4:** 10 vị trí (p95–p104) đều thuộc chương 4, chủ yếu là văn xuôi mở đầu chương. Chưa đo trang nhiều code hay bảng của chương 5–6, nên điểm coherence 0,7 / 1,8 chỉ đại diện cho loại trang này.
  - **Đo thời gian:** chạy một lần trên máy local với ít dòng (131–220 dòng mỗi cấu hình), nên không đại diện cho corpus lớn hoặc khi dùng index ANN.
  - **Chi phí:** lấy từ `usage.total_tokens` của API, nhân với giá $0,02 trên 1 triệu token.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  - Gán `section` theo **vị trí tiêu đề trong trang** (dùng `char_start`) thay vì theo trang.
  - Thêm BM25 hoặc hybrid cho các câu có từ khóa chính xác như q01, giữ nguyên chunk và filter để so sánh có kiểm soát.
  - Bỏ các nhãn "TRY IT", chú thích ảnh và đáp án trắc nghiệm trước khi chunk. Gộp các chunk đuôi quá ngắn (B có chunk ngắn nhất 6 ký tự).
  - Thử thêm overlap cho B để giảm trường hợp evidence bị cắt.
  - Mở rộng tập test, ghi đủ các trang có evidence tương đương ngay từ đầu, và có người chấm thứ hai.

## Công cụ AI và cách kiểm tra
- Đã dùng Claude Code (Anthropic) để hỗ trợ viết code pipeline, phân tích dữ liệu và soạn báo cáo.
- Cách kiểm tra:
  - Kiểm thử bất biến của chunking trên 76 trang: text chunk khớp đúng `[char_start:char_end]`, không vượt độ dài tối đa, không mất ký tự, ID không trùng và chạy lại ra kết quả như cũ.
  - Chạy thử toàn bộ pipeline với embedder giả trong một schema Postgres tạm, sau đó xóa schema.
  - Chạy `verify_benchmark.py`, `--reingest-check`, và đối chiếu số đếm SQL với `stats.json`.
- Nhãn coherence, grounding và metadata do học viên chấm. Riêng 19 nhãn metadata ở cột `section` được chuyển thành 0 sau khi một script đối chiếu vị trí tiêu đề section trong trang; học viên đã duyệt lại.
