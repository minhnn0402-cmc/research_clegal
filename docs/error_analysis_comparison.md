# Báo Cáo So Sánh Sai Lệch: Regex Thuần vs Rules + LLM

Báo cáo này đối sánh kết quả bóc tách quan hệ pháp luật giữa hai cấu hình: **Regex thuần (Rules-only)** và **Kết hợp Regex + LLM (Rules + LLM)** dựa trên tập đánh giá `golden_eval.csv`.

## 1. So Sánh Chỉ Số Tổng Quan

| Chỉ Số | Regex Thuần (Rules-only) | Kết Hợp (Rules + LLM) | Thay Đổi |
|---|---|---|---|
| **Độ chính xác (Precision)** | 0.8913 | 0.8661 | <span style='color:red'>-0.0251</span> |
| **Độ phủ (Recall)** | 0.9037 | 0.9088 | <span style='color:green'>+0.0050</span> |
| **F1-Score** | 0.8975 | 0.8869 | <span style='color:red'>-0.0105</span> |
| **True Positives (TP)** | 1615 | 1624 | +9 |
| **False Positives (FP) (Sai)** | 197 | 251 | <span style='color:red'>+54 (tăng lỗi sai)</span> |
| **False Negatives (FN) (Sót)** | 172 | 163 | <span style='color:green'>-9 (giảm sót)</span> |

> [!IMPORTANT]
> **Nhận xét chính:** Khi bật LLM, hệ thống giảm được **9 trường hợp bỏ sót (FN)** giúp Recall tăng từ `90.37%` lên `90.88%`. Tuy nhiên, LLM lại **sinh thêm 54 trường hợp bóc sai (FP)** khiến Precision bị kéo tụt mạnh từ `89.13%` xuống `86.61%`, dẫn đến F1-Score chung cuộc giảm `1.05%`.

## 2. Chi Tiết Biến Động Do LLM Tác Động

- 🟢 **Số lượng lỗi sót (FN) được LLM cứu thành công (Recall Gain):** `9` mẫu
- 🔴 **Số lượng lỗi sót (FN) mới do LLM tự gây ra thêm (Recall Loss):** `0` mẫu
- 🔴 **Số lượng lỗi sai (FP) mới do LLM tự sinh ra thêm (Precision Loss):** `54` mẫu
- 🟢 **Số lượng lỗi sai (FP) của Regex được LLM sửa/bác bỏ (Precision Gain):** `0` mẫu

## 3. Phân Tích Theo Loại Quan Hệ (Relation Type)

| Loại Quan Hệ | Regex TP | Regex FP | Regex FN | LLM TP | LLM FP | LLM FN | F1 Regex | F1 LLM | Thay Đổi F1 |
|---|---|---|---|---|---|---|---|---|---|
| `bai_bo` | 209 | 31 | 12 | 209 | 33 | 12 | 0.907 | 0.903 | <span style='color:red'>-0.004</span> |
| `bo_sung` | 44 | 3 | 1 | 44 | 3 | 1 | 0.957 | 0.957 | <span style='color:black'>+0.000</span> |
| `can_cu` | 287 | 12 | 12 | 287 | 12 | 12 | 0.960 | 0.960 | <span style='color:black'>+0.000</span> |
| `dan_chieu` | 414 | 64 | 81 | 419 | 90 | 76 | 0.851 | 0.835 | <span style='color:red'>-0.016</span> |
| `dinh_chi` | 16 | 6 | 0 | 16 | 8 | 0 | 0.842 | 0.800 | <span style='color:red'>-0.042</span> |
| `dinh_chinh` | 47 | 14 | 1 | 48 | 17 | 0 | 0.862 | 0.850 | <span style='color:red'>-0.013</span> |
| `hop_nhat` | 41 | 3 | 3 | 41 | 3 | 3 | 0.932 | 0.932 | <span style='color:black'>+0.000</span> |
| `huong_dan` | 14 | 11 | 1 | 14 | 12 | 1 | 0.700 | 0.683 | <span style='color:red'>-0.017</span> |
| `huy_bo` | 14 | 0 | 0 | 14 | 0 | 0 | 1.000 | 1.000 | <span style='color:black'>+0.000</span> |
| `keo_dai_hieu_luc` | 26 | 10 | 0 | 26 | 10 | 0 | 0.839 | 0.839 | <span style='color:black'>+0.000</span> |
| `ngung_hieu_luc` | 42 | 12 | 4 | 43 | 24 | 3 | 0.840 | 0.761 | <span style='color:red'>-0.079</span> |
| `quy_dinh_chi_tiet` | 57 | 2 | 1 | 57 | 7 | 1 | 0.974 | 0.934 | <span style='color:red'>-0.040</span> |
| `sua_doi` | 264 | 11 | 6 | 264 | 11 | 6 | 0.969 | 0.969 | <span style='color:black'>+0.000</span> |
| `sua_doi_bo_sung` | 91 | 7 | 32 | 92 | 10 | 31 | 0.824 | 0.818 | <span style='color:red'>-0.006</span> |
| `thay_the` | 49 | 11 | 18 | 50 | 11 | 17 | 0.772 | 0.781 | <span style='color:green'>+0.010</span> |

## 4. Phân Tích Theo Cấp Độ Clause (Clause Type)

| Loại Clause | Regex TP | Regex FP | Regex FN | LLM TP | LLM FP | LLM FN | F1 Regex | F1 LLM | Thay Đổi F1 |
|---|---|---|---|---|---|---|---|---|---|
| `vanban` | 395 | 19 | 19 | 395 | 19 | 19 | 0.954 | 0.954 | <span style='color:black'>+0.000</span> |
| `dieu` | 299 | 42 | 58 | 304 | 57 | 53 | 0.857 | 0.847 | <span style='color:red'>-0.010</span> |
| `khoan` | 522 | 87 | 63 | 525 | 108 | 60 | 0.874 | 0.862 | <span style='color:red'>-0.012</span> |
| `diem` | 399 | 49 | 32 | 400 | 67 | 31 | 0.908 | 0.891 | <span style='color:red'>-0.017</span> |

## 5. Ví Dụ Trực Quan và Phân Tích Nguyên Nhân Lỗi

### A. 🟢 Các mẫu lỗi sót (FN) được LLM cứu thành công (Recall Gain)
Đây là các mẫu mà Regex thuần **bỏ sót** vì cấu trúc câu quá phức tạp, không khớp các keyword hoặc quy tắc vị trí của Regex Matcher, nhưng LLM đã hiểu được ngữ nghĩa và bóc thành công.

#### Ví dụ 1: Số hiệu `1026/QĐ-BNNMT` (Loại `khoan`)
- **Nội dung:** *"b) Số thứ tự 1 của khoản A Mục I Phần I; số thứ tự 1, 2, 3 của khoản B Mục I Phần I và nội dung cụ thể tương ứng tại số thứ tự 1 của khoản A Mục I Phần II; số thứ tự 1, 2, 3 của khoản B Mục I Phần II tại Phụ lục kèm theo Quyết định số 3969/QĐ-BNNMT ngày 25 tháng 9 năm 2025 của Bộ trưởng Bộ Nông nghiệp và Môi trường về việc công bố thủ tục hành chính nội bộ mới ban hành; sửa đổi, bổ sung lĩnh vực đất đai thuộc phạm vi chức năng quản lý nhà nước của Bộ Nông nghiệp và Môi trường.
Trong thời gian Ủy ban nhân dân cấp tỉnh chưa ban hành thủ tục hành chính theo quy định tại khoản 1 Điều 15 của Nghị định số 49/2026/NĐ-CP ngày 31 tháng 01 năm 2026 của Chính phủ ban hành Nghị định quy định chi tiết và hướng dẫn một số điều của Nghị quyết số 254/2025/QH15 của Quốc hội quy định một số cơ chế, chính sách tháo gỡ khó khăn, vướng mắc trong tổ chức thi hành Luật Đất đai thì tiếp tục thực hiện các thủ tục hành chính nêu tại Khoản này."*
- **Nội dung cha:** *"2. Bãi bỏ các nội dung công bố tại Quyết định số 2417/QĐ-BNNMT ngày 28 tháng 6 năm 2025 của Bộ trưởng Bộ Nông nghiệp và Môi trường về việc công bố thủ tục hành chính nội bộ lĩnh vực đất đai thuộc phạm vi chức năng quản lý nhà nước của Bộ Nông nghiệp và Môi trường và Quyết định số 3969/QĐ-BNNMT ngày 25 tháng 9 năm 2025 của Bộ trưởng Bộ Nông nghiệp và Môi trường về việc công bố thủ tục hành chính nội bộ mới ban hành; sửa đổi, bổ sung lĩnh vực đất đai thuộc phạm vi chức năng quản lý nhà nước của Bộ Nông nghiệp và Môi trường, như sau:"*
- **Ground Truth:** Cần bóc `[dan_chieu]` của văn bản `khoản 1 Điều 15 của Nghị định số 49/2026/NĐ-CP ngày 31 tháng 01 năm 2026`
- **Giải thích cơ chế cứu:** Câu chứa dẫn chiếu gián tiếp dài hoặc cấu trúc đảo ngữ phức tạp vượt quá scope mặc định của Regex.

#### Ví dụ 2: Số hiệu `19/2026/TT-BNNMT` (Loại `khoan`)
- **Nội dung:** *"3. Sửa đổi nội dung mô tả của trường thông tin Mã thửa đất tại các bảng a, b, c của mục 2.2.1; bảng b của mục 2.2.6.3; bảng a của mục 1.1 tại Phụ lục I của Thông tư số 09/2024/TT-BTNMT ngày 31 tháng 7 năm 2024 của Bộ trưởng Bộ Tài nguyên và Môi trường quy định về nội dung, cấu trúc, kiểu thông tin cơ sở dữ liệu quốc gia về đất đai và yêu cầu kỹ thuật đối với phần mềm ứng dụng của Hệ thống thông tin quốc gia về đất đai thành “Mã định danh thửa đất là chuỗi gồm 12 ký tự xác định vị trí địa lý của thửa đất trong hệ tọa độ địa lý quốc tế WGS84 được mã hóa theo thuật toán GeoHash được gán cho từng thửa đất và có tính duy nhất trên toàn quốc”."*
- **Nội dung cha:** *"Điều 11. Hiệu lực thi hành"*
- **Ground Truth:** Cần bóc `[sua_doi_bo_sung]` của văn bản `Thông tư số 09/2024/TT-BTNMT ngày 31 tháng 7 năm 2024`
- **Giải thích cơ chế cứu:** LLM bóc tách nhờ khả năng đọc hiểu ngữ nghĩa toàn văn mà không phụ thuộc vào vị trí ký tự từ khóa hành động.

#### Ví dụ 3: Số hiệu `592/QĐ-UBND` (Loại `diem`)
- **Nội dung:** *"a) Đính chính căn cứ ban hành tại các Quyết định của Ủy ban nhân dân tỉnh: Số 09/2025/QĐ-UBND ngày 19 tháng 02 năm 2025 Quy định một số chỉ tiêu cụ thể, yếu tố ảnh hưởng đến giá đất khi áp dụng phương pháp định giá đất trên địa bàn tỉnh Quảng Ngãi theo Nghị định số 71/2024/NĐ-CP ngày 27 tháng 6 năm 2024 của Chính phủ quy định về giá đất; số 16/2025/QĐ-UBND ngày 28 tháng 02 năm 2025 Bãi bỏ Quyết định số 36/2017/QĐ-UBND ngày 29 tháng 5 năm 2017 của UBND tỉnh quy định mức thu, chế độ thu, nộp và quản lý lệ phí đăng ký kinh doanh trên địa bàn tỉnh Quảng Ngãi, cụ thể:
- Tại căn cứ ban hành: “Căn cứ Luật Tổ chức chính quyền địa phương ngày 19 tháng 6 năm 2015; Luật sửa đổi, bổ sung một số điều của Luật Tổ chức Chính phủ và Luật Tổ chức chính quyền địa phương ngày 22 tháng 11 năm 2019”.
- Nay đính chính là: “Căn cứ Luật Tổ chức Chính quyền địa phương ngày 19 tháng 02 năm 2025”."*
- **Nội dung cha:** *"Điều 1."*
- **Ground Truth:** Cần bóc `[dinh_chinh]` của văn bản `Quyết định 16/2025/QĐ-UBND ngày 28 tháng 02 năm 2025`
- **Giải thích cơ chế cứu:** LLM bóc tách nhờ khả năng đọc hiểu ngữ nghĩa toàn văn mà không phụ thuộc vào vị trí ký tự từ khóa hành động.

#### Ví dụ 4: Số hiệu `17/2025/QĐ-UBND` (Loại `dieu`)
- **Nội dung:** *"Điều 2. Quyết định này có hiệu lực thi hành kể từ ngày 01 tháng 8 năm 2025; Chỉ thị số 20/2012/CT-UBND ngày 04/12/2012 của UBND tỉnh về việc tăng cường công tác bảo vệ quyền lợi người tiêu dùng trên địa bàn tỉnh Quảng Ngãi hết hiệu lực thi hành kể từ ngày Quyết định này có hiệu lực thi hành."*
- **Ground Truth:** Cần bóc `[thay_the]` của văn bản `Chỉ thị số 20/2012/CT-UBND ngày 04/12/2012`
- **Giải thích cơ chế cứu:** LLM bóc tách nhờ khả năng đọc hiểu ngữ nghĩa toàn văn mà không phụ thuộc vào vị trí ký tự từ khóa hành động.

### B. 🔴 Các mẫu lỗi sai (FP) mới do LLM tự sinh ra (Precision Loss)
Đây là nguyên nhân chính gây tụt giảm hiệu năng. Khi gộp ngữ cảnh cha/ông (`parent_content`, `grandparent_content`), LLM bị phân tâm (Context Noise) và bóc cả những văn bản phụ không liên quan đến quan hệ chính.

#### Ví dụ 1: Số hiệu `1739/QĐ-UBND` (Loại `dieu`)
- **Nội dung:** *"Điều 1. Đình chỉ thi hành Khoản 1 của Điều 8, Quy định kèm theo Quyết định số 20/2010/QĐ-UBND ngày 23/9/2010 của Ủy ban nhân dân tỉnh Cà Mau ban hành Quy định về quản lý và bảo vệ động vật hoang dã trên địa bàn tỉnh Cà Mau; Khoản 2, Khoản 3 của Điều 1 và loài rùa hộp lưng đen (số thứ tự 24) tại Danh mục động vật hoang dã thông thường được quản lý, bảo vệ trên địa bàn tỉnh Cà Mau, thuộc Quyết định số 03/2014/QĐ-UBND ngày 08/02/2014 của Ủy ban nhân dân tỉnh Cà Mau sửa đổi, bổ sung một số điều của Quy định về quản lý và bảo vệ động vật hoang dã trên địa bàn tỉnh Cà Mau ban hành kèm theo Quyết định số 20/2010/QĐ-UBND ngày 23/9/2010 của Ủy ban nhân dân tỉnh Cà Mau. Lý do đình chỉ: Do không phù hợp với quy định của pháp luật hiện hành."*
- **LLM bóc sai (FP):** `[dinh_chi]` liên kết tới `Khoản 2 điều 1 Quyết định số 20/2010/QĐ-UBND ngày 23/9/2010`
- **Giải thích lỗi:** LLM bóc quá đà (over-extraction) các văn bản chỉ mang tính chất lịch sử hoặc điều khoản dẫn chiếu thủ tục phụ trong câu.

#### Ví dụ 2: Số hiệu `309/2025/NĐ-CP` (Loại `dieu`)
- **Nội dung:** *"Điều 1. Bãi bỏ cụm từ “và quy định khác có liên quan” tại điểm b khoản 5 Điều 36 Nghị định số 26/2019/NĐ-CP đã được sửa đổi, bổ sung tại khoản 14 Điều 1 Nghị định số 37/2024/NĐ-CP."*
- **LLM bóc sai (FP):** `[bai_bo]` liên kết tới `điểm b khoản 5 Điều 36 Nghị định số 26/2019/NĐ-CP`
- **Giải thích lỗi:** LLM bóc quá đà (over-extraction) các văn bản chỉ mang tính chất lịch sử hoặc điều khoản dẫn chiếu thủ tục phụ trong câu.

#### Ví dụ 3: Số hiệu `34/2021/TT-BGDĐT` (Loại `khoan`)
- **Nội dung:** *"2. Trường hợp đăng ký dự xét thăng hạng chức danh nghề nghiệp, ngoài các hồ sơ quy định tại khoản 1 Điều này thì cần nộp các minh chứng đạt tiêu chuẩn của hạng chức danh nghề nghiệp đăng ký dự xét theo hướng dẫn tại phụ lục kèm theo Thông tư này."*
- **Nội dung cha:** *"Điều 4. Hồ sơ đăng ký dự thi hoặc xét thăng hạng chức danh nghề nghiệp"*
- **LLM bóc sai (FP):** `[dan_chieu]` liên kết tới `Thông tư này`
- **Giải thích lỗi:** LLM bóc quá đà (over-extraction) các văn bản chỉ mang tính chất lịch sử hoặc điều khoản dẫn chiếu thủ tục phụ trong câu.

#### Ví dụ 4: Số hiệu `59/2024/QH15` (Loại `khoan`)
- **Nội dung:** *"3. Khi có một trong các căn cứ quy định tại khoản 1 Điều này, cơ quan thi hành án hình sự Công an cấp huyện nơi người phải chấp hành biện pháp giáo dục tại trường giáo dưỡng cư trú, Hiệu trưởng trường giáo dưỡng thông báo cho Tòa án có thẩm quyền quy định tại khoản 2 và khoản 3 Điều 95 của Luật này để ra quyết định đình chỉ thi hành."*
- **Nội dung cha:** *"Điều 96. Đình chỉ thi hành quyết định áp dụng biện pháp giáo dục tại trường giáo dưỡng"*
- **LLM bóc sai (FP):** `[dan_chieu]` liên kết tới `khoản 2 Điều 95 Luật này`
- **Giải thích lỗi:** LLM bóc quá đà (over-extraction) các văn bản chỉ mang tính chất lịch sử hoặc điều khoản dẫn chiếu thủ tục phụ trong câu.

#### Ví dụ 5: Số hiệu `29/2025/TT-BYT` (Loại `khoan`)
- **Nội dung:** *"1. Quy định về dữ liệu lâm sàng để bảo đảm an toàn, hiệu quả trong hồ sơ đăng ký thuốc cổ truyền và tiêu chí để xác định trường hợp miễn thử, miễn một số giai đoạn thử thuốc cổ truyền trên lâm sàng tại Việt Nam và thuốc cổ truyền phải yêu cầu thử lâm sàng giai đoạn 4 tại khoản 2, khoản 3 Điều 72 và khoản 4 Điều 89 Luật Dược."*
- **Nội dung cha:** *"Điều 1. Phạm vi điều chỉnh
Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số điều của Luật Dược ngày 21 tháng 11 năm 2024 (sau đây gọi là Luật Dược), bao gồm:"*
- **LLM bóc sai (FP):** `[quy_dinh_chi_tiet]` liên kết tới `khoản 2 Điều 72 Luật Dược`
- **Giải thích lỗi:** LLM bóc quá đà (over-extraction) các văn bản chỉ mang tính chất lịch sử hoặc điều khoản dẫn chiếu thủ tục phụ trong câu.

### C. 🔴 Các mẫu lỗi sót (FN) mới do LLM tự gây ra thêm (Recall Loss)
Đây là những trường hợp ban đầu Regex thuần làm đúng, nhưng khi bật LLM thì LLM lại bác bỏ hoặc sinh định dạng JSON lỗi, làm mất kết quả đúng ban đầu.

### D. 🔴 Các mẫu lỗi sai cả Regex thuần lẫn LLM cùng phạm phải
Đây là những ca khó nhất, nơi cả hệ thống luật lệ lẫn mô hình ngôn ngữ đều thất bại.

#### Ví dụ 1: Số hiệu `932/QĐ-UBND` (Loại `dieu`)
- **Nội dung:** *"Điều 1. Bãi bỏ các Kế hoạch của Ủy ban nhân dân tỉnh: Số 217/KH-UBND ngày 18/9/2019 về việc nâng cao hiệu quả công tác phối hợp, phục vụ quản lý nhà nước trong lĩnh vực kinh doanh nhà hàng, khách sạn, nhà nghỉ, nhà ở có phòng cho khách du lịch thuê, căn hộ du lịch, cho thuê mặt bằng kinh doanh; số 51/KH- UBND ngày 12/3/2020 về việc đổi mới, tăng cường công tác quản lý nhà nước, quản lý thu thuế đối với hoạt động vận tải; số 108/KH-UBND ngày 11/6/2020 về nâng cao hiệu quả công tác phối hợp, phục vụ quản lý thuế đối với hoạt động khai thác khoáng sản; số 137/KH-UBND ngày 28/7/2020 về việc tăng cường công tác quản lý thuế trong hoạt động xây dựng; số 163/KH-UBND ngày 03/9/2020 về tăng cường công tác quản lý nhà nước trong hoạt động kinh doanh xăng dầu; số 72/KH- UBND ngày 08/3/2022 về việc tăng cường công tác quản lý thuế đối với hoạt động kinh doanh bất động sản; số 31/KH-UBND ngày 13/02/2023 về việc tăng cường công tác quản lý thuế đối với hoạt động thương mại điện tử, kinh doanh trên nền tảng số trên địa bàn tỉnh Quảng Ninh."*
- **Ground Truth:** `[bai_bo]` liên kết tới `Kế hoạch 31/KH-UBND ngày 13/02/2023`
- **Giải thích lỗi:** Văn bản nguồn sử dụng cách viết cực kỳ đặc biệt, hoặc số hiệu bị viết tắt/lỗi chính tả nghiêm trọng trong text nguồn khiến cả Regex và LLM đều không thể nhận dạng được số hiệu chuẩn.

#### Ví dụ 2: Số hiệu `90/2007/QĐ-BNN` (Loại `khoan`)
- **Nội dung:** *"2. Việc đính chính văn bản quy phạm pháp luật đã ban hành hoặc được đăng Công báo phải dựa trên cơ sở đối chiếu với văn bản gốc và không làm thay đổi nội dung của quy định trong văn bản gốc.
Chỉ đính chính đối với lỗi chính tả hoặc sai sót về thể thức, kỹ thuật trình bày văn bản quy phạm pháp luật. Việc đính chính không áp dụng đối với những sai sót về căn cứ ban hành, thẩm quyền, nội dung của văn bản quy phạm pháp luật.
Trong trường hợp văn bản quy phạm pháp luật có những sai sót về thẩm quyền, nội dung thì văn bản quy phạm pháp luật đó sẽ bị đình chỉ thi hành và xử lý kịp thời theo quy định của Luật ban hành văn bản quy phạm pháp luật và Nghị định số 161/2005/NĐ-CP ."*
- **Ground Truth:** `[dan_chieu]` liên kết tới `Nghị định số 161/2005/NĐ-CP`
- **Giải thích lỗi:** Văn bản nguồn sử dụng cách viết cực kỳ đặc biệt, hoặc số hiệu bị viết tắt/lỗi chính tả nghiêm trọng trong text nguồn khiến cả Regex và LLM đều không thể nhận dạng được số hiệu chuẩn.

#### Ví dụ 3: Số hiệu `118/QĐ-TTg` (Loại `dieu`)
- **Nội dung:** *"Điều 3. Tập trung, chủ động thực hiện kịp thời, linh hoạt, hiệu quả các cơ chế, chính sách đãi ngộ, thu hút nhân lực y tế cho tất cả các đối tượng theo quy định trong lĩnh vực pháp y, pháp y tâm thần, bắt buộc chữa bệnh tâm thần với lộ trình phù hợp theo thực tế triển khai và khả năng ngân sách nhà nước đồng bộ với các cơ chế, chính sách và quy định pháp luật liên quan, trong đó có Nghị quyết số 72-NQ/TW ngày 09 tháng 9 năm 2025 của Bộ Chính trị về một số giải pháp đột phá, tăng cường bảo vệ, chăm sóc và nâng cao sức khỏe Nhân dân; Nghị quyết số 282/NQ-CP ngày 15 tháng 9 năm 2025 của Chính phủ ban hành Chương trình hành động của Chính phủ thực hiện Nghị quyết số 72-NQ/TW của Bộ Chính trị về một số giải pháp đột phá, tăng cường bảo vệ, chăm sóc và nâng cao sức khỏe Nhân dân; Nghị quyết số 261/2025/QH15 của Quốc hội ngày 11 tháng 12 năm 2025 về một số cơ chế, chính sách đặc biệt tạo đột phá cho công tác bảo vệ, chăm sóc và nâng cao sức khỏe nhân dân; Nghị định số 238/2025/NĐ-CP ngày 03 tháng 9 năm 2025 quy định về chính sách học phí, miễn, giảm, hỗ trợ học phí, hỗ trợ chi phí học tập và giá dịch vụ trong lĩnh vực giáo dục, đào tạo; Nghị định số 111/2017/NĐ-CP ngày 05 tháng 10 năm 2017 của Chính phủ quy định về tổ chức đào tạo thực hành trong đào tạo khối ngành sức khỏe; Chỉ thị số 54-CT/TW ngày 30 tháng 11 năm 2025 của Bộ Chính trị về tăng cường sự lãnh đạo của Đảng đối với công tác giám định tư pháp và định giá tài sản."*
- **Ground Truth:** `[dan_chieu]` liên kết tới `Nghị quyết số 72-NQ/TW ngày 09 tháng 9 năm 2025`
- **Giải thích lỗi:** Văn bản nguồn sử dụng cách viết cực kỳ đặc biệt, hoặc số hiệu bị viết tắt/lỗi chính tả nghiêm trọng trong text nguồn khiến cả Regex và LLM đều không thể nhận dạng được số hiệu chuẩn.

#### Ví dụ 4: Số hiệu `12/VGNN-PPCĐ` (Loại `khoan`)
- **Nội dung:** *"7. Thành lập Hội đồng Vật giá của tỉnh theo tinh thần Thông tư hướng dẫn số 683/ VGNN-KHCS ngày 10 tháng 9 năm 1984 của Uỷ ban Vật giá Nhà nước."*
- **Ground Truth:** `[dan_chieu]` liên kết tới `Thông tư hướng dẫn số 683/VGNN-KHCS ngày 10 tháng 9 năm 1984`
- **Giải thích lỗi:** Văn bản nguồn sử dụng cách viết cực kỳ đặc biệt, hoặc số hiệu bị viết tắt/lỗi chính tả nghiêm trọng trong text nguồn khiến cả Regex và LLM đều không thể nhận dạng được số hiệu chuẩn.

## 6. Phân Tích Điều Kiện Kích Hoạt LLM (Trigger Analysis)

Hệ thống kích hoạt LLM Fallback dựa trên các điều kiện logic kiểm thử độ rủi ro (`C0`, `C1`, `C3`, `C4a`, `C4b`, `C5`). Thống kê dưới đây chỉ ra lý do tại sao các clause sai lệch (63 mẫu khác biệt) lại gọi đến LLM:

### A. Bảng Phân Phối Triggers Trên Các Mẫu Sai Lệch

| Điều Kiện Kích Hoạt (Trigger) | Cứu Sót (`FN_resolved_by_LLM`) | Lỗi Sai Mới (`FP_introduced_by_LLM`) | Tổng số ca | Đánh giá hiệu quả |
|---|:---:|:---:|:---:|---|
| **`C0`** (Có reference nhưng Regex không phát hiện từ khóa hành động nào) | 3 | 6 | 9 | **Hiệu quả tốt:** Cứu được 3 ca sót, tỷ lệ lỗi sai đi kèm ở mức chấp nhận được. |
| **`C1`** (Quét được từ khóa hành động nhưng Regex Matcher không ghép được mục tiêu nào) | 2 | 7 | 9 | **Hiệu quả tốt:** Giúp cứu các câu đảo ngữ phức tạp nơi từ khóa và mục tiêu ở xa nhau. |
| **`C3`** (Regex Matcher bỏ sót từ 2 reference trở lên không ghép cặp được) | 1 | 11 | 12 | **Kém hiệu quả:** LLM bị ép ghép các reference phụ vào relation chính, sinh nhiều lỗi ảo. |
| **`C4b`** (Nhập nhằng: Vừa có dẫn chiếu vừa có hành động sửa đổi/bãi bỏ trong câu) | 3 | 16 | 19 | **Kém hiệu quả:** LLM bị lẫn lộn giữa quan hệ dẫn chiếu phụ và hành động tác động chính. |
| **`C4b, C5`** (Kết hợp cả nhập nhằng hành động và reference nội bộ thiếu tên luật gốc) | 0 | 5 | 5 | **Không hiệu quả:** Chỉ sinh thêm lỗi sai mà không cứu được ca nào. |
| **`C5`** (Chỉ chứa reference nội bộ như *"Điều này"*, *"khoản này"* cần khôi phục văn bản cha) | 0 | 9 | 9 | **Không hiệu quả:** Chỉ sinh thêm lỗi sai do context noise, không cứu được ca nào. |
| **Tổng cộng** | **9** | **54** | **63** | |

### B. Phân Tích Chi Tiết Từng Trigger

1. **Nhóm Trigger Cực Kỳ Hiệu Quả (`C0` & `C1`):**
   * **Bản chất:** Cứu được **5 / 9 ca** (hơn 55% tổng số ca cứu). Khi Regex thuần không phát hiện được relation nào hoặc không ghép cặp được do khoảng cách chữ quá xa, LLM đọc hiểu ngữ nghĩa toàn văn rất tốt để cứu các ca này.
   * **Giải pháp cải thiện:** Giữ nguyên trigger `C0` & `C1`, nhưng cần áp dụng bộ lọc Regex hậu xử lý lên đầu ra LLM để giảm bớt 13 ca lỗi sai (FP) đi kèm.

2. **Nhóm Trigger Kém Hiệu Quả (`C3` & `C4b`):**
   * **Bản chất:** Chỉ cứu được **4 ca** nhưng trả giá bằng **27 ca lỗi sai**. Ở `C3`, các reference thừa thường là các tài liệu đi kèm hoặc văn bản phụ; LLM có xu hướng "áp đặt" relation chính lên các văn bản phụ này. Ở `C4b`, LLM bị lẫn lộn nhãn giữa dẫn chiếu thông thường (`dan_chieu`) và hành động chính (`sua_doi_bo_sung`).
   * **Giải pháp cải thiện:** Thắt chặt ngưỡng kích hoạt `C3` (chỉ kích hoạt khi chênh lệch >= 3 reference và khoảng cách giữa chúng gần từ khóa hành động). Ở `C4b`, chỉ kích hoạt khi phát hiện từ dẫn chiếu và hành động nằm trong cùng một phân cú pháp (segment) thay vì toàn câu.

3. **Nhóm Trigger Hoàn Toàn Gây Hại (`C5` & `C4b, C5`):**
   * **Bản chất:** **Cứu được 0 ca** nhưng sinh ra thêm **14 ca lỗi sai**. Khi gặp reference nội bộ dạng *"Điều này"*, *"khoản này"*, bộ mã nguồn tĩnh `InternalReferenceResolver` đã giải quyết tốt. Khi kích hoạt LLM và truyền thêm context cha/ông, mô hình bị nhiễu và bóc cả những văn bản nằm ở tiêu đề cha làm quan hệ ảo.
   * **Giải pháp cải thiện:** **Loại bỏ hoàn toàn trigger `C5`** khỏi điều kiện gọi LLM. Việc này giúp loại bỏ ngay lập tức 14 lỗi FP lớn nhất của LLM mà không ảnh hưởng đến Recall.

---

## 7. Đề Xuất Hướng Cải Thiện Tiếp Theo

Dựa trên thống kê sai lệch trên, đây là lộ trình tối ưu hóa mà không cần phải thay đổi cấu trúc lớn:

1. **Loại bỏ Trigger C5:**
   * Sửa đổi `RelationsExtractor._evaluate_llm_trigger` để không kích hoạt LLM Fallback nếu chỉ thỏa mãn điều kiện `C5`.
2. **Áp dụng bộ lọc Regex Edge Cases lên kết quả của LLM:**
   * Kết quả đầu ra từ LLM cần chạy qua Bộ lọc số 4 (ví dụ loại bỏ `FORM_IDENTIFIER_PREFIX` như *Mẫu số X*, loại bỏ chú thích sửa đổi provenance `AMENDMENT_PROVENANCE`). Điều này sẽ triệt tiêu ngay lập tức khoảng 20-30% lỗi FP do LLM ảo tưởng.
3. **Điều chỉnh tham số Ngữ cảnh đầu vào LLM:**
   * Hạn chế đưa `grandparent_content` nếu clause_type là `khoan` hoặc `diem` trừ khi thực sự cần thiết, để giảm Context Noise khiến LLM bóc thừa văn bản tiêu đề.
4. **Cải tiến Prompt của LangExtract:**
   * Thêm các ví dụ Negative Examples (mẫu không được bóc) vào few-shot để dạy LLM loại trừ các văn bản lịch sử sửa đổi hoặc văn bản dẫn chiếu quy trình phụ.
