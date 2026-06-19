# CLS Legal Knowledge Graph

[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/) [![Neo4j](https://img.shields.io/badge/Neo4j-Graph_DB-008CC1.svg)](https://neo4j.com/) [![MongoDB](https://img.shields.io/badge/MongoDB-Raw_Data-47A248.svg)](https://www.mongodb.com/) [![Elasticsearch](https://img.shields.io/badge/Elasticsearch-Search_Engine-005571.svg)](https://www.elastic.co/)

Repo này xây dựng pipeline Python để trích xuất quan hệ pháp lý từ văn bản pháp luật Việt Nam và nạp các quan hệ đó vào đồ thị tri thức Neo4j. MongoDB lưu trữ kho dữ liệu nguồn và kết quả trích xuất trung gian, Elasticsearch/Dataframe giải quyết ID văn bản được tham chiếu, và Neo4j lưu trữ đồ thị.

Pipeline gồm hai giai đoạn chính:

1. Trích xuất quan hệ pháp lý từ nội dung văn bản đã phân tích cú pháp và ghi kết quả có cấu trúc vào MongoDB tại collection `cls_graph`.
2. Chuyển đổi quan hệ đã trích xuất và cấu trúc phân cấp văn bản thành các node và quan hệ Neo4j, với tùy chọn nhập từ TVPL và xuất ngược về MongoDB `cls_luoc_do`.

Codebase hiện hỗ trợ: trích xuất xác định theo quy tắc/regex, xử lý tham chiếu pháp lý tiếng Việt chuyên biệt, fallback LangExtract/LLM tùy chọn, quan hệ gián tiếp/suy luận ở cấp độ văn bản, chế độ ghi đồ thị chặt chẽ, báo cáo kiểm tra, và test hồi quy.

## Các Loại Quan Hệ Được Trích Xuất

| Quan hệ | Ý nghĩa |
| --- | --- |
| `can_cu` | Căn cứ pháp lý. |
| `dan_chieu` | Trích dẫn/tham chiếu, bao gồm tham chiếu nội bộ. |
| `sua_doi_bo_sung` | Sửa đổi, bổ sung cấp văn bản. |
| `thay_the` | Thay thế. |
| `bai_bo` | Bãi bỏ. |
| `huy_bo` | Hủy bỏ. |
| `dinh_chi` | Đình chỉ. |
| `dinh_chinh` | Đính chính. |
| `huong_dan` | Hướng dẫn thi hành. |
| `quy_dinh_chi_tiet` | Quy định chi tiết thi hành. |
| `keo_dai_hieu_luc` | Kéo dài hiệu lực. |
| `ngung_hieu_luc` | Ngưng hiệu lực. |
| `hop_nhat` | Quan hệ văn bản hợp nhất dành cho văn bản VBHN. |
| `sua_doi` | Sửa đổi cấp điều khoản.|
| `bo_sung` | Bổ sung cấp điều khoản.|

Việc trích xuất không chỉ đơn giản là quét từ khóa. Hệ thống xét đến: phạm vi câu và điều khoản, kiểu và mẫu số văn bản, tiêu đề luật, thành phần điều/khoản/điểm, ngữ cảnh cha con, tham chiếu nội bộ, phần mở đầu VBHN, ràng buộc cơ quan ban hành, và xung đột loại quan hệ.

## Cấu Trúc Dự Án

```text
.
|-- main.py                         # Wrapper CLI chạy toàn bộ pipeline
|-- run_tests.py                    # Chạy bộ unittest
|-- requirements.txt                # Phụ thuộc runtime/test
|-- .env.example                    # Mẫu biến môi trường
|-- data/
|   |-- law_docs.csv                # Dữ liệu tiêu đề luật cho regex/lookup
|-- docs/                           # Tài liệu kỹ thuật và báo cáo
|-- evaluation/
|-- scripts/                        # run_pipeline.py (orchestrator),
|   |                                #   get_doc_ids.py, benchmark, kiểm tra, Neo4j
|-- src/
|   |-- extract_relations.py         # Điểm vào CLI Giai đoạn 1
|   |-- build_graph.py               # Điểm vào CLI Giai đoạn 2 (shim mỏng)
|   |-- app/                         # Điểm vào CLI Giai đoạn 2 đầy đủ
|   |-- configs/                     # File YAML cấu hình: kiểu văn bản, ánh xạ
|   |                                #   khóa-giá trị, mẫu số văn bản
|   |-- domain/
|   |   |-- extractors/              # RelationsExtractor, BaseExtractor, trường hợp đặc biệt,
|   |   |                            #   base_extractor_flow/ (các mixin trích xuất dạng module)
|   |   |-- builders/                # hierarchy_builder
|   |   |-- graph/                   # relation_event.py
|   |   |-- llms/                    # Fallback LLM (relation_fallback.py, prompts, examples)
|   |   |-- model/                   # relation_types.py (hằng số loại quan hệ tập trung)
|   |   |-- queries/                 # Truy vấn Cypher (nodes.py, relationships.py)
|   |-- infrastructure/              # Cấu hình, kết nối, logging
|   |-- repositories/                # Truy cập dữ liệu MongoDB, Neo4j, Elasticsearch
|   |-- search/                      # Helper tìm kiếm văn bản được tham chiếu
|   |-- services/
|   |   |-- extraction/              # reference_resolution_service.py
|   |   |-- (15+ file service khác)  # Orchestrator xây dựng đồ thị, write coordinator,
|   |                                #   reconciliation, TVPL, Luoc Do, quan hệ suy diễn
|   |-- shared/                      # Checkpoint, text, data, helper trích xuất
|   `-- utils/                       # Tiện ích quan hệ, xử lý VBHN
`-- tests/
    |-- relation_extraction_tests/
    |-- graph_regression_tests/
    |-- graph_mechanism_tests/
    |-- pipeline_tests/
    |-- evaluation_tests/
    |-- client_tests/
    `-- test_data/
```

## Mô Hình Đồ Thị

### Nhãn Node

| Nhãn | Ý nghĩa |
| --- | --- |
| `VAN_BAN` | Văn bản pháp luật. Khóa chính: `ID`, lấy từ `cls_ID`. |
| `DIEU_KHOAN` | Thành phần văn bản như điều, khoản, hoặc điểm. Định dạng khóa chính: `<com_key>#<cls_ID>`. |

Thuộc tính node được chuẩn bị từ `cls_info`, bao gồm: tiêu đề, số hiệu văn bản, tình trạng hiệu lực, ngày ban hành/có hiệu lực, người ký, cơ quan ban hành, và loại văn bản.

### Nhóm Quan Hệ

| Nhóm | Quan hệ |
| --- | --- |
| Cấu trúc phân cấp | `bao_gom`, `bao_gom_sau_bo_sung`|
| Trích xuất từ `cls_graph.success` | `can_cu`, `dan_chieu`, `sua_doi_bo_sung`, `thay_the`, `bai_bo`, `huy_bo`, `dinh_chi`, `dinh_chinh`, `huong_dan`, `quy_dinh_chi_tiet`, `keo_dai_hieu_luc`, `ngung_hieu_luc`, `hop_nhat` , `sua_doi`, `bo_sung`|
| Suy diễn từ `cls_graph.inferred_relations` | `sua_doi_bo_sung`, `dinh_chinh`, `huong_dan`, `keo_dai_hieu_luc`, `dan_chieu`, `ngung_hieu_luc` |
| Nguồn TVPL tùy chọn | Khóa TVPL từ `cls_luoc_do`, chuẩn hóa về các loại quan hệ tiêu chuẩn ở trên. |

## Yêu Cầu Hệ Thống

- Python 3.12+
- MongoDB — lưu trữ văn bản nguồn và kết quả đầu ra
- Elasticsearch — giải quyết tham chiếu văn bản
- Neo4j 5.x
- Thủ tục Neo4j APOC (lệnh ghi đồ thị sử dụng APOC merge queries)

Cài đặt phụ thuộc (dự án dùng `uv` để quản lý dependency):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install uv
uv pip install -r requirements.txt
```

Linux/macOS:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install uv
uv pip install -r requirements.txt
```

## Cấu Hình

Tạo file `.env` từ `.env.example`. Không commit thông tin xác thực thật.

Các biến quan trọng:

```dotenv
# MongoDB nguồn — kho văn bản CLS
MONGO_PROD_HOST=localhost
MONGO_PROD_PORT=27017
MONGO_PROD_USER=your_username
MONGO_PROD_PASSWORD=your_password
MONGO_PROD_DATABASE=vanbanphapluat
CLS_DATABASE=vanbanphapluat
CLS_COLLECTION=cls_ver2

# MongoDB IE/đầu ra — dùng khi xây dựng đồ thị
MONGO_DEV_HOST=localhost
MONGO_DEV_PORT=27017
MONGO_DEV_USER=your_username
MONGO_DEV_PASSWORD=your_password
MONGO_DEV_DATABASE=ie
IE_DATABASE=ie
IE_COLLECTION=ie_collection

# Elasticsearch — giải quyết tham chiếu
ES_DEV_ENDPOINT=http://localhost:9200
ES_DEV_USER=elastic
ES_DEV_PASSWORD=your_password
ES_DEV_DOCUMENT_INDEX=law_documents
ES_DEV_TERM_INDEX=law_terms

# Neo4j — đích lưu đồ thị
NEO4J_ENV=DEV
NEO4J_DEV_HOST=localhost
NEO4J_DEV_PORT=7687
NEO4J_DEV_USER=neo4j
NEO4J_DEV_PASSWORD=your_password
NEO4J_DEV_DATABASE=neo4j

# LLM fallback tùy chọn
LEGAL_LLM_MODEL_ID=
LEGAL_LLM_BASE_URL=
LEGAL_LLM_API_KEY=
```

Lưu ý vận hành:

- `src.extract_relations` đọc văn bản nguồn từ kết nối `MONGO_PROD` và ghi kết quả IE vào `IE_DATABASE`/`IE_COLLECTION` qua cùng kết nối Mongo.
- `src.build_graph` đọc dữ liệu nguồn CLS qua `MONGO_PROD`; với dữ liệu IE, dùng `MONGO_DEV` nếu được cấu hình, fallback về `MONGO_PROD` nếu không.
- Elasticsearch ưu tiên `ES_DEV_ENDPOINT`, sau đó `ES_PROD_ENDPOINT`.
- `src.build_graph` dùng `--neo4j-env` và `--neo4j-database` để chọn đích Neo4j.
- Giữ `.env` riêng tư. Dùng `.env.example` cho ví dụ cấu hình có thể chia sẻ.

## File Input

Các lệnh pipeline nhận file JSON chứa danh sách ID văn bản:

```json
[1001, 1002, 1003]
```

Loader chuẩn hóa giá trị về kiểu integer khi có thể.

## Chạy Toàn Bộ Pipeline

Có hai cách chạy: qua **orchestrator** `scripts/run_pipeline.py` (khuyến nghị cho chạy định kỳ — tự động thu thập ID, làm giàu `data/law_docs.csv`, rồi build đồ thị trong một lệnh), hoặc gọi trực tiếp `main.py` khi đã có sẵn file `doc_ids.json` (vd. tập ID thử nghiệm tùy chỉnh).

### `scripts/run_pipeline.py` — orchestrator (khuyến nghị)

Điều phối `collect IDs → enrich law_docs.csv → assemble doc_ids.json → build graph`, có thể lập lịch chạy hằng ngày. Mỗi bước vẫn chạy độc lập được (`scripts/get_doc_ids.py`, `LawDocsEnrichmentService`, `main.py`); script này chỉ nối chúng lại.

Xem trước các bước và lệnh `main.py` dự kiến mà không thực thi gì:

```bash
python scripts/run_pipeline.py --mode incremental --neo4j-env DEV --neo4j-db test --dry-run
```

Rebuild toàn bộ — gom `central_ids.json` + `local_ids.json` (loại trùng):

```bash
python scripts/run_pipeline.py \
  --mode full \
  --neo4j-env DEV \
  --neo4j-db neo4jtest \
  --mongo-extraction-collection test \
  --extraction-batch-size 1000 \
  --extraction-parallel-workers 16 \
  --graph-batch-size 500 \
  --graph-parallel-workers 1 \
  --node-batch-size 300 \
  --structural-rel-batch-size 300 \
  --status-rel-batch-size 150 \
  --inferred-rel-batch-size 100 \
  --tvpl-batch-size 300 \
  --luoc-do-batch-size 200 \
  --with-tvpl \
  --with-luoc-do-export \
  --clear-es-cache \
  --clear-checkpoints \
  --reconcile-after-build \
  --graph-audit-output reports/graph_audit.json \
  --graph-resolution-mode strict \
  --delete-orphan-nodes
```

Cập nhật hằng ngày — chỉ ID mới phát hiện, gom `latest_central_ids.json` + `latest_local_ids.json`:

```bash
python scripts/run_pipeline.py \
  --mode incremental \
  --neo4j-env DEV \
  --neo4j-db neo4jtest \
  --mongo-extraction-collection test \
  --extraction-batch-size 1000 \
  --extraction-parallel-workers 16 \
  --graph-batch-size 500 \
  --graph-parallel-workers 1 \
  --node-batch-size 300 \
  --structural-rel-batch-size 300 \
  --status-rel-batch-size 150 \
  --inferred-rel-batch-size 100 \
  --tvpl-batch-size 300 \
  --luoc-do-batch-size 200 \
  --with-tvpl \
  --with-luoc-do-export \
  --clear-es-cache \
  --clear-checkpoints \
  --reconcile-after-build \
  --graph-audit-output reports/graph_audit.json \
  --graph-resolution-mode strict \
  --delete-orphan-nodes
```

Flag riêng của orchestrator:

| Flag | Mục đích |
| --- | --- |
| `--mode {full,incremental}` | Chọn nguồn ID: `full` = `central_ids + local_ids`; `incremental` = `latest_central_ids + latest_local_ids`. Loại trừ với `--doc-ids-file`. |
| `--doc-ids-file <path>` | Dùng tập ID tùy chỉnh; bỏ qua hoàn toàn bước collect + enrich và forward thẳng cho `main.py`. Loại trừ với `--mode`. |
| `--skip-collect` | Bỏ qua thu thập ID, tái sử dụng các file `data/doc_ids/*.json` hiện có (bỏ qua nếu dùng `--doc-ids-file`). |
| `--skip-enrich` | Bỏ qua làm giàu `data/law_docs.csv` (bỏ qua nếu dùng `--doc-ids-file`). |
| `--dry-run` | In các bước và lệnh `main.py` dự kiến mà không thực thi. |

Orchestrator tự lắp `--doc-ids-file` (file `data/doc_ids.json` đã gom + loại trùng), luôn gọi `main.py` kèm `--reset-relations`, và forward các flag dùng chung ở bảng dưới — chỉ khi bạn set tường minh (không set thì giữ nguyên giá trị mặc định của `main.py`).

### Gọi trực tiếp `main.py` (file ID có sẵn)

`main.py` điều phối Giai đoạn 1 (`src.extract_relations`) và Giai đoạn 2 (`src.build_graph`); yêu cầu `--doc-ids-file` trỏ tới file JSON danh sách ID (xem [File Input](#file-input)).

Xem trước các lệnh giai đoạn dự kiến:

```bash
python main.py --doc-ids-file data/doc_ids.json --dry-run
```

Chạy với file ID có sẵn:

```bash
python main.py \
  --doc-ids-file data/doc_ids.json \
  --extraction-batch-size 1000 \
  --graph-batch-size 500 \
  --extraction-parallel-workers 16 \
  --graph-parallel-workers 1 \
  --mongo-extraction-collection test \
  --neo4j-env DEV \
  --neo4j-db test \
  --with-tvpl \
  --with-luoc-do-export \
  --reset-relations \
  --node-batch-size 300 \
  --structural-rel-batch-size 300 \
  --status-rel-batch-size 150 \
  --inferred-rel-batch-size 100 \
  --tvpl-batch-size 300 \
  --luoc-do-batch-size 200 \
  --clear-es-cache \
  --clear-checkpoints \
  --reconcile-after-build \
  --graph-audit-output reports/graph_audit.json \
  --graph-resolution-mode strict \
  --delete-orphan-nodes
```

Các flag dùng chung của `main.py` (cũng được orchestrator forward khi set tường minh):

| Flag | Mục đích |
| --- | --- |
| `--dry-run` | In các lệnh giai đoạn dự kiến mà không thực thi. |
| `--only-extract` | Chỉ chạy Giai đoạn 1. |
| `--only-build` | Chỉ chạy Giai đoạn 2. |
| `--skip-extraction` | Bỏ qua Giai đoạn 1, bắt đầu từ xây dựng đồ thị. |
| `--skip-build` | Dừng sau khi trích xuất. |
| `--clear-es-cache` | Xóa ES cache trước khi trích xuất. |
| `--clear-checkpoints` | Xóa checkpoint liên quan trước khi bắt đầu. |
| `--suffix` | Hậu tố tùy chỉnh cho log/checkpoint. Mặc định là tên file input. |
| `--use-llm` | Bật fallback LangExtract/LLM khi trích xuất. |
| `--skip-already-processed` | Bỏ qua văn bản đã có kết quả quan hệ. |
| `--skip-infer-relations` | Bỏ qua sinh quan hệ suy diễn ở Giai đoạn 1. |
| `--with-tvpl` | Bao gồm quan hệ TVPL từ `cls_luoc_do`. |
| `--with-luoc-do-export` | Xuất quan hệ Neo4j ngược về MongoDB. |
| `--reset-relations` | Trước khi build, xóa quan hệ ngữ nghĩa **đi-ra** của các node trong phạm vi (giữ `bao_gom`/`bao_gom_sau_bo_sung`, không xóa node, không đụng quan hệ đi-vào ngoài phạm vi). Thay thế hoàn toàn `--clear-before-build` cũ (đã loại bỏ — không an toàn vì `DETACH DELETE` xóa cả node và quan hệ đi-vào). |
| `--re-update` | Làm mới toàn bộ thuộc tính cho node đã tồn tại. |
| `--skip-enrichment` | Bỏ qua bổ sung metadata cho node skeleton. |
| `--skip-nodes`, `--skip-bao-gom` | Bỏ qua giai đoạn con xây dựng node đồ thị và quan hệ bao gồm. |
| `--only-luoc-do-export` | Chỉ chạy xuất Neo4j→MongoDB `cls_luoc_do`. |
| `--show-stats` | In thống kê đồ thị trước và sau khi xây dựng. |

## Đánh Giá và Test

Chạy toàn bộ bộ unittest:

```bash
python run_tests.py
```

Chạy với đầu ra verbose:

```bash
python run_tests.py -v
```

Chạy benchmark/đánh giá trích xuất:

```bash
python -m evaluation.evaluate \
  --dataset evaluation/datasets/relation_pairs.csv \
  --output evaluation/reports/result.json \
  --breakdown \
  --details
```

Chạy test theo nhóm cụ thể:

```bash
python -m unittest discover -s tests/graph_regression_tests -p "test_*.py" -v
python -m unittest discover -s tests/relation_extraction_tests -p "test_*.py" -v
python -m unittest discover -s tests/graph_mechanism_tests -p "test_*.py" -v
python -m unittest discover -s tests/pipeline_tests -p "test_*.py" -v
```

## Lưu Ý

- TVPL là nguồn bổ sung tùy chọn. Hãy kiểm tra đầu ra `cls_graph` trước, sau đó thêm `--with-tvpl` nếu cần quan hệ TVPL bổ sung.
- Chế độ `--use-llm` đang ở giai đoạn kiểm thử. Hiện tại không sử dụng LLM, xây dựng đồ thị bằng rule-based.

## File Cấu Hình Tĩnh

Thư mục `src/configs/` chứa các file YAML được `ConfigLoader` nạp lúc runtime:

| File | Nội dung |
| --- | --- |
| `doc_and_clause_types.yml` | Định nghĩa kiểu văn bản và điều khoản |
| `doc_key_val_mapping.yml` | Ánh xạ trường khóa-giá trị văn bản |
| `doc_number_patterns.yml` | Mẫu regex nhận dạng số văn bản |

Các file này được nạp lười (lazy) khi dùng lần đầu và **không phải** module Python — không import trực tiếp.

## Tài Liệu Tham Khảo

| Tài liệu | Mục đích |
| --- | --- |
| [docs/relation_types_overview.md](docs/relation_types_overview.md) | Tổng quan loại quan hệ và ví dụ. |
| [docs/performance_report.md](docs/performance_report.md) | Kết quả benchmark và kiến trúc hiệu năng. |
| [docs/evaluation_report.md](docs/evaluation_report.md) | Báo cáo đánh giá và ghi chú chất lượng trích xuất. |
| [docs/about_unittest.md](docs/about_unittest.md) | Hướng dẫn độ phủ unittest và bộ test. |

---

Được duy trì bởi nhóm CLS Data.
