# Benchmark — Day 06

Bộ câu hỏi được viết và chốt **trước khi chạy chunking/retrieval**. Không sửa câu hỏi, nhãn hay split sau khi xem kết quả; nếu buộc phải sửa, ghi lại ở cuối file này.

- File: `questions.jsonl`, mỗi dòng là một câu hỏi.
- Kiểm chứng: từ `starter/` chạy `python scripts/verify_benchmark.py`. Script kiểm tra evidence nằm đúng trang gold sau chuẩn hóa, filter khớp metadata và đủ số lượng tối thiểu.
- Corpus: `openstax-intro-python`, chương 4–6 (PDF trang 95–174), xem `data/manifest.json`.

## Thống kê

| | dev | test | tổng |
|---|---:|---:|---:|
| Số câu | 18 | 6 | 24 |
| Có filter | 3 | 2 | 5 |

Loại câu: `direct` 7, `paraphrase` 6, `condition` 6 (điều kiện/ngoại lệ), `filter` 5.
Phân bố gold theo chương: dev có 10 câu chương 4, 4 câu chương 5, 4 câu chương 6; test có 1 câu chương 4, 3 câu chương 5, 2 câu chương 6.

## Trường dữ liệu

| Trường | Ý nghĩa |
|---|---|
| `id`, `split`, `type` | Mã câu, `dev`/`test`, loại câu để phân tích lỗi |
| `question` | Câu hỏi đưa vào truy xuất, không chứa đáp án hay số trang |
| `expected_answer` | Đáp án tham chiếu cho người chấm |
| `gold_source_id`, `gold_page` | Nguồn và **số trang PDF vật lý** (1-based) chứa evidence |
| `evidence_quote` | Đoạn trích nguyên văn từ trang gold, đủ để trả lời |
| `filter` | `null` hoặc `{"chapter": N}`: phạm vi người dùng cung cấp **trước khi truy xuất** |
| `alternative_evidence` | Các cặp trang/evidence khác cũng hợp lệ; trúng một trong số đó vẫn tính hit |

**Quy tắc so khớp evidence:** so sánh sau khi gộp mọi khoảng trắng (kể cả xuống dòng) thành một dấu cách, vì PDF ngắt dòng giữa câu. Chunk được tính hit khi `source_id`/`page` trùng một cặp gold và text chunk chứa **trọn** `evidence_quote` của cặp đó. Evidence bị tách qua hai chunk thì không tính hit, mà được ghi thành lỗi.

## Câu có filter

Trường `chapter` lấy từ bookmark của PDF (xem `filter_field` trong manifest), không suy đoán. Filter là **input giả định**: người dùng nói rõ mình đang học chương nào. Mỗi câu filter được chọn sao cho câu hỏi **mơ hồ nếu không có phạm vi**:

- `q08`/`q09`: cùng câu hỏi về khoảng trắng theo PEP 8. Chương 4 nói về khoảng trắng quanh toán tử, chương 6 nói về `=` trong keyword argument.
- `q10`: "nesting" (chương 4, câu lệnh rẽ nhánh lồng nhau) dễ nhầm với nested loop (chương 5).
- `q21`: "else block" (chương 5, loop else) dễ nhầm với if-else (chương 4).
- `q22`: biến Boolean (chương 5, biến cờ thay cho loop else) dễ nhầm với phần Boolean ở chương 4.

Cấu hình A và B chạy mọi câu **không filter**. Cấu hình C chỉ áp dụng filter cho 5 câu trên; 19 câu còn lại chạy không filter và được ghi rõ trong trace.

## Cách chia dev/test và nguy cơ rò rỉ

Chỉ có một tài liệu nên không thể chia theo tài liệu. Test được chọn thủ công để phủ cả 3 chương và các loại câu `paraphrase`, `condition` và `filter`, mỗi khái niệm chỉ xuất hiện ở một split. Các nguy cơ rò rỉ:

- `q05` (dev) và `q19` (test) có evidence cùng nằm ở trang 109 (associativity). Chọn cấu hình dựa trên q05 có thể có lợi cho q19.
- `q21`/`q22` (test) cùng nằm trong mục 5.5. `q22` có evidence ở trang 141, trùng với evidence thay thế của `q21`.
- Cả bộ câu hỏi do tác giả viết sau khi đọc corpus, nên câu hỏi có thể gần với cách diễn đạt của sách hơn câu hỏi thực tế. Các câu `paraphrase` được đổi từ ngữ để giảm hiện tượng này.
- Test chỉ có 6 câu: chênh 1 câu tương đương ±16,7 điểm %. Kết quả chỉ mang tính minh họa.

## Tiêu chí chọn cấu hình (chốt trước khi xem test)

Chọn trên **dev** theo thứ tự ưu tiên:

1. Evidence Hit@3 cao hơn;
2. nếu bằng, Hit@1 cao hơn;
3. nếu vẫn bằng, điểm grounding thủ công cao hơn;
4. nếu vẫn bằng, ít chunk hơn hoặc ingest nhanh hơn.

Sau khi chọn thì cố định cấu hình, rồi mới chạy test **một lần** để báo cáo.

## Ghi nguồn

Các đoạn `evidence_quote` là trích ngắn từ *Introduction to Python Programming* (Udayan Das, Aubrey Lawson, Chris Mayfield, Narges Norouzi), OpenStax, Rice University, giấy phép CC BY-NC-SA 4.0. Access for free at openstax.org.

## Nhật ký thay đổi

- 2026-11-14: tạo bộ 24 câu, chạy `verify_benchmark.py` kết quả `Benchmark OK`. Chưa chạy retrieval.
