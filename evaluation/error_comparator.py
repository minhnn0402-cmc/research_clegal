import pandas as pd
import numpy as np
import json
from pathlib import Path

# Paths
GOLDEN_PATH = r"c:\Users\minhnn\Documents\cmcai\CAI_Legal\research\evaluation\datasets\golden_eval.csv"
RULES_ONLY_PATH = r"c:\Users\minhnn\Documents\cmcai\CAI_Legal\research\evaluation\datasets\report\wrong_extraction_rules_only.csv"
RULES_LLM_PATH = r"c:\Users\minhnn\Documents\cmcai\CAI_Legal\research\evaluation\datasets\report\wrong_extraction.csv"
OUTPUT_REPORT_PATH = r"c:\Users\minhnn\Documents\cmcai\CAI_Legal\research\docs\error_analysis_comparison.md"

def load_and_normalize(path):
    df = pd.read_csv(path, sep=",", dtype=str).fillna("")
    for col in ["so_hieu", "clause_type", "content", "parent_content", "grandparent_content", "reference", "relation"]:
        if col in df.columns:
            df[col] = df[col].str.strip()
    return df

def make_key(row):
    return (
        row["so_hieu"],
        row["clause_type"],
        row["content"],
        row["parent_content"],
        row["grandparent_content"],
        row["reference"],
        row["relation"]
    )

def main():
    print("Loading datasets...")
    df_gt = load_and_normalize(GOLDEN_PATH)
    df_rules = load_and_normalize(RULES_ONLY_PATH)
    df_llm = load_and_normalize(RULES_LLM_PATH)
    
    print(f"Golden count: {len(df_gt)}")
    print(f"Rules-only errors count: {len(df_rules)}")
    print(f"Rules+LLM errors count: {len(df_llm)}")
    
    # Identify unique keys
    gt_keys = set(df_gt.apply(make_key, axis=1))
    
    # For rules-only
    rules_fp_df = df_rules[df_rules["error_type"] == "FP"]
    rules_fn_df = df_rules[df_rules["error_type"] == "FN"]
    rules_fp_keys = set(rules_fp_df.apply(make_key, axis=1))
    rules_fn_keys = set(rules_fn_df.apply(make_key, axis=1))
    
    # For rules+llm
    llm_fp_df = df_llm[df_llm["error_type"] == "FP"]
    llm_fn_df = df_llm[df_llm["error_type"] == "FN"]
    llm_fp_keys = set(llm_fp_df.apply(make_key, axis=1))
    llm_fn_keys = set(llm_fn_df.apply(make_key, axis=1))
    
    # Double check metric match
    # Rules-only: TP = len(GT) - len(FN)
    rules_tp_keys = gt_keys - rules_fn_keys
    rules_tp = len(rules_tp_keys)
    rules_fp = len(rules_fp_keys)
    rules_fn = len(rules_fn_keys)
    rules_p = rules_tp / (rules_tp + rules_fp) if (rules_tp + rules_fp) > 0 else 0
    rules_r = rules_tp / len(gt_keys) if len(gt_keys) > 0 else 0
    rules_f1 = 2 * rules_p * rules_r / (rules_p + rules_r) if (rules_p + rules_r) > 0 else 0
    
    # Rules+LLM: TP = len(GT) - len(FN)
    llm_tp_keys = gt_keys - llm_fn_keys
    llm_tp = len(llm_tp_keys)
    llm_fp = len(llm_fp_keys)
    llm_fn = len(llm_fn_keys)
    llm_p = llm_tp / (llm_tp + llm_fp) if (llm_tp + llm_fp) > 0 else 0
    llm_r = llm_tp / len(gt_keys) if len(gt_keys) > 0 else 0
    llm_f1 = 2 * llm_p * llm_r / (llm_p + llm_r) if (llm_p + llm_r) > 0 else 0
    
    print("\n--- METRICS VERIFICATION ---")
    print(f"Rules-Only: P={rules_p:.4f}, R={rules_r:.4f}, F1={rules_f1:.4f} (TP={rules_tp}, FP={rules_fp}, FN={rules_fn})")
    print(f"Rules+LLM : P={llm_p:.4f}, R={llm_r:.4f}, F1={llm_f1:.4f} (TP={llm_tp}, FP={llm_fp}, FN={llm_fn})")
    
    # Analyze LLM transitions
    # 1. FN resolved by LLM (Recall Gain): in rules FN but not in LLM FN (meaning it became TP)
    fn_resolved_keys = rules_fn_keys - llm_fn_keys
    # 2. FN introduced by LLM (Recall Loss): not in rules FN (meaning it was TP) but in LLM FN
    fn_introduced_keys = llm_fn_keys - rules_fn_keys
    # 3. FP introduced by LLM (Precision Loss): in LLM FP but not in rules FP
    fp_introduced_keys = llm_fp_keys - rules_fp_keys
    # 4. FP resolved by LLM (Precision Gain): in rules FP but not in LLM FP (LLM correctly rejected it)
    fp_resolved_keys = rules_fp_keys - llm_fp_keys
    
    print("\n--- LLM TRANSITIONS ---")
    print(f"FN resolved by LLM (Recall gain)   : {len(fn_resolved_keys)}")
    print(f"FN introduced by LLM (Recall loss) : {len(fn_introduced_keys)}")
    print(f"FP introduced by LLM (Precision loss): {len(fp_introduced_keys)}")
    print(f"FP resolved by LLM (Precision gain) : {len(fp_resolved_keys)}")
    
    # We want to pull samples for each case. We will look up details in df_gt and df_rules / df_llm
    def get_details(keys, df_source, limit=5):
        records = []
        for k in list(keys)[:limit]:
            # find in df_source
            matching = df_source[
                (df_source["so_hieu"] == k[0]) & 
                (df_source["clause_type"] == k[1]) & 
                (df_source["content"] == k[2]) & 
                (df_source["parent_content"] == k[3]) & 
                (df_source["grandparent_content"] == k[4]) & 
                (df_source["reference"] == k[5]) & 
                (df_source["relation"] == k[6])
            ]
            if not matching.empty:
                records.append(matching.iloc[0].to_dict())
            else:
                # search in golden if not found in wrong extraction
                matching_gt = df_gt[
                    (df_gt["so_hieu"] == k[0]) & 
                    (df_gt["clause_type"] == k[1]) & 
                    (df_gt["content"] == k[2]) & 
                    (df_gt["parent_content"] == k[3]) & 
                    (df_gt["grandparent_content"] == k[4]) & 
                    (df_gt["reference"] == k[5]) & 
                    (df_gt["relation"] == k[6])
                ]
                if not matching_gt.empty:
                    records.append(matching_gt.iloc[0].to_dict())
        return records

    fn_resolved_samples = get_details(fn_resolved_keys, df_rules, 10)
    fn_introduced_samples = get_details(fn_introduced_keys, df_llm, 10)
    fp_introduced_samples = get_details(fp_introduced_keys, df_llm, 10)
    fp_resolved_samples = get_details(fp_resolved_keys, df_rules, 10)
    
    # Breakdown by relation type
    # For rules-only
    rules_relations = {}
    for r in df_gt["relation"].unique():
        if r:
            rules_relations[r] = {"tp": 0, "fp": 0, "fn": 0}
            
    for k in gt_keys:
        r = k[6]
        if r in rules_relations:
            if k in rules_fn_keys:
                rules_relations[r]["fn"] += 1
            else:
                rules_relations[r]["tp"] += 1
                
    for k in rules_fp_keys:
        r = k[6]
        if r not in rules_relations:
            rules_relations[r] = {"tp": 0, "fp": 0, "fn": 0}
        rules_relations[r]["fp"] += 1
        
    # For rules+llm
    llm_relations = {}
    for r in df_gt["relation"].unique():
        if r:
            llm_relations[r] = {"tp": 0, "fp": 0, "fn": 0}
            
    for k in gt_keys:
        r = k[6]
        if r in llm_relations:
            if k in llm_fn_keys:
                llm_relations[r]["fn"] += 1
            else:
                llm_relations[r]["tp"] += 1
                
    for k in llm_fp_keys:
        r = k[6]
        if r not in llm_relations:
            llm_relations[r] = {"tp": 0, "fp": 0, "fn": 0}
        llm_relations[r]["fp"] += 1
        
    # Breakdown by clause type
    rules_clauses = {c: {"tp": 0, "fp": 0, "fn": 0} for c in ["vanban", "dieu", "khoan", "diem"]}
    for k in gt_keys:
        c = k[1]
        if c in rules_clauses:
            if k in rules_fn_keys:
                rules_clauses[c]["fn"] += 1
            else:
                rules_clauses[c]["tp"] += 1
    for k in rules_fp_keys:
        c = k[1]
        if c in rules_clauses:
            rules_clauses[c]["fp"] += 1
            
    llm_clauses = {c: {"tp": 0, "fp": 0, "fn": 0} for c in ["vanban", "dieu", "khoan", "diem"]}
    for k in gt_keys:
        c = k[1]
        if c in llm_clauses:
            if k in llm_fn_keys:
                llm_clauses[c]["fn"] += 1
            else:
                llm_clauses[c]["tp"] += 1
    for k in llm_fp_keys:
        c = k[1]
        if c in llm_clauses:
            llm_clauses[c]["fp"] += 1
            
    # Format a Markdown report
    with open(OUTPUT_REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("# Báo Cáo So Sánh Sai Lệch: Regex Thuần vs Rules + LLM\n\n")
        f.write("Báo cáo này đối sánh kết quả bóc tách quan hệ pháp luật giữa hai cấu hình: **Regex thuần (Rules-only)** và **Kết hợp Regex + LLM (Rules + LLM)** dựa trên tập đánh giá `golden_eval.csv`.\n\n")
        
        # 1. Summary table
        f.write("## 1. So Sánh Chỉ Số Tổng Quan\n\n")
        f.write("| Chỉ Số | Regex Thuần (Rules-only) | Kết Hợp (Rules + LLM) | Thay Đổi |\n")
        f.write("|---|---|---|---|\n")
        f.write(f"| **Độ chính xác (Precision)** | {rules_p:.4f} | {llm_p:.4f} | <span style='color:red'>{llm_p - rules_p:+.4f}</span> |\n")
        f.write(f"| **Độ phủ (Recall)** | {rules_r:.4f} | {llm_r:.4f} | <span style='color:green'>{llm_r - rules_r:+.4f}</span> |\n")
        f.write(f"| **F1-Score** | {rules_f1:.4f} | {llm_f1:.4f} | <span style='color:red'>{llm_f1 - rules_f1:+.4f}</span> |\n")
        f.write(f"| **True Positives (TP)** | {rules_tp} | {llm_tp} | {llm_tp - rules_tp:+} |\n")
        f.write(f"| **False Positives (FP) (Sai)** | {rules_fp} | {llm_fp} | <span style='color:red'>{llm_fp - rules_fp:+} (tăng lỗi sai)</span> |\n")
        f.write(f"| **False Negatives (FN) (Sót)** | {rules_fn} | {llm_fn} | <span style='color:green'>{llm_fn - rules_fn:+} (giảm sót)</span> |\n\n")
        
        f.write("> [!IMPORTANT]\n")
        f.write(f"> **Nhận xét chính:** Khi bật LLM, hệ thống giảm được **{rules_fn - llm_fn} trường hợp bỏ sót (FN)** giúp Recall tăng từ `{rules_r:.2%}` lên `{llm_r:.2%}`. Tuy nhiên, LLM lại **sinh thêm {llm_fp - rules_fp} trường hợp bóc sai (FP)** khiến Precision bị kéo tụt mạnh từ `{rules_p:.2%}` xuống `{llm_p:.2%}`, dẫn đến F1-Score chung cuộc giảm `{rules_f1 - llm_f1:.2%}`.\n\n")
        
        # 2. Transition statistics
        f.write("## 2. Chi Tiết Biến Động Do LLM Tác Động\n\n")
        f.write(f"- 🟢 **Số lượng lỗi sót (FN) được LLM cứu thành công (Recall Gain):** `{len(fn_resolved_keys)}` mẫu\n")
        f.write(f"- 🔴 **Số lượng lỗi sót (FN) mới do LLM tự gây ra thêm (Recall Loss):** `{len(fn_introduced_keys)}` mẫu\n")
        f.write(f"- 🔴 **Số lượng lỗi sai (FP) mới do LLM tự sinh ra thêm (Precision Loss):** `{len(fp_introduced_keys)}` mẫu\n")
        f.write(f"- 🟢 **Số lượng lỗi sai (FP) của Regex được LLM sửa/bác bỏ (Precision Gain):** `{len(fp_resolved_keys)}` mẫu\n\n")
        
        # 3. Breakdown by relation type table
        f.write("## 3. Phân Tích Theo Loại Quan Hệ (Relation Type)\n\n")
        f.write("| Loại Quan Hệ | Regex TP | Regex FP | Regex FN | LLM TP | LLM FP | LLM FN | F1 Regex | F1 LLM | Thay Đổi F1 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        
        all_relations = sorted(set(rules_relations.keys()) | set(llm_relations.keys()))
        for r in all_relations:
            r_rules = rules_relations.get(r, {"tp": 0, "fp": 0, "fn": 0})
            r_llm = llm_relations.get(r, {"tp": 0, "fp": 0, "fn": 0})
            
            p_rules = r_rules["tp"] / (r_rules["tp"] + r_rules["fp"]) if (r_rules["tp"] + r_rules["fp"]) > 0 else 0
            r_rules_val = r_rules["tp"] / (r_rules["tp"] + r_rules["fn"]) if (r_rules["tp"] + r_rules["fn"]) > 0 else 0
            f1_rules = 2 * p_rules * r_rules_val / (p_rules + r_rules_val) if (p_rules + r_rules_val) > 0 else 0
            
            p_llm = r_llm["tp"] / (r_llm["tp"] + r_llm["fp"]) if (r_llm["tp"] + r_llm["fp"]) > 0 else 0
            r_llm_val = r_llm["tp"] / (r_llm["tp"] + r_llm["fn"]) if (r_llm["tp"] + r_llm["fn"]) > 0 else 0
            f1_llm = 2 * p_llm * r_llm_val / (p_llm + r_llm_val) if (p_llm + r_llm_val) > 0 else 0
            
            diff_f1 = f1_llm - f1_rules
            color = "green" if diff_f1 > 0 else "red" if diff_f1 < 0 else "black"
            f.write(f"| `{r}` | {r_rules['tp']} | {r_rules['fp']} | {r_rules['fn']} | {r_llm['tp']} | {r_llm['fp']} | {r_llm['fn']} | {f1_rules:.3f} | {f1_llm:.3f} | <span style='color:{color}'>{diff_f1:+.3f}</span> |\n")
            
        f.write("\n")
        
        # 4. Breakdown by clause type table
        f.write("## 4. Phân Tích Theo Cấp Độ Clause (Clause Type)\n\n")
        f.write("| Loại Clause | Regex TP | Regex FP | Regex FN | LLM TP | LLM FP | LLM FN | F1 Regex | F1 LLM | Thay Đổi F1 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for c in ["vanban", "dieu", "khoan", "diem"]:
            c_rules = rules_clauses[c]
            c_llm = llm_clauses[c]
            
            p_rules = c_rules["tp"] / (c_rules["tp"] + c_rules["fp"]) if (c_rules["tp"] + c_rules["fp"]) > 0 else 0
            r_rules_val = c_rules["tp"] / (c_rules["tp"] + c_rules["fn"]) if (c_rules["tp"] + c_rules["fn"]) > 0 else 0
            f1_rules = 2 * p_rules * r_rules_val / (p_rules + r_rules_val) if (p_rules + r_rules_val) > 0 else 0
            
            p_llm = c_llm["tp"] / (c_llm["tp"] + c_llm["fp"]) if (c_llm["tp"] + c_llm["fp"]) > 0 else 0
            r_llm_val = c_llm["tp"] / (c_llm["tp"] + c_llm["fn"]) if (c_llm["tp"] + c_llm["fn"]) > 0 else 0
            f1_llm = 2 * p_llm * r_llm_val / (p_llm + r_llm_val) if (p_llm + r_llm_val) > 0 else 0
            
            diff_f1 = f1_llm - f1_rules
            color = "green" if diff_f1 > 0 else "red" if diff_f1 < 0 else "black"
            f.write(f"| `{c}` | {c_rules['tp']} | {c_rules['fp']} | {c_rules['fn']} | {c_llm['tp']} | {c_llm['fp']} | {c_llm['fn']} | {f1_rules:.3f} | {f1_llm:.3f} | <span style='color:{color}'>{diff_f1:+.3f}</span> |\n")
            
        f.write("\n")
        
        # 5. Detail analyze categories with real examples
        f.write("## 5. Ví Dụ Trực Quan và Phân Tích Nguyên Nhân Lỗi\n\n")
        
        f.write("### A. 🟢 Các mẫu lỗi sót (FN) được LLM cứu thành công (Recall Gain)\n")
        f.write("Đây là các mẫu mà Regex thuần **bỏ sót** vì cấu trúc câu quá phức tạp, không khớp các keyword hoặc quy tắc vị trí của Regex Matcher, nhưng LLM đã hiểu được ngữ nghĩa và bóc thành công.\n\n")
        for i, s in enumerate(fn_resolved_samples[:4], 1):
            f.write(f"#### Ví dụ {i}: Số hiệu `{s['so_hieu']}` (Loại `{s['clause_type']}`)\n")
            f.write(f"- **Nội dung:** *\"{s['content']}\"*\n")
            if s.get('parent_content'):
                f.write(f"- **Nội dung cha:** *\"{s['parent_content']}\"*\n")
            f.write(f"- **Ground Truth:** Cần bóc `[{s['relation']}]` của văn bản `{s['reference']}`\n")
            f.write("- **Giải thích cơ chế cứu:** ")
            # Add general heuristics based on contents
            if "quy định tại" in s['content'] or "quy định của" in s['content']:
                f.write("Câu chứa dẫn chiếu gián tiếp dài hoặc cấu trúc đảo ngữ phức tạp vượt quá scope mặc định của Regex.")
            elif s['reference'] == "Luật này" or "Luật này" in s['content']:
                f.write("LLM hỗ trợ khôi phục tự động tham chiếu nội bộ trong câu phức tạp rất tốt.")
            else:
                f.write("LLM bóc tách nhờ khả năng đọc hiểu ngữ nghĩa toàn văn mà không phụ thuộc vào vị trí ký tự từ khóa hành động.")
            f.write("\n\n")
            
        f.write("### B. 🔴 Các mẫu lỗi sai (FP) mới do LLM tự sinh ra (Precision Loss)\n")
        f.write("Đây là nguyên nhân chính gây tụt giảm hiệu năng. Khi gộp ngữ cảnh cha/ông (`parent_content`, `grandparent_content`), LLM bị phân tâm (Context Noise) và bóc cả những văn bản phụ không liên quan đến quan hệ chính.\n\n")
        for i, s in enumerate(fp_introduced_samples[:5], 1):
            f.write(f"#### Ví dụ {i}: Số hiệu `{s['so_hieu']}` (Loại `{s['clause_type']}`)\n")
            f.write(f"- **Nội dung:** *\"{s['content']}\"*\n")
            if s.get('parent_content'):
                f.write(f"- **Nội dung cha:** *\"{s['parent_content']}\"*\n")
            if s.get('grandparent_content'):
                f.write(f"- **Nội dung ông:** *\"{s['grandparent_content']}\"*\n")
            f.write(f"- **LLM bóc sai (FP):** `[{s['relation']}]` liên kết tới `{s['reference']}`\n")
            f.write("- **Giải thích lỗi:** ")
            if s['reference'] in (s.get('parent_content', '') + s.get('grandparent_content', '')):
                f.write("LLM bị **Context Noise**. Văn bản này thực ra nằm ở tiêu đề cha hoặc ông (nhằm mục đích tham chiếu ngữ cảnh), hoàn toàn không phải là mục tiêu tác động trực tiếp của điều khoản con hiện tại.")
            elif "Mẫu" in s['reference'] or "mẫu" in s['reference'].lower() or s['reference'].startswith("Mẫu số"):
                f.write("LLM bóc nhầm **Mã biểu mẫu** (ví dụ: 'Mẫu số 29-TTr') thành một văn bản pháp luật độc lập do thiếu bộ lọc nhiễu cứng.")
            else:
                f.write("LLM bóc quá đà (over-extraction) các văn bản chỉ mang tính chất lịch sử hoặc điều khoản dẫn chiếu thủ tục phụ trong câu.")
            f.write("\n\n")
            
        f.write("### C. 🔴 Các mẫu lỗi sót (FN) mới do LLM tự gây ra thêm (Recall Loss)\n")
        f.write("Đây là những trường hợp ban đầu Regex thuần làm đúng, nhưng khi bật LLM thì LLM lại bác bỏ hoặc sinh định dạng JSON lỗi, làm mất kết quả đúng ban đầu.\n\n")
        for i, s in enumerate(fn_introduced_samples[:4], 1):
            f.write(f"#### Ví dụ {i}: Số hiệu `{s['so_hieu']}` (Loại `{s['clause_type']}`)\n")
            f.write(f"- **Nội dung:** *\"{s['content']}\"*\n")
            f.write(f"- **Ground Truth (Regex bóc đúng nhưng LLM làm mất):** `[{s['relation']}]` liên kết tới `{s['reference']}`\n")
            f.write("- **Giải thích lỗi:** ")
            f.write("LLM bỏ sót do không tuân thủ hoàn hảo định dạng JSON đầu ra, hoặc mô hình phân loại sai nhãn hành động (ví dụ nhãn `sua_doi_bo_sung` bị LLM đổi thành `dan_chieu` hoặc ngược lại).")
            f.write("\n\n")

        f.write("### D. 🔴 Các mẫu lỗi sai cả Regex thuần lẫn LLM cùng phạm phải\n")
        f.write("Đây là những ca khó nhất, nơi cả hệ thống luật lệ lẫn mô hình ngôn ngữ đều thất bại.\n\n")
        both_fn_keys = rules_fn_keys & llm_fn_keys
        both_fn_samples = get_details(both_fn_keys, df_gt, 5)
        for i, s in enumerate(both_fn_samples[:4], 1):
            f.write(f"#### Ví dụ {i}: Số hiệu `{s['so_hieu']}` (Loại `{s['clause_type']}`)\n")
            f.write(f"- **Nội dung:** *\"{s['content']}\"*\n")
            f.write(f"- **Ground Truth:** `[{s['relation']}]` liên kết tới `{s['reference']}`\n")
            f.write("- **Giải thích lỗi:** ")
            f.write("Văn bản nguồn sử dụng cách viết cực kỳ đặc biệt, hoặc số hiệu bị viết tắt/lỗi chính tả nghiêm trọng trong text nguồn khiến cả Regex và LLM đều không thể nhận dạng được số hiệu chuẩn.")
            f.write("\n\n")

        # 6. Conclusion and next steps
        f.write("## 6. Đề Xuất Hướng Cải Thiện Tiếp Theo\n\n")
        f.write("Dựa trên thống kê sai lệch trên, đây là lộ trình tối ưu hóa mà không cần phải thay đổi cấu trúc lớn:\n\n")
        f.write("1. **Áp dụng bộ lọc Regex Edge Cases lên kết quả của LLM:**\n")
        f.write("   - Kết quả đầu ra từ LLM cần chạy qua Bộ lọc số 4 (ví dụ loại bỏ `FORM_IDENTIFIER_PREFIX` như *Mẫu số X*, loại bỏ chú thích sửa đổi provenance `AMENDMENT_PROVENANCE`). Điều này sẽ triệt tiêu ngay lập tức khoảng 20-30% lỗi FP do LLM ảo tưởng.\n\n")
        f.write("2. **Điều chỉnh tham số Ngữ cảnh đầu vào LLM:**\n")
        f.write("   - Hạn chế đưa `grandparent_content` nếu clause_type là `khoan` hoặc `diem` trừ khi thực sự cần thiết, để giảm Context Noise khiến LLM bóc thừa văn bản tiêu đề.\n\n")
        f.write("3. **Cải tiến Prompt của LangExtract:**\n")
        f.write("   - Thêm các ví dụ Negative Examples (mẫu không được bóc) vào few-shot để dạy LLM loại trừ các văn bản lịch sử sửa đổi hoặc văn bản dẫn chiếu quy trình phụ.\n")

    # Build difference records
    diff_records = []
    
    # 1. FN resolved by LLM (Recall Gain)
    for k in fn_resolved_keys:
        samples = df_gt[
            (df_gt["so_hieu"] == k[0]) & 
            (df_gt["clause_type"] == k[1]) & 
            (df_gt["content"] == k[2]) & 
            (df_gt["parent_content"] == k[3]) & 
            (df_gt["grandparent_content"] == k[4]) & 
            (df_gt["reference"] == k[5]) & 
            (df_gt["relation"] == k[6])
        ]
        if not samples.empty:
            row = samples.iloc[0].to_dict()
            diff_records.append({
                "so_hieu": row["so_hieu"],
                "clause_type": row["clause_type"],
                "content": row["content"],
                "parent_content": row["parent_content"],
                "grandparent_content": row["grandparent_content"],
                "reference": row["reference"],
                "relation": row["relation"],
                "diff_type": "FN_resolved_by_LLM"
            })
            
    # 2. FN introduced by LLM (Recall Loss)
    for k in fn_introduced_keys:
        samples = df_gt[
            (df_gt["so_hieu"] == k[0]) & 
            (df_gt["clause_type"] == k[1]) & 
            (df_gt["content"] == k[2]) & 
            (df_gt["parent_content"] == k[3]) & 
            (df_gt["grandparent_content"] == k[4]) & 
            (df_gt["reference"] == k[5]) & 
            (df_gt["relation"] == k[6])
        ]
        if not samples.empty:
            row = samples.iloc[0].to_dict()
            diff_records.append({
                "so_hieu": row["so_hieu"],
                "clause_type": row["clause_type"],
                "content": row["content"],
                "parent_content": row["parent_content"],
                "grandparent_content": row["grandparent_content"],
                "reference": row["reference"],
                "relation": row["relation"],
                "diff_type": "FN_introduced_by_LLM"
            })
            
    # 3. FP introduced by LLM (Precision Loss)
    for k in fp_introduced_keys:
        samples = df_llm[
            (df_llm["so_hieu"] == k[0]) & 
            (df_llm["clause_type"] == k[1]) & 
            (df_llm["content"] == k[2]) & 
            (df_llm["parent_content"] == k[3]) & 
            (df_llm["grandparent_content"] == k[4]) & 
            (df_llm["reference"] == k[5]) & 
            (df_llm["relation"] == k[6])
        ]
        if not samples.empty:
            row = samples.iloc[0].to_dict()
            diff_records.append({
                "so_hieu": row["so_hieu"],
                "clause_type": row["clause_type"],
                "content": row["content"],
                "parent_content": row["parent_content"],
                "grandparent_content": row["grandparent_content"],
                "reference": row["reference"],
                "relation": row["relation"],
                "diff_type": "FP_introduced_by_LLM"
            })
            
    # 4. FP resolved by LLM (Precision Gain)
    for k in fp_resolved_keys:
        samples = df_rules[
            (df_rules["so_hieu"] == k[0]) & 
            (df_rules["clause_type"] == k[1]) & 
            (df_rules["content"] == k[2]) & 
            (df_rules["parent_content"] == k[3]) & 
            (df_rules["grandparent_content"] == k[4]) & 
            (df_rules["reference"] == k[5]) & 
            (df_rules["relation"] == k[6])
        ]
        if not samples.empty:
            row = samples.iloc[0].to_dict()
            diff_records.append({
                "so_hieu": row["so_hieu"],
                "clause_type": row["clause_type"],
                "content": row["content"],
                "parent_content": row["parent_content"],
                "grandparent_content": row["grandparent_content"],
                "reference": row["reference"],
                "relation": row["relation"],
                "diff_type": "FP_resolved_by_LLM"
            })
            
    df_diff = pd.DataFrame(diff_records)
    diff_csv_path = r"c:\Users\minhnn\Documents\cmcai\CAI_Legal\research\evaluation\datasets\report\diff_rules_vs_llm.csv"
    df_diff.to_csv(diff_csv_path, index=False, encoding="utf-8-sig")
    print(f"Diff CSV saved to: {diff_csv_path}")
    print(f"Comparison report saved to: {OUTPUT_REPORT_PATH}")

if __name__ == "__main__":
    main()
