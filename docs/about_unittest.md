# Báo cáo hệ thống kiểm thử tự động (Unit Test)

**Dự án:** `cls-sync-data-btp`  
**Ngày cập nhật:** 15/06/2026  
**Phạm vi:** Tài liệu nội bộ

---

## Tóm tắt mở đầu

Hệ thống **cls-sync-data-btp** đóng vai trò tự động đọc văn bản pháp luật, phát hiện **quan hệ pháp lý** (sửa đổi, bãi bỏ, dẫn chiếu...) và xây dựng Đồ thị tri thức (Knowledge Graph).

Để đảm bảo độ chính xác của đồ thị này, dự án đã xây dựng một **hệ thống kiểm thử tự động (Unit Test)**. Hệ thống này đóng vai trò như một **"người lính gác"**, đảm bảo mọi logic bóc tách pháp lý đều chính xác trước khi đưa vào vận hành.

**Số liệu nổi bật:**

- **Tổng số kịch bản kiểm thử:** 691 bài test tự động.
- **Tốc độ thực thi:** Hoàn thành toàn bộ chỉ trong **~17.4 giây**.
- **Độc lập hoàn toàn:** Chạy trực tiếp, không phụ thuộc vào cơ sở dữ liệu thật (MongoDB, Neo4j, hay Elasticsearch).
- **Độ bao phủ:** Phân thành 6 nhóm kiểm thử chuyên sâu, quét từ các lỗi chính tả nhỏ nhất đến các luồng logic đồ thị phức tạp và lớp điều phối pipeline.

---

## 1. Tại sao hệ thống cần Unit Test?

Văn bản pháp luật Việt Nam có cấu trúc rất phức tạp, với nhiều biến thể cách viết dễ gây nhầm lẫn hoặc sinh lỗi hệ thống nếu bóc tách sai bằng mắt thường hoặc code cứng.

Hệ thống kiểm thử tự động giải quyết các bài toán rủi ro sau:

- **Chống nhận diện sai cấu trúc:** Phân biệt rạch ròi `điểm đ` và `điểm d` (tiếng Việt), hay `điểm d1` không bị cắt cụt thành `điểm d`.
- **Chống nhận diện sai số hiệu:** Số hiệu phức tạp như `66.13/2026/NQ-CP` không bị hệ thống hiểu nhầm thành `66`.
- **Chống nhầm lẫn văn bản:** Cùng một số hiệu nhưng khác cơ quan ban hành (ví dụ: Quyết định của UBND Tỉnh A vs Tỉnh B) là hai văn bản hoàn toàn khác nhau.
- **Phân loại chính xác tác động pháp lý:** Phân biệt được "Quy định chi tiết" và "Hướng dẫn thi hành" là hai loại quan hệ khác nhau với mức độ ảnh hưởng khác nhau.

> **Giá trị cốt lõi:** Mỗi khi đội ngũ kỹ thuật nâng cấp hoặc sửa đổi mã nguồn, bộ test sẽ tự động chạy lại toàn bộ. Nếu có bất kỳ sự thay đổi nào làm hỏng các quy tắc pháp lý đã đúng trước đó, hệ thống sẽ **báo lỗi ngay lập tức** (chặn lỗi phát sinh — Regression).

---

## 2. Kiến trúc 6 nhóm kiểm thử trọng tâm

Hệ thống kiểm thử được tổ chức thành 6 phân hệ độc lập, mô phỏng lại toàn bộ chu trình sống của một dữ liệu pháp lý — từ bóc tách, lưu trữ, đo lường chất lượng đến điều phối pipeline và tích hợp với dịch vụ ngoài.

| Nhóm kiểm thử | Trách nhiệm cốt lõi | Mức độ |
|---|---|:---:|
| **1. Hồi quy đồ thị** *(Graph Regression)* | **Chống lặp lại lỗi cũ:** Đảm bảo hệ thống không mắc lại các sai sót bóc tách đã từng xảy ra khi gặp các câu từ pháp lý hóc búa. | Nhóm bảo vệ |
| **2. Trích xuất quan hệ** *(Relation Extraction)* | **Kiểm tra "Bộ não" hệ thống:** Đảm bảo máy tính phân biệt đúng hành vi pháp lý (Văn bản A đang *bãi bỏ*, *sửa đổi*, hay chỉ *tham chiếu* văn bản B). | Nhóm cốt lõi |
| **3. Cơ chế đồ thị** *(Graph Mechanism)* | **Bảo vệ kho dữ liệu:** Đảm bảo khi lưu thông tin, các sợi dây liên kết giữa các văn bản không bị đứt gãy, thất thoát hay trùng lặp. | Nhóm nền tảng |
| **4. Công cụ đánh giá** *(Evaluation Tools)* | **Kiểm toán báo cáo:** Đảm bảo các con số đo lường hiệu suất được hệ thống báo cáo (VD: Độ chính xác 99%) là trung thực, chính xác. | Nhóm giám sát |
| **5. Pipeline & Điều phối** *(Pipeline Tests)* | **Kiểm tra "Người chỉ huy":** Đảm bảo bước thu thập `doc_ids`, làm giàu danh mục văn bản Luật (`law_docs.csv`), và orchestrator (`main.py`, `scripts/run_pipeline.py`) truyền đúng tham số giữa Phase 1 và Phase 2. | Nhóm điều phối |
| **6. Tích hợp dịch vụ ngoài** *(Client/Provider Tests)* | **Kiểm tra cầu nối ra ngoài:** Đảm bảo lớp gọi LLM dự phòng (LangExtract qua endpoint nội bộ CMC) cấu hình provider, cache và fallback đúng trước khi gửi request thật. | Nhóm tích hợp |

---

## 3. Chi tiết từng nhóm kiểm thử

### 3.1. Nhóm hồi quy đồ thị (Graph Regression Tests)

Bảo vệ hệ thống khỏi **30 kịch bản đặc biệt khó (Edge Cases)**. Hệ thống chia làm nhiều tầng kiểm tra:

- **Tầng bóc tách:** Phân loại đúng loại quan hệ (sửa đổi, bổ sung, v.v.) và đọc đúng các cấu trúc liệt kê ("từ điểm d đến điểm e").
- **Tầng định vị (Resolver):** Khả năng hệ thống "đoán" đúng văn bản. Ví dụ: khi văn bản viết tắt là `HĐND` / `UBND`, hệ thống vẫn nhận diện được tên đầy đủ; hoặc xử lý các trường hợp văn bản trùng số hiệu, trùng năm bằng cách dùng ngày ban hành để phân biệt chính xác.

### 3.2. Nhóm trích xuất quan hệ (Relation Extraction Tests)

Đây là nhóm kiểm thử chuyên sâu nhất, chia theo từng loại hành vi pháp lý:

- **Nhóm Dẫn chiếu (`dan_chieu`):** Phân biệt được đâu là dẫn chiếu ra văn bản khác, đâu là dẫn chiếu nội bộ (VD: "theo quy định tại khoản này").
- **Nhóm Sửa đổi, bổ sung (`sua_doi_bo_sung`):** Xử lý các tình huống phức tạp khi một điều khoản con tự động "kế thừa" phạm vi tác động từ điều khoản cha.
- **Nhóm Hành động tác động mạnh (`bai_bo`, `dinh_chinh`, `ngung_hieu_luc`...):** Đảm bảo khoanh vùng đúng phạm vi điều khoản bị tác động, tránh việc máy tính "xóa nhầm" toàn bộ văn bản.
- **Xử lý số hiệu:** Chuẩn hóa các số hiệu viết sai quy cách trong dữ liệu thực tế (thiếu dấu gạch ngang, số thập phân...).

### 3.3. Nhóm cơ chế đồ thị (Graph Mechanism Tests)

Đảm bảo luồng lưu trữ hoạt động trơn tru:

- Chạy thử nghiệm 4 chế độ ghi dữ liệu (từ dễ dãi đến khắt khe).
- Kiểm tra tính năng đối soát (Reconciliation): Tự động phát hiện đồ thị đang thừa hay thiếu quan hệ so với thực tế.
- Kiểm tra khả năng đồng bộ và phân biệt nguồn gốc dữ liệu (Ví dụ: dữ liệu từ Thư viện Pháp luật vs dữ liệu tự bóc tách).

### 3.4. Nhóm Đánh giá chất lượng (Evaluation Tests)

Bảo vệ độ tin cậy của các báo cáo. Đảm bảo rằng khi hệ thống báo cáo "Độ chính xác đạt 99%", thì con số đó được tính toán bằng công thức chuẩn mực (True Positive / False Positive...), không bị sai lệch số liệu thống kê. Bao gồm cả bộ phân tích lỗi (`error_analysis`) — gom nhóm và đếm các trường hợp trích xuất sai để phục vụ rà soát thủ công.

### 3.5. Nhóm Pipeline & Điều phối (Pipeline Tests)

Kiểm tra lớp điều phối nằm trên hai pha trích xuất/xây dựng đồ thị:

- **Thu thập `doc_ids`:** Phân loại đúng văn bản theo phạm vi (trung ương/địa phương, có là Luật/Bộ luật/Hiến pháp hay không) trước khi đưa vào pipeline.
- **Làm giàu danh mục Luật (`law_docs.csv`):** Đảm bảo văn bản Luật/Bộ luật/Hiến pháp mới phát hiện được ghi bổ sung đúng định dạng, không trùng lặp.
- **`main.py` orchestrator:** Kiểm tra chế độ dry-run và việc truyền tham số (MongoDB collection, batch size...) đúng từ Phase 1 sang Phase 2.
- **`scripts/run_pipeline.py`:** Kiểm tra các chế độ chạy `full` / `incremental` / custom doc-ids-file.

### 3.6. Nhóm Tích hợp Client/Provider (Client Tests)

Kiểm tra lớp gọi dịch vụ LLM dự phòng (`LangExtractRelationFallback`) — ví dụ đảm bảo khi cấu hình `base_url` nội bộ (CMC), hệ thống ép đúng provider OpenAI-compatible thay vì gọi nhầm sang dịch vụ Gemini công khai. Đây là tuyến phòng vệ đầu tiên trước khi pipeline thực sự gọi ra ngoài.

---

## 4. Các điểm cần hoàn thiện trong tương lai (Khoảng trống Coverage)

Dù đã rất toàn diện, hệ thống vẫn đang lên kế hoạch phủ sóng các vùng kỹ thuật sau:

1. **Bao phủ toàn bộ khuôn mẫu (Regex Matrix):** Bổ sung bài test rà soát 1-1 cho hàng trăm khuôn mẫu (pattern) nhận biết câu chữ pháp lý.
2. **Kiểm thử hỗn loạn (Fuzz/Property Testing):** Tạo ra các câu văn bản chứa dấu câu dị thường, dấu ngoặc kép lồng nhau nhiều lớp, hoặc các câu quá dài để thử thách sức chịu đựng của thuật toán.
3. **Mở rộng Integration Test:** Bổ sung thêm các bài kiểm thử chạy trực tiếp trên cơ sở dữ liệu thật (Elasticsearch/MongoDB) để đánh giá đường truyền và hiệu suất tải thực tế.

---

## 5. Hướng dẫn chạy

Hệ thống kiểm thử được thiết kế để có thể kích hoạt bằng một dòng lệnh duy nhất.

```bash
# Lệnh chạy toàn bộ 691 bài test (Khuyến nghị trước khi tạo phiên bản mới)
python run_tests.py

# Lệnh chạy độc lập kiểm tra một nhóm tính năng:
python -m unittest discover -s tests/graph_regression_tests -v
python -m unittest discover -s tests/relation_extraction_tests -v
python -m unittest discover -s tests/graph_mechanism_tests -v
python -m unittest discover -s tests/evaluation_tests -v
python -m unittest discover -s tests/pipeline_tests -v
python -m unittest discover -s tests/client_tests -v
```

---

## 6. Kết luận: Khi nào coi là đủ an toàn?

**Hệ thống được coi là an toàn để vận hành khi và chỉ khi CẢ 6 nhóm kiểm thử trên đều PASS 100%.**

Tuy nhiên, Unit Test chủ yếu đảm bảo **không lặp lại lỗi cũ** và **bảo vệ logic gốc**. Khi đối mặt với các văn bản pháp luật có cách hành văn hoàn toàn mới chưa từng có trong lịch sử, vẫn cần định kỳ kết hợp đánh giá thực tế (Evaluation Report) và kiểm tra tích hợp trên cơ sở dữ liệu thật để duy trì chất lượng cao nhất cho Đồ thị tri thức.
