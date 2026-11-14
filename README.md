# Day 06 · Data Ingestion Engineering

## Bài làm: Nguyễn Đức Hải (2A202603943)

- **Corpus:** *Introduction to Python Programming* (OpenStax, CC BY-NC-SA 4.0), chương 4–6, PDF trang 95–174, 76 trang nội dung. Xem [data/manifest.json](data/manifest.json).
- **Embedding:** OpenAI `text-embedding-3-small`, 1536 chiều. **Vector store:** PostgreSQL 16 + pgvector 0.8.7, tìm kiếm cosine chính xác.
- **Cấu hình:** A = cắt cố định 500/50; B = theo đoạn, tối đa 1000; C = B + lọc `chapter`.
- **Báo cáo:** [report/individual/2A202603943_NguyenDucHai.md](report/individual/2A202603943_NguyenDucHai.md). **Nhật ký thí nghiệm:** [artifacts/experiment_log.csv](artifacts/experiment_log.csv). **Kết quả:** [starter/results/](starter/results/README.md).

### Tái lập
Cần Python 3.11–3.14, Docker và một OpenAI API key. Các lệnh chạy từ thư mục `starter/`:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # psycopg 3.3.8, pypdf 6.x, python-dotenv 1.x, openai 3.50.0
cp .env.example .env                      # điền OPENAI_API_KEY và EMBEDDING_MODEL=text-embedding-3-small
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py             # kỳ vọng: Setup OK

# PDF gốc không commit (giấy phép yêu cầu ghi nguồn trên từng trang); tải về data/raw/:
curl -L -o data/raw/Introduction_to_Python_Programming-WEB.pdf \
  https://assets.openstax.org/oscms-prodcms/media/documents/Introduction_to_Python_Programming-WEB.pdf

python scripts/build_manifest.py          # manifest, data/processed/pages.jsonl, results/ingest_log.csv
python scripts/verify_benchmark.py        # kỳ vọng: Benchmark OK
python -m src.run                         # ingest A/B/C, chạy 24 câu, ghi traces/summary/stats và mẫu chấm tay
python -m src.run --reingest-check        # nạp lại lần 2, số dòng không đổi
python scripts/aggregate_audit.py         # tổng hợp nhãn trong results/audit/
```

`src.run` không ghi đè các file chấm tay đã có, trừ khi chạy với cờ `--overwrite-audit`. Bản PDF đã dùng có sha256 ghi trong manifest.

---

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
