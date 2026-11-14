# Kết quả

| File | Nội dung | Tạo bởi |
|---|---|---|
| `ingest_log.csv` | Trạng thái từng trang PDF (`ok` / `excluded` / `empty` / `error`), số ký tự trước và sau làm sạch | `scripts/build_manifest.py` |
| `traces.jsonl` | Top-3 của 3 cấu hình × 24 câu: chunk_id, text, score, metadata, `evidence_hit`, `page_hit_only`, `filter_applied` | `python -m src.run` |
| `summary.json` | Hit@1 và Evidence Hit@3 dạng n/N theo cấu hình × split, cùng số liệu riêng cho câu có filter | `python -m src.run` |
| `stats.json` | Số chunk, phân bố độ dài, token, chi phí, thời gian ingest và query, số dòng trong DB | `python -m src.run` |
| `embedding_usage.csv` | Token và chi phí của mỗi lần gọi API, kể cả lần ingest đầu tiên | `python -m src.run` |
| `reingest_check.json` | Số dòng trước và sau khi nạp lại lần 2 | `python -m src.run --reingest-check` |
| `audit/coherence.csv`, `audit/grounding.csv`, `audit/metadata.csv` | Nhãn chấm tay | Mẫu do `src.run` sinh ra; nhãn do học viên điền |
| `audit_summary.json` | Tổng hợp các nhãn chấm tay | `scripts/aggregate_audit.py` |

## Ghi nguồn
Các đoạn text trong `traces.jsonl` và `audit/` là trích từ *Introduction to Python Programming* (Udayan Das, Aubrey Lawson, Chris Mayfield, Narges Norouzi), OpenStax, Rice University, giấy phép [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Chỉ dùng cho mục đích học tập, phi thương mại. Access for free at openstax.org.
