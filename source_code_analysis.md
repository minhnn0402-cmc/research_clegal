# Báo Cáo Phân Tích Mã Nguồn Hệ Thống Đồ Thị Tri Thức Pháp Luật (LKG)

Báo cáo này phân tích chi tiết cấu trúc mã nguồn, luồng xử lý và cơ chế hoạt động của dự án **cls-sync-data-btp** thuộc nhánh `graph`. Hệ thống được thiết kế để trích xuất các quan hệ pháp lý từ văn bản pháp luật nguồn trong MongoDB và xây dựng Đồ thị tri thức (Knowledge Graph) trên cơ sở dữ liệu đồ thị Neo4j.

Báo cáo được cấu trúc thành hai phần rõ ràng và thống nhất:
1. **PHẦN I: TỔNG QUAN HỆ THỐNG (OVERVIEW)**: Sơ đồ luồng dữ liệu (Flowchart) và mô tả chức năng của từng bước trong pipeline từ đầu vào đến đầu ra (A → B → C...).
2. **PHẦN II: CHI TIẾT TỪNG BƯỚC XỬ LÝ (DETAILED MECHANICS)**: Đi sâu phân tích thuật toán, cấu trúc dữ liệu, cơ chế tối ưu hiệu năng (như song song hóa, bộ đệm ghi lô, bộ nhớ đệm cache, mSearch) và các câu lệnh truy vấn cốt lõi cho từng thành phần từ A đến M.

---

## PHẦN I: TỔNG QUAN HỆ THỐNG (OVERVIEW)

### 1. Sơ Đồ Luồng Xử Lý Tổng Thể (Pipeline Flowchart)

Dưới đây là sơ đồ chi tiết biểu diễn luồng dữ liệu từ pha Trích xuất quan hệ (Phase 1) đến pha Xây dựng Đồ thị (Phase 2):

<div class="lkg-flowchart-container">
    <style>
        .lkg-flowchart-container {
            background-color: #0b0c10;
            color: #d1d5db;
            padding: 24px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 20px 0;
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }
        .lkg-flow-title {
            font-family: 'Outfit', sans-serif;
            font-size: 18px;
            font-weight: 700;
            color: #ffffff;
            margin: 0 0 20px 0;
            padding-bottom: 8px;
            border-bottom: 2px solid #6c5ce7;
            display: inline-block;
        }
        .lkg-flow-phase {
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
            background: rgba(255, 255, 255, 0.01);
        }
        .lkg-flow-phase:last-child {
            margin-bottom: 0;
        }
        .lkg-flow-phase-title {
            font-size: 14px;
            font-weight: 700;
            color: #6c5ce7;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 14px;
        }
        .lkg-flow-subgraph {
            border: 1px solid rgba(255,255,255,0.03);
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 12px;
            background: rgba(0, 0, 0, 0.15);
        }
        .lkg-flow-subgraph:last-child {
            margin-bottom: 0;
        }
        .lkg-flow-subgraph-title {
            font-size: 12px;
            font-weight: 600;
            color: #8b92b6;
            margin-bottom: 10px;
            border-left: 3px solid #00dec9;
            padding-left: 8px;
        }
        .lkg-flow-step {
            display: flex;
            align-items: center;
            margin-bottom: 8px;
            gap: 12px;
            font-size: 12px;
            flex-wrap: nowrap;
        }
        .lkg-flow-step:last-child {
            margin-bottom: 0;
        }
        .lkg-flow-badge {
            background: rgba(108, 92, 231, 0.12);
            color: #a29bfe;
            border: 1px solid rgba(108, 92, 231, 0.25);
            font-size: 10px;
            font-weight: 700;
            padding: 2px 6px;
            border-radius: 10px;
            min-width: 42px;
            text-align: center;
            flex-shrink: 0;
        }
        .lkg-flow-node {
            padding: 4px 10px;
            border-radius: 4px;
            font-weight: 600;
            white-space: nowrap;
            font-size: 11px;
            border: 1px solid transparent;
            flex-shrink: 0;
        }
        .lkg-node-file {
            background: rgba(255, 118, 117, 0.1);
            color: #ff7675;
            border-color: rgba(255, 118, 117, 0.2);
        }
        .lkg-node-code {
            background: rgba(108, 92, 231, 0.1);
            color: #a29bfe;
            border-color: rgba(108, 92, 231, 0.2);
        }
        .lkg-node-mongo {
            background: rgba(0, 222, 201, 0.1);
            color: #58ebd3;
            border-color: rgba(0, 222, 201, 0.2);
        }
        .lkg-node-neo4j {
            background: rgba(253, 150, 68, 0.1);
            color: #ffa801;
            border-color: rgba(253, 150, 68, 0.2);
        }
        .lkg-flow-arrow {
            color: #8b92b6;
            font-size: 11px;
            flex-grow: 1;
            display: flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .lkg-flow-line {
            height: 1px;
            background: rgba(255, 255, 255, 0.08);
            flex-grow: 1;
            min-width: 20px;
        }
    </style>

    <h2 class="lkg-flow-title">Sơ đồ luồng xử lý hệ thống LKG</h2>

    <!-- PHASE 1 -->
    <div class="lkg-flow-phase">
        <div class="lkg-flow-phase-title">Pha 1: Trích xuất Quan hệ (Văn bản sang MongoDB)</div>

        <!-- P1_Orchestration -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">1. Khởi tạo & Điều phối</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">1</span>
                <span class="lkg-flow-node lkg-node-file">doc_ids.json</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Đầu vào ID văn bản ➔</span>
                <span class="lkg-flow-node lkg-node-file">extract_relations.py</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">2</span>
                <span class="lkg-flow-node lkg-node-file">extract_relations.py</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Khởi tạo điều phối ➔</span>
                <span class="lkg-flow-node lkg-node-code">RelationsProcessorService</span>
            </div>
        </div>

        <!-- P1_Extraction -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">2. Bóc tách Quan hệ (Văn bản sang từ khóa cues)</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">3a/3b</span>
                <span class="lkg-flow-node lkg-node-code">RelationsProcessorService</span>
                <span class="lkg-flow-arrow">Yêu cầu đọc văn bản ⇄ <span class="lkg-flow-line"></span> Trả về dữ liệu văn bản gốc</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo PROD: cls_ver2</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">4</span>
                <span class="lkg-flow-node lkg-node-code">RelationsProcessorService</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Yêu cầu bóc tách ➔</span>
                <span class="lkg-flow-node lkg-node-code">RelationsExtractor</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">5a/5b</span>
                <span class="lkg-flow-node lkg-node-code">RelationsExtractor</span>
                <span class="lkg-flow-arrow">Gửi câu phân tích ⇄ <span class="lkg-flow-line"></span> Trả về quan hệ thô</span>
                <span class="lkg-flow-node lkg-node-code">Rule-based Resolver</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">6a/6b</span>
                <span class="lkg-flow-node lkg-node-code">RelationsExtractor</span>
                <span class="lkg-flow-arrow">Gửi context fallback ⇄ <span class="lkg-flow-line"></span> Trả về quan hệ LLM</span>
                <span class="lkg-flow-node lkg-node-code">LangExtractFallback LLM</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">7</span>
                <span class="lkg-flow-node lkg-node-code">RelationsExtractor</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Trả về toàn bộ quan hệ thô ➔</span>
                <span class="lkg-flow-node lkg-node-code">RelationsProcessorService</span>
            </div>
        </div>

        <!-- P1_Resolution -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">3. Phân giải ID Đích (Từ khóa cues sang ID)</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8</span>
                <span class="lkg-flow-node lkg-node-code">RelationsProcessorService</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Yêu cầu phân giải ➔</span>
                <span class="lkg-flow-node lkg-node-code">post_process_relations</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">9a/9b</span>
                <span class="lkg-flow-node lkg-node-code">post_process_relations</span>
                <span class="lkg-flow-arrow">Gửi yêu cầu tra cứu nhanh ⇄ <span class="lkg-flow-line"></span> Trả về kết quả tra cứu</span>
                <span class="lkg-flow-node lkg-node-file">laws_dataframe CSV</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">10a/10b</span>
                <span class="lkg-flow-node lkg-node-code">post_process_relations</span>
                <span class="lkg-flow-arrow">Gửi truy vấn mSearch ⇄ <span class="lkg-flow-line"></span> Trả về kết quả tìm kiếm</span>
                <span class="lkg-flow-node lkg-node-mongo">Elasticsearch: law_documents_t4</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">11</span>
                <span class="lkg-flow-node lkg-node-code">post_process_relations</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Trả về quan hệ đã phân giải ➔</span>
                <span class="lkg-flow-node lkg-node-code">RelationsProcessorService</span>
            </div>
        </div>

        <!-- P1_Saving -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">4. Ghi Kết quả</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">12</span>
                <span class="lkg-flow-node lkg-node-code">RelationsProcessorService</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> bulk_write ghi lô ➔</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo DEV: ie_collection</span>
            </div>
        </div>
    </div>

    <!-- PHASE 2 -->
    <div class="lkg-flow-phase">
        <div class="lkg-flow-phase-title">Pha 2: Xây dựng Đồ thị (MongoDB sang Neo4j)</div>

        <!-- P2_Orchestration -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">1. Khởi tạo & Điều phối</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">1</span>
                <span class="lkg-flow-node lkg-node-file">data/all_ids.json</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Đọc danh sách ID văn bản ➔</span>
                <span class="lkg-flow-node lkg-node-file">build_graph.py</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">2</span>
                <span class="lkg-flow-node lkg-node-file">build_graph.py</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Khởi tạo điều phối ➔</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
            </div>
        </div>

        <!-- P2_NodeBuild -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">2. Khởi tạo Nút (Pha 1)</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">3a</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Yêu cầu tạo Nút ➔</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">3b/3c</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow">Truy vấn văn bản gốc ⇄ <span class="lkg-flow-line"></span> Trả về dữ liệu văn bản gốc</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo PROD: cls_ver2</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">3d/3e</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow">Gửi tài liệu thô ⇄ <span class="lkg-flow-line"></span> Trả về tham số Nút</span>
                <span class="lkg-flow-node lkg-node-code">NodePreparationService</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">3f</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Ghi Nút VAN_BAN & DIEU_KHOAN ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">3g</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Trả về kết quả khởi tạo ➔</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
            </div>
        </div>

        <!-- P2_BaoGomBuild -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">3. Khởi tạo liên kết bao_gom (Pha 2)</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">4a</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Yêu cầu tạo bao_gom ➔</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">4b/4c</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow">Truy vấn văn bản gốc ⇄ <span class="lkg-flow-line"></span> Trả về dữ liệu văn bản gốc</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo PROD: cls_ver2</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">4d/4e</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow">Gửi tài liệu thô ⇄ <span class="lkg-flow-line"></span> Trả về tham số bao_gom</span>
                <span class="lkg-flow-node lkg-node-code">NodePreparationService</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">4f</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Ghi quan hệ cấu trúc bao_gom ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">4g</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Trả về kết quả khởi tạo ➔</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
            </div>
        </div>

        <!-- P2_RelBuild -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">4. Xây dựng Quan hệ & Làm giàu (Pha 3-6)</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">5a/5b</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow">Yêu cầu đọc kết quả trích xuất ⇄ <span class="lkg-flow-line"></span> Trả về kết quả trích xuất</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo DEV: ie_collection</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">6a/6b</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow">Yêu cầu đọc văn bản gốc để enrich ⇄ <span class="lkg-flow-line"></span> Trả về dữ liệu văn bản gốc</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo PROD: cls_ver2</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">7a/7b</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow">Gửi tài liệu đã làm giàu ⇄ <span class="lkg-flow-line"></span> Trả về quan hệ thô</span>
                <span class="lkg-flow-node lkg-node-code">StatusRelationshipPreparationService</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8a</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Gửi quan hệ thô ➔</span>
                <span class="lkg-flow-node lkg-node-code">GraphRelationshipWriteCoordinator</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8b</span>
                <span class="lkg-flow-node lkg-node-code">GraphRelationshipWriteCoordinator</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Ghi quan hệ trực tiếp ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8c</span>
                <span class="lkg-flow-node lkg-node-code">GraphRelationshipWriteCoordinator</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Kích hoạt tự sửa chữa ➔</span>
                <span class="lkg-flow-node lkg-node-code">GraphNodeAutoHealer</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8d/8e</span>
                <span class="lkg-flow-node lkg-node-code">GraphNodeAutoHealer</span>
                <span class="lkg-flow-arrow">Yêu cầu đọc văn bản gốc ⇄ <span class="lkg-flow-line"></span> Trả về dữ liệu văn bản gốc</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo PROD: cls_ver2</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8f/8g</span>
                <span class="lkg-flow-node lkg-node-code">GraphNodeAutoHealer</span>
                <span class="lkg-flow-arrow">Gửi tài liệu gốc để phân tích ⇄ <span class="lkg-flow-line"></span> Trả về tham số nút</span>
                <span class="lkg-flow-node lkg-node-code">NodePreparationService</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8h</span>
                <span class="lkg-flow-node lkg-node-code">GraphNodeAutoHealer</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Khôi phục nút ảo và phân cấp ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8i</span>
                <span class="lkg-flow-node lkg-node-code">GraphNodeAutoHealer</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Báo cáo hoàn thành tự sửa chữa ➔</span>
                <span class="lkg-flow-node lkg-node-code">GraphRelationshipWriteCoordinator</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">8j</span>
                <span class="lkg-flow-node lkg-node-code">GraphRelationshipWriteCoordinator</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Trả về kết quả ghi ➔</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">9</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Lan truyền bo_sung ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">10a/10b</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow">Yêu cầu đọc inferred_relations ⇄ <span class="lkg-flow-line"></span> Trả về inferred_relations</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo DEV: ie_collection</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">10c/10d</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow">Gửi quan hệ suy luận ⇄ <span class="lkg-flow-line"></span> Trả về quan hệ gián tiếp</span>
                <span class="lkg-flow-node lkg-node-code">InferredRelationshipService</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">11</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Ghi quan hệ gián tiếp ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">12a/12b</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow">Yêu cầu đọc lược đồ TVPL ⇄ <span class="lkg-flow-line"></span> Trả về dữ liệu lược đồ TVPL</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo PROD: cls_ver2</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">12c/12d</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow">Gửi lược đồ TVPL ⇄ <span class="lkg-flow-line"></span> Trả về quan hệ TVPL</span>
                <span class="lkg-flow-node lkg-node-code">TVPLRelationshipService</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">13</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Ghi quan hệ TVPL ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">14a</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Yêu cầu làm giàu nút ảo ➔</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">14b/14c</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow">Truy vấn siêu dữ liệu gốc ⇄ <span class="lkg-flow-line"></span> Trả về siêu dữ liệu gốc</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo PROD: cls_ver2</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">14d/14e</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow">Gửi siêu dữ liệu gốc để phân tích ⇄ <span class="lkg-flow-line"></span> Trả về tham số nút ảo</span>
                <span class="lkg-flow-node lkg-node-code">NodePreparationService</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">14f</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Điền thuộc tính nút ảo ➔</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">14g</span>
                <span class="lkg-flow-node lkg-node-code">LegalKnowledgeGraphBuilder</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Trả về kết quả làm giàu ➔</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
            </div>
        </div>

        <!-- P2_SyncBack -->
        <div class="lkg-flow-subgraph">
            <div class="lkg-flow-subgraph-title">5. Đồng bộ ngược (Pha 5)</div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">15a</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Gọi đồng bộ ngược ➔</span>
                <span class="lkg-flow-node lkg-node-code">Neo4jToLuocDoPreparation</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">15b/15c</span>
                <span class="lkg-flow-node lkg-node-code">Neo4jToLuocDoPreparation</span>
                <span class="lkg-flow-arrow">Đọc quan hệ hai chiều ⇄ <span class="lkg-flow-line"></span> Trả về các quan hệ hai chiều</span>
                <span class="lkg-flow-node lkg-node-neo4j">Neo4j Database</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">16</span>
                <span class="lkg-flow-node lkg-node-code">Neo4jToLuocDoPreparation</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Ghi đè lược đồ cls_luoc_do ➔</span>
                <span class="lkg-flow-node lkg-node-mongo">Mongo DEV: ie_collection</span>
            </div>
            <div class="lkg-flow-step">
                <span class="lkg-flow-badge">17</span>
                <span class="lkg-flow-node lkg-node-code">Neo4jToLuocDoPreparation</span>
                <span class="lkg-flow-arrow"><span class="lkg-flow-line"></span> Trả về kết quả đồng bộ ➔</span>
                <span class="lkg-flow-node lkg-node-code">BuildGraphApp</span>
            </div>
        </div>
    </div>
</div>

#### Pha 1: Trích Xuất Quan Hệ (Phase 1: Relation Extraction)

Luồng hoạt động chính của Pha 1 di chuyển theo thứ tự sau:
* **1. A (doc_ids.json) → B (extract_relations.py)**: Tập tin `doc_ids.json` (A) cung cấp danh sách các ID văn bản pháp luật cần xử lý. Tệp chạy chính `extract_relations.py` (B) tiếp nhận danh sách này, đọc dữ liệu ID văn bản nguồn.
* **2. B (extract_relations.py) → C (RelationsProcessorService)**: Điểm khởi tạo chuyển quyền kiểm soát sang lớp điều phối dịch vụ `RelationsProcessorService` (C) để quản lý việc phân lô và chia nhỏ công việc.
* **3. D (Mongo PROD: cls_ver2) → C (RelationsProcessorService)**: Dịch vụ (C) truy vấn đọc văn bản pháp luật gốc (bao gồm cấu trúc cây điều khoản đã phân tích cú pháp) từ cơ sở dữ liệu nguồn MongoDB `cls_ver2` (D) thuộc môi trường Production.
* **4. C (RelationsProcessorService) → E (RelationsExtractor)**: Nội dung văn bản được gửi sang bộ xử lý cốt lõi `RelationsExtractor` (E) để yêu cầu bóc tách quan hệ thô của điều khoản.
* **5a. E (RelationsExtractor) → E1 (Rule-based Resolver)**: Trình bóc tách (E) gửi nội dung câu sang `Rule-based Resolver` (E1) để tìm khớp cues bằng Regex và giải quyết các tham chiếu nội bộ.
* **5b. E1 (Rule-based Resolver) → E (RelationsExtractor)**: Trả lại các quan hệ thô và cấu trúc tham chiếu tìm được về cho `RelationsExtractor` (E).
* **6a. E (RelationsExtractor) → F (LangExtractRelationFallback LLM)**: Nếu Regex không đủ tự tin hoặc gặp cấu trúc câu phức tạp, `RelationsExtractor` (E) gửi context sang `LangExtractRelationFallback LLM` (F).
* **6b. F (LangExtractRelationFallback LLM) → E (RelationsExtractor)**: Trả về kết quả bóc tách chuẩn hóa dưới định dạng JSON về cho `RelationsExtractor` (E).
* **7. E (RelationsExtractor) → C (RelationsProcessorService)**: Trả lại danh sách đầy đủ các quan hệ thô đã trích xuất của tài liệu về cho `RelationsProcessorService` (C).
* **8. C (RelationsProcessorService) → G (post_process_relations)**: Dịch vụ (C) gửi danh sách quan hệ thô sang module hậu xử lý `post_process_relations` (G) để tiến hành phân giải thông tin tài liệu đích sang ID cụ thể.
* **9a. G (post_process_relations) → H (laws_dataframe CSV)**: G gửi yêu cầu tra cứu nhanh (Fast-path Lookup) tới bộ nhớ DataFrame `laws_dataframe` (H) nạp sẵn trong RAM.
* **9b. H (laws_dataframe CSV) → G (post_process_relations)**: Trả về kết quả khớp ID văn bản đích từ DataFrame (nếu tìm thấy) cho G.
* **10a. G (post_process_relations) → I (Elasticsearch: law_documents_t4)**: Khi tra cứu nhanh trên RAM thất bại, G gửi truy vấn tìm kiếm mSearch tới Elasticsearch index `law_documents_t4` (I).
* **10b. I (Elasticsearch: law_documents_t4) → G (post_process_relations)**: Trả về kết quả tìm kiếm phù hợp chứa ID văn bản đích cho G.
* **11. G (post_process_relations) → C (RelationsProcessorService)**: Trả về các quan hệ đã được gán ID văn bản đích chính xác cho `RelationsProcessorService` (C).
* **12. C (RelationsProcessorService) → J (Mongo DEV: ie_collection)**: Kết quả phân giải hoàn chỉnh được tích lũy vào bộ đệm và ghi lô (bulk write) 500 tài liệu mỗi lần xuống MongoDB `ie_collection` (J) thuộc môi trường Development dưới trường `cls_graph`.


#### Pha 2: Xây Dựng Đồ Thị Tri Thức (Phase 2: Graph Building)

Luồng hoạt động của Pha 2 bao gồm các bước điều phối, xử lý dữ liệu và tương tác chặt chẽ giữa các dịch vụ để xây dựng đồ thị:
* **1. A1 (data/all_ids.json) → K (build_graph.py)**: CLI entry point `build_graph.py` (K) đọc danh sách các ID văn bản cần xử lý từ tệp cấu hình JSON đầu vào (A1).
* **2. K (build_graph.py) → L (BuildGraphApp)**: Khởi tạo lớp điều phối chính `BuildGraphApp` (L) để quản lý toàn bộ vòng đời và thứ tự chạy của Pha 2.
* **3a. L (BuildGraphApp) → N (LegalKnowledgeGraphBuilder)**: `BuildGraphApp` (L) gọi `LegalKnowledgeGraphBuilder` (N) để thực hiện Pha 1: Tạo các nút `VAN_BAN` và `DIEU_KHOAN`.
* **3b. N (LegalKnowledgeGraphBuilder) → P (Mongo PROD: cls_ver2)**: Builder (N) gửi yêu cầu truy vấn cấu trúc văn bản gốc và siêu dữ liệu từ MongoDB Production `cls_ver2` (P).
* **3c. P (Mongo PROD: cls_ver2) → N (LegalKnowledgeGraphBuilder)**: `cls_ver2` (P) trả về dữ liệu văn bản gốc (`cls_parsing`, `cls_info`) cho Builder (N).
* **3d. N (LegalKnowledgeGraphBuilder) → O (NodePreparationService)**: Builder (N) chuyển các tài liệu gốc thô sang `NodePreparationService` (O) để phân tích cấu trúc cây và trích xuất tham số nút.
* **3e. O (NodePreparationService) → N (LegalKnowledgeGraphBuilder)**: `NodePreparationService` (O) trả về danh sách các tham số nút `VAN_BAN` và `DIEU_KHOAN` cho Builder (N).
* **3f. N (LegalKnowledgeGraphBuilder) → M (Neo4j Graph Database)**: Builder (N) thực hiện ghi lô (bulk upsert) đồng loạt các nút vào `M (Neo4j Graph Database)`.
* **3g. N (LegalKnowledgeGraphBuilder) → L (BuildGraphApp)**: Trả về kết quả khởi tạo các nút cho L.
* **4a. L (BuildGraphApp) → N (LegalKnowledgeGraphBuilder)**: `BuildGraphApp` (L) gọi `LegalKnowledgeGraphBuilder` (N) để thực hiện Pha 2: Tạo các quan hệ cấu trúc `bao_gom` (liên kết phân cấp văn bản-điều-khoản).
* **4b. N (LegalKnowledgeGraphBuilder) → P (Mongo PROD: cls_ver2)**: Builder (N) gửi yêu cầu truy vấn cấu trúc cây phân cấp từ MongoDB Production `cls_ver2` (P).
* **4c. P (Mongo PROD: cls_ver2) → N (LegalKnowledgeGraphBuilder)**: `cls_ver2` (P) trả về dữ liệu văn bản gốc cho Builder (N).
* **4d. N (LegalKnowledgeGraphBuilder) → O (NodePreparationService)**: Builder (N) chuyển tài liệu gốc sang `NodePreparationService` (O) để chuẩn bị quan hệ cấu trúc.
* **4e. O (NodePreparationService) → N (LegalKnowledgeGraphBuilder)**: `NodePreparationService` (O) trả về danh sách tham số quan hệ `bao_gom` cho Builder (N).
* **4f. N (LegalKnowledgeGraphBuilder) → M (Neo4j Graph Database)**: Builder (N) ghi lô các cạnh `bao_gom` vào `M (Neo4j Graph Database)`.
* **4g. N (LegalKnowledgeGraphBuilder) → L (BuildGraphApp)**: Trả về kết quả khởi tạo quan hệ cấu trúc cho L.
*(Lưu ý: Để tối ưu hóa, nếu cả Pha 1 và Pha 2 cùng kích hoạt trong cấu hình chạy, hệ thống sẽ tự động gộp các bước 3b/3c và 4b/4c thành một lượt quét MongoDB duy nhất thông qua hàm `build_nodes_and_bao_gom`)*.
* **5a. L (BuildGraphApp) → J (Mongo DEV: ie_collection)**: `BuildGraphApp` (L) đọc kết quả trích xuất quan hệ của Pha 1 (bao gồm trường `cls_graph`) từ MongoDB Development `ie_collection` (J).
* **5b. L (BuildGraphApp) → P (Mongo PROD: cls_ver2)**: `BuildGraphApp` (L) truy vấn thông tin gốc từ MongoDB Production `cls_ver2` (P) để làm giàu ngữ cảnh và giải quyết các tham chiếu đích (như bổ sung điều khoản).
* **6a. L (BuildGraphApp) → Q (StatusRelationshipPreparationService)**: `BuildGraphApp` (L) gửi tài liệu thô đã được làm giàu sang `StatusRelationshipPreparationService` (Q) để bóc tách và phân loại các quan hệ nghiệp vụ trực tiếp (Pha 3).
* **6b. Q (StatusRelationshipPreparationService) → L (BuildGraphApp)**: Trả về danh sách các quan hệ thô đã được chuẩn bị cho `BuildGraphApp` (L).
* **7a. L (BuildGraphApp) → R (GraphRelationshipWriteCoordinator)**: `BuildGraphApp` (L) chuyển danh sách quan hệ thô sang `GraphRelationshipWriteCoordinator` (R) để điều phối quá trình ghi.
* **7b. R (GraphRelationshipWriteCoordinator) → M (Neo4j Graph Database)**: Coordinator (R) ghi các quan hệ trực tiếp (như `sua_doi`, `thay_the`, `bai_bo`, `can_cu`, `dan_chieu`) vào `M`.
* **8a. R (GraphRelationshipWriteCoordinator) → S (GraphNodeAutoHealer)**: Nếu phát hiện nút đích bị thiếu trên đồ thị khi ghi, coordinator kích hoạt cơ chế tự sửa chữa của `S (GraphNodeAutoHealer)`.
* **8b. S (GraphNodeAutoHealer) → P (Mongo PROD: cls_ver2)**: `GraphNodeAutoHealer` (S) gửi yêu cầu truy vấn cấu trúc tài liệu của nút đích tới MongoDB Production `cls_ver2` (P).
* **8c. P (Mongo PROD: cls_ver2) → S (GraphNodeAutoHealer)**: `cls_ver2` (P) trả về dữ liệu văn bản gốc cho `GraphNodeAutoHealer` (S).
* **8d. S (GraphNodeAutoHealer) → O (NodePreparationService)**: `GraphNodeAutoHealer` (S) gửi các tài liệu gốc thô sang `NodePreparationService` (O) để phân tích cấu trúc cây và trích xuất tham số nút.
* **8e. O (NodePreparationService) → S (GraphNodeAutoHealer)**: `NodePreparationService` (O) trả về danh sách các tham số nút `VAN_BAN` và `DIEU_KHOAN` cho `GraphNodeAutoHealer` (S).
* **8f. S (GraphNodeAutoHealer) → M (Neo4j Graph Database)**: Tự động khôi phục cấu trúc nút ảo cùng nhánh phân cấp cha-con tương ứng trên `M`.
* **8g. S (GraphNodeAutoHealer) → R (GraphRelationshipWriteCoordinator)**: Báo cáo hoàn thành tự sửa chữa cho coordinator.
* **8h. R (GraphRelationshipWriteCoordinator) → L (BuildGraphApp)**: Trả về kết quả ghi mối quan hệ kèm theo báo cáo tự sửa chữa cho `BuildGraphApp` (L).
* **9. L (BuildGraphApp) → M (Neo4j Graph Database)**: `BuildGraphApp` (L) chạy câu lệnh lan truyền `bo_sung` trên `M` để tự động sao chép quan hệ từ điều khoản cha sang các điều khoản con ảo.
* **10a. L (BuildGraphApp) → J (Mongo DEV: ie_collection)**: `BuildGraphApp` (L) đọc trường `cls_graph.inferred_relations` từ MongoDB Development `ie_collection` (J).
* **10b. L (BuildGraphApp) → T (InferredRelationshipService)**: Gửi thông tin sang `InferredRelationshipService` (T) để thực hiện bước suy luận quan hệ cấp văn bản (Pha 3b).
* **10c. T (InferredRelationshipService) → L (BuildGraphApp)**: Dịch khóa điều khoản và trả về danh sách quan hệ gián tiếp VB-VB kèm theo câu chứng cứ chứng minh.
* **11. L (BuildGraphApp) → M (Neo4j Graph Database)**: Thực hiện ghi lô các quan hệ gián tiếp vào `M`.
* **12a. L (BuildGraphApp) → P (Mongo PROD: cls_ver2)**: `BuildGraphApp` (L) truy vấn lược đồ lịch sử `cls_luoc_do` của nguồn TVPL trong MongoDB Production `cls_ver2` (P).
* **12b. L (BuildGraphApp) → U (TVPLRelationshipService)**: Gửi thông tin lược đồ TVPL sang `TVPLRelationshipService` (U) để hòa nhập dữ liệu TVPL (Pha 4).
* **12c. U (TVPLRelationshipService) → L (BuildGraphApp)**: Chuẩn hóa nhãn quan hệ, đảo chiều theo `REVERSED_RELATIONS` và trả về danh sách quan hệ TVPL.
* **13. L (BuildGraphApp) → M (Neo4j Graph Database)**: Chèn quan hệ TVPL vào `M` dưới sự bảo vệ của Priority Guard (không ghi đè quan hệ do CMCAI tạo ra).
* **14a. L (BuildGraphApp) → N (LegalKnowledgeGraphBuilder)**: `BuildGraphApp` (L) yêu cầu làm giàu nút ảo (Pha 6).
* **14b. N (LegalKnowledgeGraphBuilder) → P (Mongo PROD: cls_ver2)**: Builder (N) gửi yêu cầu truy vấn thông tin gốc cho các nút ảo xương tới MongoDB Production `cls_ver2` (P).
* **14c. P (Mongo PROD: cls_ver2) → N (LegalKnowledgeGraphBuilder)**: `cls_ver2` (P) trả về siêu dữ liệu gốc cho Builder (N).
* **14d. N (LegalKnowledgeGraphBuilder) → O (NodePreparationService)**: Builder (N) gửi các tài liệu gốc thô sang `NodePreparationService` (O) để phân tích cấu trúc cây và trích xuất thuộc tính cho nút ảo.
* **14e. O (NodePreparationService) → N (LegalKnowledgeGraphBuilder)**: `NodePreparationService` (O) trả về danh sách các tham số thuộc tính cho Builder (N).
* **14f. N (LegalKnowledgeGraphBuilder) → M (Neo4j Graph Database)**: Điền thuộc tính khớp chính xác/biến thể và cập nhật thuộc tính còn thiếu của các nút ảo lên `M`.
* **14g. N (LegalKnowledgeGraphBuilder) → L (BuildGraphApp)**: Trả về kết quả làm giàu nút ảo cho L.
* **15a. L (BuildGraphApp) → V (Neo4jToLuocDoPreparation)**: `BuildGraphApp` (L) gọi `Neo4jToLuocDoPreparation` (V) để bắt đầu bước đồng bộ ngược (Pha 5).
* **15b. V (Neo4jToLuocDoPreparation) → M (Neo4j Graph Database)**: `Neo4jToLuocDoPreparation` (V) truy vấn toàn bộ quan hệ hai chiều của các văn bản đang xử lý từ `M`.
* **15c. M (Neo4j Graph Database) → V (Neo4jToLuocDoPreparation)**: `M` trả về danh sách các quan hệ hai chiều cho `V`.
* **16. V (Neo4jToLuocDoPreparation) → J (Mongo DEV: ie_collection)**: Phân loại vai trò chủ động/bị động và ghi đè lược đồ `cls_luoc_do` hoàn chỉnh xuống MongoDB Development `ie_collection` (J) thông qua bulk_write của PyMongo.
* **17. V (Neo4jToLuocDoPreparation) → L (BuildGraphApp)**: Trả về kết quả đồng bộ ngược cho L.

---

## PHẦN II: CHI TIẾT TỪNG BƯỚC XỬ LÝ (DETAILED MECHANICS)

### 1. Chi Tiết Pha 1: Trích Xuất Quan Hệ (Relation Extraction)

#### Chi tiết A (doc_ids.json)
* **Cấu trúc**: Chứa mảng phẳng định dạng JSON lưu các số nguyên biểu thị ID văn bản pháp luật nguồn (`[12345, 67890, ...]`).
* **Ý nghĩa**: Cho phép chạy cập nhật tăng dần (incremental) thay vì quét toàn bộ MongoDB hàng triệu bản ghi, giảm tải cho hạ tầng.

#### Chi tiết B (extract_relations.py)
* **Orchestration**: Nhận tham số dòng lệnh thông qua `argparse`, khởi tạo `ConnectionManager` để thiết lập các kết nối kết nối MongoDB và Elasticsearch.
* **Tối ưu hóa phân trang**: Để tránh quá tải bộ nhớ RAM khi truy vấn MongoDB với danh sách hàng trăm ngàn ID, danh sách `doc_ids` được sắp xếp giảm dần và chia nhỏ thành các truy vấn lọc bằng toán tử `$in` với kích thước giới hạn bởi `max_ids_per_query` (mặc định 50.000 ID). Điều này tối ưu hóa việc lập kế hoạch thực thi truy vấn (Query Plan) của MongoDB.

#### Chi tiết C (RelationsProcessorService)
* **Kế thừa**: Kế thừa lớp trừu tượng `BatchProcessor` cung cấp vòng đời xử lý lô tài liệu.
* **Quy trình Batch**:
  1. Sử dụng phương thức `process_batch` để tải tài liệu theo từng lô có kích thước `batch_size` (mặc định 500).
  2. Sử dụng phân trang thông qua so sánh ID: `{"cls_ID": {"$lt": last_processed_id}}` kết hợp với sắp xếp giảm dần giúp MongoDB tận dụng chỉ mục (Index) hiệu quả mà không bị suy giảm hiệu năng do toán tử `skip`.
* **Cơ chế Checkpoint**: Định kỳ mỗi `checkpoint_interval` tài liệu xử lý thành công, trạng thái (ID cuối cùng và tổng số lượng đã xử lý) được lưu xuống đĩa thông qua `CheckpointManager`. Nếu tiến trình bị gián đoạn đột ngột (do lỗi mạng, ngắt tiến trình), hệ thống sẽ đọc checkpoint và tiếp tục từ vị trí dừng trong phiên chạy kế tiếp.
* **Bộ đệm Ghi Lô (Bulk Write Buffer)**: Kết quả trích xuất được tích lũy vào danh sách đệm `bulk_buffer`. Khi buffer đạt ngưỡng `bulk_buffer_size` (mặc định 500), dịch vụ gọi lệnh `bulk_write` để lưu đồng loạt xuống MongoDB `ie_collection`, giảm thiểu số lượng truy cập I/O mạng từ 500 lần xuống còn 1 lần.
* **ES Cache dùng chung (Cross-document Cache)**: Thiết lập bộ nhớ đệm `_es_cache` dùng chung giữa các luồng công việc để ghi nhớ kết quả phân giải thực thể của Elasticsearch.
  * *Thread safety*: Đọc ghi cache được bảo vệ bởi khóa `_es_cache_lock`.
  * *Persistence*: Cache được lưu tự động xuống tệp `logs/es_reference_cache.json` mỗi khi xả bộ đệm bulk write, giúp tái sử dụng kết quả phân giải cho các phiên chạy sau mà không cần truy vấn lại Elasticsearch qua VPN.
* **Parallel Workers (Đa luồng)**: Khởi tạo tiến trình xử lý song song với `parallel_workers` (mặc định 8 luồng). Dịch vụ sử dụng đối tượng luồng cục bộ `threading.local` để lưu trữ riêng biệt thực thể `RelationsExtractor` cho mỗi thread. Điều này ngăn chặn việc tranh chấp tài nguyên và giảm thiểu chi phí khởi tạo lại các cấu trúc dữ liệu từ điển cồng kềnh trong mỗi luồng xử lý văn bản.

#### Chi tiết D (Mongo PROD: cls_ver2)
* **Cấu trúc trường dữ liệu**:
  * `cls_ID`: Số nguyên định danh duy nhất của văn bản.
  * `cls_parsing`: Chứa cấu trúc cây điều khoản dạng danh mục (Điều, Khoản, Điểm) được nén bằng thuật toán Gzip và mã hóa nhị phân để tiết kiệm dung lượng lưu trữ trên MongoDB.
  * `cls_info`: Chứa siêu dữ liệu văn bản như `so_hieu`, `loai_van_ban`, `ngay_ban_hanh`, `co_quan_ban_hanh`, `title_without_number`.
* **Giải nén nhị phân**: `RelationsProcessorService` tự động kiểm tra định dạng của `cls_parsing`, nếu là nhị phân sẽ sử dụng thư viện `gzip` để giải nén trên RAM và giải mã chuỗi UTF-8 sang đối tượng JSON thô chứa danh sách các điều khoản.

#### Chi tiết E & E1 (RelationsExtractor & Rule-based Resolver)
* **Tự điển Cues**: Tập hợp các mẫu từ khóa tiếng Việt thể hiện các nhóm quan hệ pháp lý:
  * *Sửa đổi/Bổ sung*: "sửa đổi, bổ sung", "sửa đổi", "bổ sung", "được bổ sung", "bãi bỏ một phần".
  * *Thay thế*: "thay thế", "thay thế hoàn toàn".
  * *Bãi bỏ/Hủy bỏ*: "bãi bỏ", "hủy bỏ", "ngưng hiệu lực".
  * *Căn cứ/Dẫn chiếu*: "căn cứ", "chi tiết tại", "dẫn chiếu đến".
* **Rule-based Resolver (E1)**:
  * *Regex Engine*: Quét văn bản điều khoản để tìm khớp các từ khóa cues kèm theo tiêu đề hoặc số hiệu văn bản pháp luật đi liền sau.
  * *InternalReferenceResolver*: Giải quyết tham chiếu tắt nội bộ văn bản. Khi văn bản ghi "khoản 2 Điều này" hoặc "điểm a khoản này", Resolver phân tích đường dẫn phân cấp hiện tại (`com_path`) của điều khoản nguồn để tìm ra Điều cha hoặc Khoản cha tương ứng, từ đó ánh xạ chính xác đến định danh điều khoản mục tiêu nội bộ.
  * *DistractorFilter (Lọc bẫy ngữ cảnh)*: Loại bỏ các câu chứa từ khóa gây nhiễu nhưng không mang tính chất quan hệ hiệu lực. Ví dụ: từ "bổ sung" trong cụm từ "bổ sung hồ sơ dự án" sẽ bị lọc bỏ vì không tác động đến hiệu lực văn bản pháp luật khác.

#### Chi tiết F (LangExtractRelationFallback LLM)
* **Cơ chế Fallback**: Regex có giới hạn khi gặp các cấu trúc câu tiếng Việt phức tạp, câu đảo ngữ, hoặc câu chứa nhiều quan hệ phủ định lồng nhau. Khi điểm tin cậy bóc tách của Regex nằm dưới ngưỡng an toàn, hệ thống sẽ kích hoạt Fallback để gọi API LLM.
* **Prompt Engineering**: Prompt gửi đến LLM được chuẩn hóa cao độ, chứa văn bản điều khoản pháp lý cần xử lý, định nghĩa nghiêm ngặt về các loại quan hệ pháp lý đầu ra, và yêu cầu đầu ra bắt buộc phải tuân thủ cấu trúc JSON chứa các trường: `source_key`, `relationship`, `target_document_info` (loại văn bản, số hiệu, tiêu đề, cơ quan ban hành, ngày ban hành).
* **Parallel Calling**: Do việc gọi API LLM tốn thời gian chờ phản hồi từ mạng (I/O bound), hệ thống bọc các yêu cầu gọi LLM trong một `ThreadPoolExecutor` riêng để chạy song song nhiều yêu cầu cùng lúc, giúp luồng trích xuất chính không bị nghẽn.

#### Chi tiết G (post_process_relations)
* **Mục đích**: Nhận danh sách các quan hệ thô có chứa văn bản mô tả tài liệu đích (`target_value`), thực hiện phân giải chuỗi mô tả đó sang định danh số nguyên `cls_ID` hợp lệ trong hệ thống.
* **Quy trình hoạt động**:
  1. Gom nhóm tất cả các chuỗi mô tả văn bản đích độc nhất từ tất cả các mối quan hệ trích xuất được trong văn bản nguồn.
  2. Kiểm tra bộ nhớ đệm cache (`_es_cache`) trước để lấy kết quả nếu đã được phân giải trước đó.
  3. Nếu cache chưa có, tiến hành phân giải song song sử dụng `ThreadPoolExecutor` qua hai tầng tìm kiếm: `laws_dataframe` (H) và Elasticsearch (I).
  4. Lọc bỏ các mối quan hệ trùng lặp hoặc xung đột trên cùng một văn bản đích bằng quy tắc ưu tiên (`_CONFLICT_RELATION_PRIORITY`). Nếu một nguồn có cả quan hệ "sửa đổi" và "thay thế" tới cùng một đích, quan hệ "sửa đổi" có độ ưu tiên cao hơn sẽ được giữ lại, loại bỏ các quan hệ có độ ưu tiên yếu hơn để làm sạch dữ liệu.

#### Chi tiết H (laws_dataframe CSV)
* **Cơ chế RAM Fast-path**: Nạp tệp dữ liệu `law_docs.csv` chứa danh sách tất cả các văn bản Luật, Bộ Luật, Hiến pháp và Pháp lệnh của Việt Nam vào bộ nhớ RAM dưới dạng một Pandas DataFrame.
* **Xử lý viết tắt (Abbreviation Mapping)**: Tự động xây dựng sơ đồ ánh xạ từ các ký tự viết tắt phổ biến sang tiêu đề chính thức. Ví dụ: "Luật TTHC" được chuyển đổi thành "Luật Tố tụng hành chính", "Luật đất đai 2013" được quy đổi sang ID chính xác trong 0ms mà không cần truy vấn mạng.
* **Lọc ngày tháng**: Áp dụng hàm `filter_law_dataframe` để so sánh và lựa chọn văn bản có ngày ban hành gần nhất hoặc khớp chính xác nhất với ngày tháng được trích xuất từ câu văn tham chiếu.

#### Chi tiết I (Elasticsearch: law_documents_t4)
* **Elasticsearch Index**: Sử dụng index `law_documents_t4` lưu trữ toàn bộ các văn bản pháp luật đã được đánh chỉ mục tìm kiếm full-text search.
* **Tối ưu hóa mSearch (Multi-Search)**:
  * Thay vì thực hiện các truy vấn tuần tự (truy vấn tìm theo số hiệu trước, nếu không thấy thì mới chạy tiếp truy vấn tìm theo tiêu đề), module sử dụng phương thức `msearch` của Elasticsearch để đóng gói cả hai truy vấn (một truy vấn so khớp chính xác số hiệu `so_hieu.keyword` và một truy vấn tìm kiếm mờ theo tiêu đề `title`) gửi đi trong một lượt yêu cầu duy nhất.
  * Giảm thiểu 50% độ trễ mạng qua đường truyền VPN doanh nghiệp.
* **Quy tắc Kiểm tra tính hợp lệ của Cache (is_persistent_es_cache_eligible)**:
  * Các văn bản cấp trung ương (không chứa chỉ thị địa phương như UBND, HĐND ở phần hậu tố số hiệu) luôn đủ điều kiện lưu cache persistent.
  * Các văn bản ban hành bởi chính quyền địa phương (chứa hậu tố `UBND` hoặc `HĐND` sau dấu gạch chéo cuối cùng của số hiệu, ví dụ: `12/QĐ-UBND`) chỉ được ghi vào cache persistent nếu tài liệu nguồn cung cấp thông tin rõ ràng về cơ quan ban hành (`co_quan_ban_hanh`). Quy tắc này ngăn chặn hiện tượng trùng lặp cache chéo giữa các tỉnh thành có cùng số hiệu văn bản địa phương.

#### Chi tiết J (Mongo DEV: ie_collection)
* **Đầu ra**: Lưu trữ cấu trúc kết quả trích xuất của Pha 1.
* **Cấu trúc dữ liệu lưu trữ**:
  ```json
  {
    "cls_ID": 12345,
    "cls_graph": {
      "success": [
        {
          "source_key": "dieu_3_khoan_1",
          "source_type": "khoan",
          "success": [
            {
              "relationship": "sua_doi_bo_sung",
              "target_doc_id": 67890,
              "target_key": "dieu_5",
              "target_value": {
                "dieu": {
                  "information": "Điều 5",
                  "position_start": 120,
                  "position_end": 150
                },
                "luat": {
                  "information": "Luật Đất đai",
                  "position_start": 155,
                  "position_end": 200
                }
              }
            }
          ]
        }
      ],
      "failed": [
        {
          "source_key": "dieu_4",
          "source_type": "dieu",
          "failed": {
            "luat": {
              "information": "Luật Đất đai cũ không rõ số hiệu",
              "position_start": 300,
              "position_end": 340
            }
          }
        }
      ],
      "has_failed": true,
      "updated_at": "2026-06-17T14:29:59.123Z"
    }
  }
  ```

---

### 2. Chi Tiết Pha 2: Xây Dựng Đồ Thị Tri Thức (Neo4j Graph Building)

#### Chi tiết K (build_graph.py)
* **Quản lý tham số**: Sử dụng bộ thư viện `argparse` để phân tích tham số dòng lệnh phong phú. Nó nhận diện các cờ chạy độc lập từng bước như `--only-nodes`, `--only-bao-gom`, `--only-status-rels`, `--only-inferred-rels`, `--only-tvpl`, `--only-luoc-do-export`.
* **Cấu hình Kết nối & Môi trường**:
  * Đọc biến cấu hình môi trường để trỏ tới driver Neo4j tương ứng (`NEO4J_DEV` hoặc `NEO4J_PROD`) và database đích tương ứng (mặc định là `neo4j`).
  * Ghi nhận collection lưu kết quả trung gian trong MongoDB qua biến `MONGO_EXTRACTION_COLLECTION` hoặc cấu hình mặc định trong tệp `.env`.
* **Phân lô & Song song hóa**:
  * Tiếp nhận đường dẫn tệp chứa danh sách ID văn bản cần xử lý (mặc định `data/all_ids.json`).
  * Cung cấp cơ chế phân luồng song song thông qua cờ `--parallel-workers` (mặc định khởi tạo 8 luồng song song) hoặc tuần tự bằng `--no-parallel`.
  * Nhận batch size cấu hình riêng biệt cho từng pha xử lý cụ thể như `--node-batch-size`, `--structural-rel-batch-size`, `--status-rel-batch-size`, `--inferred-rel-batch-size`, `--tvpl-batch-size`, `--luoc-do-batch-size` (tất cả mặc định là 500).
* **Quản lý Checkpoint**: CLI cung cấp cờ `--clear-checkpoint` và `--checkpoint-suffix` giúp khởi tạo lại tệp lưu vết checkpoint nằm tại đường dẫn `logs/checkpoints/` nhằm kiểm soát trạng thái chạy lại khi cập nhật tập dữ liệu khác nhau.

#### Chi tiết L & M (BuildGraphApp & Neo4j Database)
`BuildGraphApp` (L) là trái tim điều phối việc chuyển dịch cơ sở dữ liệu từ dạng tài liệu MongoDB sang cơ sở dữ liệu đồ thị Neo4j (M), thực thi tuần tự qua các giai đoạn chi tiết sau:

##### Bước 1: Khởi tạo nút & bao_gom (Build Nodes & BAO_GOM)
* **Tối ưu hóa Combined Single-Scan**:
  * Khi cả hai pha tạo nút và tạo quan hệ `bao_gom` đều được kích hoạt, `BuildGraphApp` sẽ gọi phương thức kết hợp `build_nodes_and_bao_gom` của `LegalKnowledgeGraphBuilder`.
  * Thay vì thực hiện quét MongoDB hai lần (một lần tải tài liệu để tạo nút, một lần tải tài liệu để liên kết cạnh `bao_gom`), hệ thống chỉ thực hiện một lần duyệt duy nhất. Trong mỗi lô (batch), tài liệu được đọc lên, giải nén trường nhị phân `cls_parsing` bằng `gzip` và chuyển dịch đồng thời sang cả hai danh sách tham số: `doc_params` (cho nút VAN_BAN), `term_params` (cho nút DIEU_KHOAN) và `rel_params` (cho cạnh bao_gom).
* **Phân trang MongoDB bằng so sánh khóa**:
  * Sử dụng câu lệnh tìm kiếm: `{"cls_ID": {"$gt": last_processed_id}}` sắp xếp tăng dần theo `cls_ID`. Nhờ có chỉ mục (Index) trên trường `cls_ID`, MongoDB trả về dữ liệu nhanh chóng mà không gặp lỗi nghẽn hiệu năng như toán tử `skip/limit` khi duyệt qua các tập tài liệu lớn hàng trăm nghìn bản ghi.
* **Sao chép và Nhân bản siêu dữ liệu (Property Inheritance)**:
  * Trong hàm `prepare_nodes_from_document` của `NodePreparationService`, khi tạo tham số cho nút `DIEU_KHOAN` (khóa ID độc bản dạng `"{com_key}#{cls_ID}"`), toàn bộ các thuộc tính siêu dữ liệu của văn bản cha `VAN_BAN` (bao gồm `so_hieu`, `loai_van_ban`, `ngay_ban_hanh`, `ngay_co_hieu_luc`, `tinh_trang_hieu_luc`, `co_quan_ban_hanh`) được sao chép trực tiếp vào thuộc tính của nút `DIEU_KHOAN` con đó.
  * *Mục đích*: Loại bỏ các liên kết `MATCH` ngược lên nút văn bản cha khi viết các truy vấn tìm kiếm nghiệp vụ của API, cho phép tra cứu trực tiếp thông tin hiệu lực ngay trên nút điều khoản với thời gian phản hồi giảm thiểu tối đa.
* **Cơ chế ghi lô Neo4j & Thử lại lũy thừa (Exponential Backoff Jitter Retry)**:
  * Việc tạo nút sử dụng các câu lệnh Cypher ghi lô truyền qua driver Neo4j:
    * *Tạo VAN_BAN*:
      ```cypher
      UNWIND $props_list AS props
      MERGE (q:VAN_BAN {ID: props.ID})
      SET q = props
      ```
    * *Tạo DIEU_KHOAN*:
      ```cypher
      UNWIND $props_list AS props
      MERGE (q:DIEU_KHOAN {ID: props.ID})
      SET q = props
      ```
    * *Tạo quan hệ bao_gom*:
      ```cypher
      UNWIND $rel_list AS rel
      MATCH (a {ID: rel.head_ID}) WHERE a:VAN_BAN OR a:DIEU_KHOAN
      MATCH (b:DIEU_KHOAN {ID: rel.tail_ID})
      MERGE (a)-[r:bao_gom]->(b)
      SET r.thoi_gian_cap_nhat = rel.thoi_gian_cap_nhat, r.nguon_cap_nhat = rel.nguon_cap_nhat
      ```
  * Khi thực thi đa luồng ghi song song (với 8 workers), Neo4j thường xuyên trả về lỗi khóa giao dịch (Deadlock) hoặc xung đột ghi chỉ mục (`IndexEntryConflictException`). Hàm ghi `_execute_with_retry` của `Neo4jRepository` sẽ bắt các ngoại lệ này và thực hiện thử lại tối đa 5 lần. Thời gian chờ tăng dần theo lũy thừa kết hợp giá trị nhiễu ngẫu nhiên (Jitter) nhằm tránh xung đột đồng thời giữa các thread ghi:
    $$\text{delay} = \text{base\_delay} \times 2^{\text{attempt}} + \text{random}(0, 1)$$
    Với $\text{base\_delay} = 1.0$ giây.

##### Bước 2: Tạo quan hệ trực tiếp (Build Semantic Status Relationships)
* **Dọn dẹp mối quan hệ cũ (Deletion Pass)**:
  * Trước khi chèn quan hệ nghiệp vụ trực tiếp (như `sua_doi`, `thay_the`, `bai_bo`, `can_cu`, `dan_chieu`), hệ thống chạy lệnh Cypher xóa sạch các cạnh nghiệp vụ hướng ra cũ của tập ID đang xử lý để tránh rác dữ liệu:
    ```cypher
    CALL {
      MATCH (source:VAN_BAN)-[r]->(target)
      WHERE source.ID IN $ids AND type(r) <> 'bao_gom'
      DELETE r
    } IN TRANSACTIONS OF 1000 ROWS
    ```
* **APOC Merge Nodes & Tự sửa chữa nút ảo biến thể**:
  * Khi chèn quan hệ nghiệp vụ, hệ thống sử dụng câu lệnh Cypher tối ưu thông qua thư viện APOC: `bulk_upsert_for_status_relations`. Lệnh này xử lý tình huống đặc biệt khi nút nguồn hoặc nút đích chưa được tạo trên đồ thị (do tài liệu đó chưa được nạp).
  * Truy vấn APOC tự động thực hiện tạo nút ảo (chế độ tự sửa chữa - auto-heal) và tìm kiếm xem có nút điều khoản biến thể nào tương thích đã tồn tại (dạng nút được thêm do sửa đổi bổ sung chứa tiền tố `_dk_` hoặc `_bosung_` kết thúc bằng dấu `#` và ID cha):
    ```cypher
    UNWIND $rel_list AS rel
    // Đảm bảo nút nguồn tồn tại
    CALL apoc.merge.node([rel.head_class], {ID: rel.head_ID}) YIELD node as a
    
    // Làm giàu nút nguồn ảo nếu nó là nút skeleton (chỉ chứa ID)
    WITH rel, a, size(keys(a)) AS k_a, split(toString(rel.head_ID), '#') AS parts_head
    OPTIONAL MATCH (a_var:DIEU_KHOAN)
    WHERE k_a <= 1 AND size(parts_head) > 1 
      AND (a_var.ID STARTS WITH (parts_head[0] + '_dk_') OR a_var.ID STARTS WITH (parts_head[0] + '_bosung_'))
      AND a_var.ID ENDS WITH ('#' + parts_head[1])
    WITH rel, a, collect(a_var) AS a_vars
    CALL apoc.do.when(
        size(a_vars) > 0,
        'SET a += apoc.map.clean(properties(a_vars[0]), ["ID"], []) RETURN a',
        'RETURN a',
        {a: a, a_vars: a_vars}
    ) YIELD value AS a_val
    WITH rel, a_val.a AS a
    
    // Đảm bảo nút đích tồn tại
    CALL apoc.merge.node([rel.tail_class], {ID: rel.tail_ID}) YIELD node as b
    ...
    // Tạo quan hệ nghiệp vụ động bằng APOC
    CALL apoc.merge.relationship(a, rel.rel_type, {}, coalesce(rel.rel_props, {}), b, coalesce(rel.rel_props, {})) YIELD rel as r
    SET r += coalesce(rel.rel_props, {})
    ```
* **Tự Động Tạo Nút Điều Khoản Ảo Bổ Sung**:
  * Nếu văn bản A bổ sung một điều khoản mới B vào văn bản C (ví dụ: bổ sung Điều 12a vào văn bản C), điều khoản 12a này ban đầu không tồn tại trong cấu trúc cây nguyên bản của C.
  * `StatusRelationshipPreparationService` kiểm tra danh mục các điều khoản hiện hữu của C. Nếu `target_key` không trùng khớp với bất kỳ khóa nào có sẵn:
    1. Đọc nội dung văn bản gốc điều khoản bổ sung từ MongoDB, dùng Regex tìm đoạn văn bản nằm giữa hai dấu nháy kép để làm trường `noi_dung` cho Điều 12a mới.
    2. Tạo nút ảo `DIEU_KHOAN` cho Điều 12a trên đồ thị.
    3. Thực hiện liên kết Điều 12a ảo này ngược lên cây phân cấp của văn bản C bằng quan hệ ảo đặc biệt `bao_gom_sau_bo_sung`, bảo vệ cây phân cấp đồ thị không bị đứt gãy.
* **Xử lý Xung Đột Trùng Cạnh (`CONFLICT_RELATION_PRIORITY`)**:
  * Nhằm tránh nhiễu thông tin, hệ thống định nghĩa bộ lọc xung đột quan hệ. Nếu xuất hiện nhiều quan hệ hành động giữa cùng một nguồn và đích (ví dụ: vừa sửa đổi vừa thay thế), hệ thống sắp xếp theo nhóm ưu tiên: Sửa đổi/Bổ sung (ưu tiên cao nhất) → Thay thế → Bãi bỏ → Hủy bỏ (ưu tiên thấp nhất) để chỉ giữ lại quan hệ mạnh nhất.

##### Bước 3: Suy luận quan hệ gián tiếp VB-VB (Build Inferred Document Relationships)
* **Tổng hợp quan hệ**:
  * `InferredRelationshipService` đọc các quan hệ cấp điều khoản lưu trong trường `cls_graph.success` của MongoDB.
  * Loại bỏ các liên kết trỏ tới các thực thể có cấu trúc vĩ mô của văn bản đích như chương, phần, mục.
  * Sử dụng lớp `RelationTransformer` dịch các khóa điều khoản tiếng Anh (ví dụ: `khoan_2_dieu_3`) thành tên hiển thị tiếng Việt chuẩn ("Khoản 2 Điều 3").
  * Gom các liên kết cấp điều khoản của cặp văn bản thành một mối liên kết duy nhất cấp văn bản.
* **Tạo câu chứng cứ**:
  * Gom nhóm các hành động và sinh chuỗi văn bản làm chứng cứ kết nối đồ thị (thuộc tính `description`). Ví dụ: "Khoản 2 Điều 3 sửa đổi Khoản 1 Điều 5; Điểm a Khoản 3 Điều 3 bãi bỏ Khoản 2 Điều 6".
* **Ghi đĩa Neo4j**:
  * Xóa các quan hệ gián tiếp cũ trên Neo4j (được nhận diện qua thuộc tính `loai_quan_he = 'gian_tiep'`).
  * Gọi `bulk_create_multiple_relationships` để tạo cạnh gián tiếp trên đồ thị. Các mảng dữ liệu nghiệp vụ như danh sách ID liên quan (`danh_sach_id_lien_quan`) và các mối quan hệ gốc cấp điều khoản (`moi_quan_he_goc`) được chuyển thành dạng chuỗi JSON thô để Neo4j lưu trữ ổn định.

##### Bước 4: Hòa nhập quan hệ TVPL (Build TVPL Relations - Optional)
* **Lọc Nguồn**: `TVPLRelationshipService` quét trường `cls_luoc_do` của các tài liệu trong MongoDB, lọc chỉ lấy các mối quan hệ lịch sử có trường `source == 'tvpl'`.
* **Ánh xạ & Đảo chiều quan hệ theo `REVERSED_RELATIONS`**:
  * Nhãn quan hệ của TVPL được ánh xạ sang nhãn chuẩn Neo4j. Để giữ hướng mũi tên đồ thị nhất quán luôn đi từ tài liệu mới tới tài liệu cũ (ví dụ: Mới-[thay_the]->Cũ), hệ thống tra cứu bảng cấu hình `REVERSED_RELATIONS`:
    * *Các quan hệ cần đảo chiều* (mã cấu hình `True`): `van_ban_thay_the`, `van_ban_huong_dan`, `van_ban_sua_doi_bo_sung`, `van_ban_dinh_chinh`, `van_ban_hop_nhat`, `van_ban_quy_dinh_chi_tiet`, `van_ban_bai_bo`, `van_ban_dinh_chi`, `van_ban_huy_bo`, `van_ban_keo_dai_hieu_luc`, `van_ban_ngung_hieu_luc`.
      Khi chèn vào Neo4j, hệ thống sẽ đảo ngược vị trí nguồn và đích: Thiết lập `head_ID = related_doc_id` và `tail_ID = cls_ID`.
    * *Các quan hệ giữ nguyên chiều* (mã cấu hình `False`): `van_ban_bi_thay_the`, `van_ban_duoc_huong_dan`, `van_ban_duoc_sua_doi_bo_sung`, `van_ban_bi_dinh_chinh`, `van_ban_duoc_hop_nhat`, `van_ban_bi_bai_bo`, `van_ban_bi_dinh_chi`, `van_ban_bi_huy_bo`, `van_ban_duoc_quy_dinh_chi_tiet`, `van_ban_duoc_keo_dai_hieu_luc`, `van_ban_bi_ngung_hieu_luc`, `van_ban_can_cu`, `van_ban_dan_chieu`.
      Thiết lập `head_ID = cls_ID` và `tail_ID = related_doc_id`.
* **Priority Guard (Luật bảo vệ độ ưu tiên)**:
  * Để ngăn chặn dữ liệu TVPL (vốn được nhập thủ công và có thể không đồng bộ) đè lên dữ liệu trích xuất tự động bằng thuật toán chuẩn xác của CMCAI, câu lệnh Cypher chèn TVPL sử dụng `OPTIONAL MATCH` để kiểm tra sự tồn tại của quan hệ cùng loại từ nguồn `cmcai`:
    ```cypher
    UNWIND $rel_list AS rel
    MATCH (a:VAN_BAN {ID: rel.head_ID})
    MATCH (b:VAN_BAN {ID: rel.tail_ID})
    OPTIONAL MATCH (a)-[r]->(b)
    WHERE type(r) = rel.rel_type AND r.nguon_cap_nhat = 'cmcai'
    WITH rel, a, b, r
    // Chỉ chèn quan hệ TVPL nếu r IS NULL (không có quan hệ cmcai tương đương)
    CALL apoc.do.when(
        r IS NULL,
        'MERGE (a)-[new_r:REL_TYPE]->(b) SET new_r.nguon_cap_nhat = "tvpl", new_r.thoi_gian_cap_nhat = timestamp RETURN new_r',
        'RETURN r',
        {a:a, b:b, rel_type:rel.rel_type, timestamp:rel.thoi_gian_cap_nhat}
    ) YIELD value
    RETURN count(*)
    ```

##### Bước 5: Làm giàu thuộc tính nút ảo (Enrich Skeleton Metadata)
* **Định vị nút ảo**: Quét đồ thị tìm các nút `VAN_BAN` hoặc `DIEU_KHOAN` chỉ có ID và không có thuộc tính (do hệ thống tự động sinh trong quá trình merge quan hệ ở Bước 2 và Bước 4 khi tài liệu đích chưa được nạp chính thức). Các nút này được nhận diện qua điều kiện `size(keys(node)) <= 1`.
* **Làm giàu nút VAN_BAN**:
  * Gom danh sách ID của các nút `VAN_BAN` ảo.
  * Truy vấn MongoDB `cls_ver2` theo lô lấy siêu dữ liệu chính xác và gọi hàm `bulk_upsert_nodes` cập nhật thuộc tính lên Neo4j.
* **Làm giàu nút DIEU_KHOAN (DIEU_KHOAN Enrichment)**:
  1. Tách chuỗi khóa ID của các nút `DIEU_KHOAN` ảo (định dạng `"{com_key}#{parent_id}"`) để xác định ID văn bản cha (`parent_id`).
  2. Gom nhóm danh sách các điều khoản ảo theo `parent_id`.
  3. Truy vấn các tài liệu cha từ MongoDB `cls_ver2`, giải nén cấu trúc cây điều khoản nhị phân trong `cls_parsing` bằng `gzip`.
  4. Ánh xạ các điều khoản của tài liệu cha thành một từ điển (dictionary) để tìm kiếm nhanh với độ phức tạp $O(1)$ thay vì duyệt tuần tự $O(n)$.
  5. Đối chiếu tìm kiếm điều khoản trùng khớp chính xác (Exact Match) hoặc trùng khớp biến thể (Variant Match - dùng cho các nút ảo được chèn bổ sung có hậu tố `_dk_` hoặc `_bosung_`).
  6. Với khớp biến thể, hệ thống sao chép thuộc tính của nút điều khoản gốc gần nhất, sửa lại trường `ID` tương khớp và gửi mảng dữ liệu hoàn chỉnh lên Neo4j để làm giàu nút.

##### Bước 6: Đồng bộ ngược lược đồ cls_luoc_do (Export to Luoc Do MongoDB)
* **Truy vấn quan hệ hai chiều**:
  * Lớp `Neo4jToLuocDoPreparation` chia danh sách ID văn bản thành các lô 5.000 phần tử.
  * Thực hiện câu truy vấn Cypher kết hợp toán tử `UNION` để lấy ra tất cả các cạnh nghiệp vụ đi ra (outbound) và đi vào (inbound) liên quan đến danh sách ID trong lô (loại bỏ quan hệ cấu trúc `bao_gom`):
    ```cypher
    MATCH (head:VAN_BAN)-[r]->(tail:VAN_BAN)
    WHERE type(r) <> 'bao_gom' AND head.ID IN $ids
    RETURN head.ID AS head_id, tail.ID AS tail_id, type(r) AS rel_type, r.nguon_cap_nhat AS source
    UNION
    MATCH (head:VAN_BAN)-[r]->(tail:VAN_BAN)
    WHERE type(r) <> 'bao_gom' AND tail.ID IN $ids
    RETURN head.ID AS head_id, tail.ID AS tail_id, type(r) AS rel_type, r.nguon_cap_nhat AS source
    ```
* **Phân loại vai trò (HEAD/TAIL)**:
  * Hệ thống duyệt qua từng kết quả trả về. Nếu ID tài liệu đang xét trùng khớp với `head_id` (đầu cạnh - thực hiện hành động), hệ thống tra cứu bảng ánh xạ `rel_mapping_head` để ghi nhận thông tin vào trường bị động (ví dụ: đầu cạnh của mối quan hệ `thay_the` → ghi vào danh sách `van_ban_bi_thay_the` của văn bản ở đuôi).
  * Ngược lại, nếu ID trùng với `tail_id` (đuôi cạnh - nhận hành động), hệ thống tra cứu bảng `rel_mapping_tail` để ghi nhận vào trường chủ động (ví dụ: đuôi cạnh của `thay_the` → ghi vào danh sách `van_ban_thay_the` của văn bản hiện tại).
* **Ghi lô PyMongo**:
  * Các mối quan hệ sau khi phân loại được gom nhóm theo ID văn bản, đóng gói kèm nhãn thời gian cập nhật `updated_at`.
  * Khởi tạo mảng các câu lệnh `UpdateOne` với cờ `upsert=True` và thực thi ghi đồng loạt xuống MongoDB `ie_collection` bằng phương thức `bulk_write`.

---

### 2. Chi Tiết Pha 2: Xây Dựng Đồ Thị Tri Thức (Neo4j Graph Building)

#### Chi tiết K (build_graph.py)
* **Quản lý tham số**: Sử dụng bộ thư viện `argparse` để phân tích tham số dòng lệnh phong phú. Nó nhận diện các cờ chạy độc lập từng bước như `--only-nodes`, `--only-bao-gom`, `--only-status-rels`, `--only-inferred-rels`, `--only-tvpl`, `--only-luoc-do-export`.
* **Cấu hình Kết nối & Môi trường**:
  * Đọc biến cấu hình môi trường để trỏ tới driver Neo4j tương ứng (`NEO4J_DEV` hoặc `NEO4J_PROD`) và database đích tương ứng (mặc định là `neo4j`).
  * Ghi nhận collection lưu kết quả trung gian trong MongoDB qua biến `MONGO_EXTRACTION_COLLECTION` hoặc cấu hình mặc định trong tệp `.env`.
* **Phân lô & Song song hóa**:
  * Tiếp nhận đường dẫn tệp chứa danh sách ID văn bản cần xử lý (mặc định `data/all_ids.json`).
  * Cung cấp cơ chế phân luồng song song thông qua cờ `--parallel-workers` (mặc định khởi tạo 8 luồng song song) hoặc tuần tự bằng `--no-parallel`.
  * Nhận batch size cấu hình riêng biệt cho từng pha xử lý cụ thể như `--node-batch-size`, `--structural-rel-batch-size`, `--status-rel-batch-size`, `--inferred-rel-batch-size`, `--tvpl-batch-size`, `--luoc-do-batch-size` (tất cả mặc định là 500).
* **Quản lý Checkpoint**: CLI cung cấp cờ `--clear-checkpoint` và `--checkpoint-suffix` giúp khởi tạo lại tệp lưu vết checkpoint nằm tại đường dẫn `logs/checkpoints/` nhằm kiểm soát trạng thái chạy lại khi cập nhật tập dữ liệu khác nhau.

#### Chi tiết L (BuildGraphApp)
* **Orchestration**: Là lớp điều phối chính chịu trách nhiệm quản lý vòng đời chạy 6 bước của Pha 2.
* **Quy trình tuần tự & Phân luồng công việc**:
  1. Kiểm tra cấu hình và các cờ chạy để xác định các bước sẽ thực thi.
  2. Nạp danh sách `doc_ids` cần xử lý từ tệp cấu hình JSON hoặc từ database.
  3. Phân chia luồng xử lý song song thông qua `ThreadPoolExecutor` dựa trên số lượng `parallel_workers` (mặc định 8 luồng).
  4. Lần lượt gọi các dịch vụ chuyên biệt tương ứng với từng bước (các thành phần từ N đến V) để ghi nhận dữ liệu vào Neo4j.
  5. Đóng và giải phóng kết nối driver Neo4j một cách an toàn sau khi hoàn tất.

#### Chi tiết M (Neo4j Graph Database)
* **Cơ chế lưu trữ**: Lưu trữ cấu trúc đồ thị gồm các nhãn nút chính `VAN_BAN`, `DIEU_KHOAN` và các loại quan hệ `bao_gom` (cạnh cấu trúc), `sua_doi`, `thay_the`, `bai_bo`, `can_cu`, `dan_chieu` (cạnh nghiệp vụ trực tiếp), `gian_tiep` (cạnh nghiệp vụ suy luận).
* **Cơ chế ghi lô Neo4j**: Sử dụng câu lệnh Cypher ghi lô truyền qua driver Neo4j để tối ưu hóa hiệu năng, giảm thiểu số lượng giao dịch (transactions).
* **Xử lý xung đột ghi chỉ mục & Deadlock (Exponential Backoff Jitter Retry)**:
  * Khi thực thi đa luồng ghi song song, Neo4j thường xuyên gặp lỗi khóa giao dịch (Deadlock) hoặc xung đột ghi chỉ mục (`IndexEntryConflictException`). Hàm ghi `_execute_with_retry` của `Neo4jRepository` bắt các ngoại lệ này và thực hiện thử lại tối đa 5 lần. Thời gian chờ tăng dần theo lũy thừa kết hợp giá trị nhiễu ngẫu nhiên (Jitter) nhằm tránh xung đột đồng thời giữa các thread ghi:
    $$\text{delay} = \text{base\_delay} \times 2^{\text{attempt}} + \text{random}(0, 1)$$
    Với $\text{base\_delay} = 1.0$ giây.
* **APOC dynamic merges**: Sử dụng thư viện APOC (`apoc.merge.node` và `apoc.merge.relationship`) để hỗ trợ tạo nút động và chèn các kiểu quan hệ biến thiên theo dữ liệu đầu vào.

#### Chi tiết N (LegalKnowledgeGraphBuilder)
* **Đóng vai trò chính trong Bước 1 & Bước 5**:
* **Tối ưu hóa Combined Single-Scan (Bước 1)**:
  * Khi cả hai bước tạo nút và tạo quan hệ `bao_gom` đều được kích hoạt, builder gọi phương thức kết hợp `build_nodes_and_bao_gom`.
  * Thay vì quét MongoDB hai lần, hệ thống chỉ thực hiện một lần duyệt duy nhất. Trong mỗi lô (batch), tài liệu được đọc lên, giải nén trường nhị phân `cls_parsing` bằng `gzip` và chuyển dịch đồng thời sang cả hai danh sách tham số: `doc_params` (cho nút VAN_BAN), `term_params` (cho nút DIEU_KHOAN) và `rel_params` (cho cạnh bao_gom).
* **Phân trang MongoDB bằng so sánh khóa**:
  * Sử dụng câu lệnh tìm kiếm: `{"cls_ID": {"$gt": last_processed_id}}` sắp xếp tăng dần theo `cls_ID`. Nhờ có chỉ mục (Index) trên trường `cls_ID`, MongoDB trả về dữ liệu nhanh chóng mà không gặp lỗi nghẽn hiệu năng như toán tử `skip/limit` khi duyệt qua các tập tài liệu lớn hàng trăm nghìn bản ghi.
* **Làm giàu nút ảo (Step 5)**:
  * Quét đồ thị tìm các nút `VAN_BAN` hoặc `DIEU_KHOAN` chỉ có ID và không có thuộc tính (do hệ thống tự động sinh trong quá trình merge quan hệ ở Bước 2 và Bước 4 khi tài liệu đích chưa được nạp chính thức). Các nút này được nhận diện qua điều kiện `size(keys(node)) <= 1`.
  * Gom danh sách ID của các nút `VAN_BAN` ảo, truy vấn MongoDB `cls_ver2` theo lô lấy siêu dữ liệu chính xác và gọi hàm `bulk_upsert_nodes` cập nhật thuộc tính lên Neo4j.
  * Với nút `DIEU_KHOAN` ảo (định dạng ID `"{com_key}#{parent_id}"`), builder tách chuỗi để xác định ID văn bản cha, gom nhóm theo `parent_id`, truy vấn các tài liệu cha từ MongoDB, giải nén cấu trúc cây điều khoản nhị phân trong `cls_parsing` bằng `gzip`.
  * Ánh xạ các điều khoản của tài liệu cha thành một từ điển để tìm kiếm nhanh với độ phức tạp $O(1)$ thay vì duyệt tuần tự. Đối chiếu tìm kiếm điều khoản trùng khớp chính xác (Exact Match) hoặc trùng khớp biến thể (Variant Match - dùng cho các nút ảo được chèn bổ sung có hậu tố `_dk_` hoặc `_bosung_`). Với khớp biến thể, builder sao chép thuộc tính của nút điều khoản gốc gần nhất, sửa lại trường `ID` tương khớp và gửi mảng dữ liệu hoàn chỉnh lên Neo4j để làm giàu nút.

#### Chi tiết O (NodePreparationService)
* **Chuẩn bị tham số nút**: Chịu trách nhiệm chuyển đổi cấu trúc cây điều khoản JSON từ MongoDB sang dạng danh sách thuộc tính phẳng tương thích với các nút Neo4j.
* **Sao chép và Nhân bản siêu dữ liệu (Property Inheritance)**:
  * Trong hàm `prepare_nodes_from_document`, khi tạo tham số cho nút `DIEU_KHOAN`, toàn bộ các thuộc tính siêu dữ liệu của văn bản cha `VAN_BAN` (bao gồm `so_hieu`, `loai_van_ban`, `ngay_ban_hanh`, `ngay_co_hieu_luc`, `tinh_trang_hieu_luc`, `co_quan_ban_hanh`) được sao chép trực tiếp vào thuộc tính của nút `DIEU_KHOAN` con đó.
  * *Mục đích*: Loại bỏ các liên kết `MATCH` ngược lên nút văn bản cha khi viết các truy vấn tìm kiếm nghiệp vụ của API, cho phép tra cứu trực tiếp thông tin hiệu lực ngay trên nút điều khoản với thời gian phản hồi giảm thiểu tối đa.

#### Chi tiết P (Mongo PROD: cls_ver2)
* **Ý nghĩa & Cấu trúc**: (Tương tự thành phần D ở Pha 1) Cung cấp dữ liệu gốc để khởi tạo và bổ sung thông tin cho các nút đồ thị, chứa trường nhị phân `cls_parsing` được nén bằng `gzip`.

#### Chi tiết Q (StatusRelationshipPreparationService)
* **Mục đích**: Chuẩn bị các tham số cho quan hệ trạng thái/nghiệp vụ từ trường dữ liệu `cls_graph` trích xuất được ở Pha 1.
* **Tự Động Tạo Nút Điều Khoản Ảo Bổ Sung**:
  * Nếu văn bản A bổ sung một điều khoản mới B vào văn bản C (ví dụ: bổ sung Điều 12a vào văn bản C), điều khoản 12a này ban đầu không tồn tại trong cấu trúc cây nguyên bản của C.
  * Dịch vụ kiểm tra danh mục các điều khoản hiện hữu của C. Nếu `target_key` không trùng khớp với bất kỳ khóa nào có sẵn:
    1. Đọc nội dung văn bản gốc điều khoản bổ sung từ MongoDB, dùng Regex tìm đoạn văn bản nằm giữa hai dấu nháy kép để làm trường `noi_dung` cho Điều 12a mới.
    2. Tạo nút ảo `DIEU_KHOAN` cho Điều 12a trên đồ thị.
    3. Thực hiện liên kết Điều 12a ảo này ngược lên cây phân cấp của văn bản C bằng quan hệ ảo đặc biệt `bao_gom_sau_bo_sung`, bảo vệ cây phân cấp đồ thị không bị đứt gãy.
* **Xử lý Xung Đột Trùng Cạnh (`CONFLICT_RELATION_PRIORITY`)**:
  * Nhằm tránh nhiễu thông tin, hệ thống định nghĩa bộ lọc xung đột quan hệ. Nếu xuất hiện nhiều quan hệ hành động giữa cùng một nguồn và đích (ví dụ: vừa sửa đổi vừa thay thế), hệ thống sắp xếp theo nhóm ưu tiên: Sửa đổi/Bổ sung (ưu tiên cao nhất) → Thay thế → Bãi bỏ → Hủy bỏ (ưu tiên thấp nhất) để chỉ giữ lại quan hệ mạnh nhất.

#### Chi tiết R (GraphRelationshipWriteCoordinator)
* **Cơ Chế Ghi An Toàn (Write Safety Mode)**:
  * Để bảo vệ tính toàn vẹn của đồ thị và tránh việc chèn các quan hệ lỗi lên các nút ảo trống rỗng, coordinator hoạt động ở chế độ mặc định `strict-auto-heal`:
    1. Khi cố gắng ghi quan hệ giữa nút nguồn và nút đích, nếu phát hiện nút đích chưa tồn tại trên Neo4j, hệ thống sẽ kích hoạt đối tượng tự sửa chữa `S (GraphNodeAutoHealer)`.
    2. `GraphNodeAutoHealer` thực hiện truy vấn trực tiếp thông tin cấu trúc của nút đích từ MongoDB, giải nén dữ liệu và tự động tạo nút đích cùng toàn bộ phân cấp cha-con của nó trên Neo4j.
    3. Sau khi nút đích được tự động phục hồi chính xác, coordinator tiến hành thực thi lại lệnh chèn quan hệ ban đầu.
    4. Toàn bộ tiến trình tự sửa chữa và các lỗi tham chiếu hỏng (nút đích không tồn tại cả trong MongoDB) được ghi lại chi tiết vào tệp báo cáo `reports/graph_write_audit.json` và `reports/graph_write_audit_detail.ndjson`.
* **APOC Merge Nodes & Tự sửa chữa nút ảo biến thể**:
  * Khi chèn quan hệ nghiệp vụ, coordinator sử dụng câu lệnh Cypher tối ưu thông qua thư viện APOC: `bulk_upsert_for_status_relations`. Lệnh này xử lý tình huống đặc biệt khi nút nguồn hoặc nút đích chưa được tạo trên đồ thị (do tài liệu đó chưa được nạp).
  * Truy vấn APOC tự động thực hiện tạo nút ảo (chế độ tự sửa chữa - auto-heal) và tìm kiếm xem có nút điều khoản biến thể nào tương thích đã tồn tại (dạng nút được thêm do sửa đổi bổ sung chứa tiền tố `_dk_` hoặc `_bosung_` kết thúc bằng dấu `#` và ID cha):
    ```cypher
    UNWIND $rel_list AS rel
    // Đảm bảo nút nguồn tồn tại
    CALL apoc.merge.node([rel.head_class], {ID: rel.head_ID}) YIELD node as a
    
    // Làm giàu nút nguồn ảo nếu nó là nút skeleton (chỉ chứa ID)
    WITH rel, a, size(keys(a)) AS k_a, split(toString(rel.head_ID), '#') AS parts_head
    OPTIONAL MATCH (a_var:DIEU_KHOAN)
    WHERE k_a <= 1 AND size(parts_head) > 1 
      AND (a_var.ID STARTS WITH (parts_head[0] + '_dk_') OR a_var.ID STARTS WITH (parts_head[0] + '_bosung_'))
      AND a_var.ID ENDS WITH ('#' + parts_head[1])
    WITH rel, a, collect(a_var) AS a_vars
    CALL apoc.do.when(
        size(a_vars) > 0,
        'SET a += apoc.map.clean(properties(a_vars[0]), ["ID"], []) RETURN a',
        'RETURN a',
        {a: a, a_vars: a_vars}
    ) YIELD value AS a_val
    WITH rel, a_val.a AS a
    
    // Đảm bảo nút đích tồn tại
    CALL apoc.merge.node([rel.tail_class], {ID: rel.tail_ID}) YIELD node as b
    ...
    // Tạo quan hệ nghiệp vụ động bằng APOC
    CALL apoc.merge.relationship(a, rel.rel_type, {}, coalesce(rel.rel_props, {}), b, coalesce(rel.rel_props, {})) YIELD rel as r
    SET r += coalesce(rel.rel_props, {})
    ```

#### Chi tiết S (GraphNodeAutoHealer)
* **Tự sửa chữa cấu trúc**: Được coordinator (R) gọi khi gặp lỗi thiếu nút đích.
* **Cơ chế hoạt động**:
  1. Nhận ID văn bản đích bị thiếu.
  2. Truy vấn trực tiếp MongoDB `P` để lấy dữ liệu parsing và info của tài liệu đó.
  3. Sử dụng `NodePreparationService` để phân tích cấu trúc cây điều khoản.
  4. Thực hiện lệnh ghi lô để tạo ngay lập tức các nút `VAN_BAN`, `DIEU_KHOAN` và các cạnh `bao_gom` tương ứng trên đồ thị Neo4j.
  5. Giúp bảo vệ luồng ghi chính không bị đứt gãy, đảm bảo tính nhất quán tham chiếu trên đồ thị.

#### Chi tiết T (InferredRelationshipService)
* **Mục đích**: Tổng hợp các mối quan hệ nghiệp vụ trực tiếp cấp điều khoản để sinh quan hệ gián tiếp cấp văn bản (Văn bản tới Văn bản).
* **Thuật toán & Quy trình**:
  1. Đọc các quan hệ từ MongoDB của tài liệu đang xử lý.
  2. Loại bỏ các liên kết trỏ tới các thực thể có cấu trúc vĩ mô của văn bản đích như chương, phần, mục.
  3. Sử dụng lớp `RelationTransformer` dịch các khóa điều khoản tiếng Anh (ví dụ: `khoan_2_dieu_3`) thành tên hiển thị tiếng Việt chuẩn ("Khoản 2 Điều 3").
  4. Gom các liên kết cấp điều khoản của cặp văn bản thành một mối liên kết duy nhất cấp văn bản.
  5. Gom nhóm các hành động và sinh chuỗi văn bản làm chứng cứ kết nối đồ thị (thuộc tính `description`). Ví dụ: "Khoản 2 Điều 3 sửa đổi Khoản 1 Điều 5; Điểm a Khoản 3 Điều 3 bãi bỏ Khoản 2 Điều 6".
  6. Xóa các quan hệ gián tiếp cũ trên Neo4j (được nhận diện qua thuộc tính `loai_quan_he = 'gian_tiep'`).
  7. Gọi `bulk_create_multiple_relationships` để tạo cạnh gián tiếp trên đồ thị. Các mảng dữ liệu nghiệp vụ như danh sách ID liên quan (`danh_sach_id_lien_quan`) và các mối quan hệ gốc cấp điều khoản (`moi_quan_he_goc`) được chuyển thành dạng chuỗi JSON thô để Neo4j lưu trữ ổn định.

#### Chi tiết U (TVPLRelationshipService)
* **Lọc Nguồn**: Quét trường `cls_luoc_do` của các tài liệu trong MongoDB, lọc chỉ lấy các mối quan hệ lịch sử có trường `source == 'tvpl'`.
* **Ánh xạ & Đảo chiều quan hệ theo `REVERSED_RELATIONS`**:
  * Nhãn quan hệ của TVPL được ánh xạ sang nhãn chuẩn Neo4j. Để giữ hướng mũi tên đồ thị nhất quán luôn đi từ tài liệu mới tới tài liệu cũ (ví dụ: Mới-[thay_the]->Cũ), hệ thống tra cứu bảng cấu hình `REVERSED_RELATIONS`:
    * *Các quan hệ cần đảo chiều* (mã cấu hình `True`): `van_ban_thay_the`, `van_ban_huong_dan`, `van_ban_sua_doi_bo_sung`, `van_ban_dinh_chinh`, `van_ban_hop_nhat`, `van_ban_quy_dinh_chi_tiet`, `van_ban_bai_bo`, `van_ban_dinh_chi`, `van_ban_huy_bo`, `van_ban_keo_dai_hieu_luc`, `van_ban_ngung_hieu_luc`.
      Khi chèn vào Neo4j, hệ thống sẽ đảo ngược vị trí nguồn và đích: Thiết lập `head_ID = related_doc_id` và `tail_ID = cls_ID`.
    * *Các quan hệ giữ nguyên chiều* (mã cấu hình `False`): `van_ban_bi_thay_the`, `van_ban_duoc_huong_dan`, `van_ban_duoc_sua_doi_bo_sung`, `van_ban_bi_dinh_chinh`, `van_ban_duoc_hop_nhat`, `van_ban_bi_bai_bo`, `van_ban_bi_dinh_chi`, `van_ban_bi_huy_bo`, `van_ban_duoc_quy_dinh_chi_tiet`, `van_ban_duoc_keo_dai_hieu_luc`, `van_ban_bi_ngung_hieu_luc`, `van_ban_can_cu`, `van_ban_dan_chieu`.
      Thiết lập `head_ID = cls_ID` và `tail_ID = related_doc_id`.
* **Priority Guard (Luật bảo vệ độ ưu tiên)**:
  * Để ngăn chặn dữ liệu TVPL (vốn được nhập thủ công và có thể không đồng bộ) đè lên dữ liệu trích xuất tự động bằng thuật toán chuẩn xác của CMCAI, câu lệnh Cypher chèn TVPL sử dụng `OPTIONAL MATCH` để kiểm tra sự tồn tại của quan hệ cùng loại từ nguồn `cmcai`:
    ```cypher
    UNWIND $rel_list AS rel
    MATCH (a:VAN_BAN {ID: rel.head_ID})
    MATCH (b:VAN_BAN {ID: rel.tail_ID})
    OPTIONAL MATCH (a)-[r]->(b)
    WHERE type(r) = rel.rel_type AND r.nguon_cap_nhat = 'cmcai'
    WITH rel, a, b, r
    // Chỉ chèn quan hệ TVPL nếu r IS NULL (không có quan hệ cmcai tương đương)
    CALL apoc.do.when(
        r IS NULL,
        'MERGE (a)-[new_r:REL_TYPE]->(b) SET new_r.nguon_cap_nhat = "tvpl", new_r.thoi_gian_cap_nhat = timestamp RETURN new_r',
        'RETURN r',
        {a:a, b:b, rel_type:rel.rel_type, timestamp:rel.thoi_gian_cap_nhat}
    ) YIELD value
    RETURN count(*)
    ```

#### Chi tiết V (Neo4jToLuocDoPreparation)
* **Truy vấn quan hệ hai chiều**:
  * Thực hiện câu truy vấn Cypher kết hợp toán tử `UNION` để lấy ra tất cả các cạnh nghiệp vụ đi ra (outbound) và đi vào (inbound) liên quan đến danh sách ID trong lô (loại bỏ quan hệ cấu trúc `bao_gom`):
    ```cypher
    MATCH (head:VAN_BAN)-[r]->(tail:VAN_BAN)
    WHERE type(r) <> 'bao_gom' AND head.ID IN $ids
    RETURN head.ID AS head_id, tail.ID AS tail_id, type(r) AS rel_type, r.nguon_cap_nhat AS source
    UNION
    MATCH (head:VAN_BAN)-[r]->(tail:VAN_BAN)
    WHERE type(r) <> 'bao_gom' AND tail.ID IN $ids
    RETURN head.ID AS head_id, tail.ID AS tail_id, type(r) AS rel_type, r.nguon_cap_nhat AS source
    ```
* **Phân loại vai trò (HEAD/TAIL)**:
  * Hệ thống duyệt qua từng kết quả trả về. Nếu ID tài liệu đang xét trùng khớp với `head_id` (đầu cạnh - thực hiện hành động), hệ thống tra cứu bảng ánh xạ `rel_mapping_head` để ghi nhận thông tin vào trường bị động (ví dụ: đầu cạnh của mối quan hệ `thay_the` → ghi vào danh sách `van_ban_bi_thay_the` của văn bản ở đuôi).
  * Ngược lại, nếu ID trùng với `tail_id` (đuôi cạnh - nhận hành động), hệ thống tra cứu bảng `rel_mapping_tail` để ghi nhận vào trường chủ động (ví dụ: đuôi cạnh của `thay_the` → ghi vào danh sách `van_ban_thay_the` của văn bản hiện tại).
* **Ghi lô PyMongo**:
  * Các mối quan hệ sau khi phân loại được gom nhóm theo ID văn bản, đóng gói kèm nhãn thời gian cập nhật `updated_at`.
  * Khởi tạo mảng các câu lệnh `UpdateOne` với cờ `upsert=True` và thực thi ghi đồng loạt xuống MongoDB `ie_collection` bằng phương thức `bulk_write` của PyMongo.

### 3. Các Cơ Chế An Toàn Và Nâng Cao

#### Cơ Chế Lan Truyền Quan Hệ Tự Động (Propagating bo_sung)
* **Vấn đề**: Khi văn bản A bổ sung một điều khoản mới B vào văn bản C, mối quan hệ `bo_sung` được tạo giữa B và A. Tuy nhiên, nếu sau đó một văn bản khác tạo ra các khoản con ảo của B (ví dụ: Khoản 2 Điều B) thông qua quan hệ `bao_gom_sau_bo_sung`, các khoản con ảo này sẽ không có mối liên kết `bo_sung` trực tiếp với văn bản A.
* **Giải pháp**: Hàm `_propagate_bo_sung_to_synthetic_children` thực hiện quét đồ thị Neo4j sau mỗi lượt cập nhật:
  1. Xác định các nút `DIEU_KHOAN` chưa có quan hệ `bo_sung` hướng tới và không thuộc cây cấu trúc nguyên bản `bao_gom`.
  2. Tìm kiếm ngược lên cây phân cấp ảo thông qua đường đi `bao_gom_sau_bo_sung*1..3` để xác định điều khoản cha đã có quan hệ `bo_sung`.
  3. Tự động sao chép và chèn quan hệ `bo_sung` trực tiếp từ văn bản/điều khoản tạo ban đầu tới các nút con ảo này, đảm bảo tính liên kết chặt chẽ của đồ thị.
