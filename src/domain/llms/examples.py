import re
from dataclasses import dataclass
from types import SimpleNamespace # For creating simple classes to hold example data without extra dependencies

try:
    import langextract as lx
except Exception:  # pragma: no cover - optional dependency
    @dataclass
    class _Extraction:
        extraction_class: str
        extraction_text: str
        attributes: dict

    @dataclass
    class _ExampleData:
        text: str
        extractions: list

    lx = SimpleNamespace(
        data=SimpleNamespace(
            Extraction=_Extraction,
            ExampleData=_ExampleData,
        )
    )

langextract_examples = [
    lx.data.ExampleData(
        text="""Căn cứ Luật Tổ chức Chính phủ ngày 19 tháng 6 năm 2015 đã được sửa đổi, bổ sung một số điều theo Luật số 47/2019/QH14;
    Căn cứ Luật Quản lý thuế số 38/2019/QH14 ngày 13 tháng 6 năm 2019;
    Căn cứ Nghị định số 01/2025/NĐ-CP ngày 01 tháng 01 năm 2025 của Chính phủ;""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Luật Tổ chức Chính phủ ngày 19 tháng 6 năm 2015",
            attributes={
                "type": "can_cu",
                "target": "Luật Tổ chức Chính phủ ngày 19 tháng 6 năm 2015",
                "evidence": "Căn cứ Luật Tổ chức Chính phủ ngày 19 tháng 6 năm 2015 đã được sửa đổi, bổ sung một số điều theo Luật số 47/2019/QH14"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Luật Quản lý thuế số 38/2019/QH14 ngày 13 tháng 6 năm 2019",
            attributes={
                "type": "can_cu",
                "target": "Luật Quản lý thuế số 38/2019/QH14 ngày 13 tháng 6 năm 2019",
                "evidence": "Căn cứ Luật Quản lý thuế số 38/2019/QH14 ngày 13 tháng 6 năm 2019"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Nghị định số 01/2025/NĐ-CP ngày 01 tháng 01 năm 2025",
            attributes={
                "type": "can_cu",
                "target": "Nghị định số 01/2025/NĐ-CP ngày 01 tháng 01 năm 2025",
                "evidence": "Căn cứ Nghị định số 01/2025/NĐ-CP ngày 01 tháng 01 năm 2025 của Chính phủ"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Căn cứ khoản 2 Điều 14 Luật Ban hành văn bản quy phạm pháp luật số 80/2015/QH13 đã được sửa đổi, bổ sung một số điều theo Luật số 63/2020/QH14;""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 2 Điều 14 Luật Ban hành văn bản quy phạm pháp luật số 80/2015/QH13",
            attributes={
                "type": "can_cu",
                "target": "khoản 2 Điều 14 Luật Ban hành văn bản quy phạm pháp luật số 80/2015/QH13",
                "evidence": "Căn cứ khoản 2 Điều 14 Luật Ban hành văn bản quy phạm pháp luật số 80/2015/QH13 đã được sửa đổi, bổ sung một số điều theo Luật số 63/2020/QH14"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Nguyên tắc hỗ trợ; phạm vi, đối tượng áp dụng; điều kiện, nguồn vốn hỗ trợ đối với các nội dung được phép kéo dài thực hiện theo Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016 và các nội dung đã được sửa đổi, bổ sung tại Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019 của Hội đồng nhân dân tỉnh.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016",
            attributes={
                "type": "dan_chieu",
                "target": "Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016",
                "evidence": "Nguyên tắc hỗ trợ; phạm vi, đối tượng áp dụng; điều kiện, nguồn vốn hỗ trợ đối với các nội dung được phép kéo dài thực hiện theo Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019",
            attributes={
                "type": "dan_chieu",
                "target": "Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019",
                "evidence": "các nội dung đã được sửa đổi, bổ sung tại Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019 của Hội đồng nhân dân tỉnh"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Không nộp hồ sơ đăng ký thuế; không nộp hồ sơ khai thuế hoặc nộp hồ sơ khai thuế sau 90 ngày, kể từ ngày hết thời hạn nộp hồ sơ khai thuế quy định tại các Khoản 1, 2, 3 và Khoản 5 Điều 32 của Luật quản lý thuế hoặc kể từ ngày hết thời hạn gia hạn nộp hồ sơ khai thuế quy định tại Điều 33 Luật quản lý thuế.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Khoản 1",
            attributes={
                "type": "dan_chieu",
                "target": "khoản 1 Điều 32 của Luật quản lý thuế",
                "evidence": "quy định tại các Khoản 1, 2, 3 và Khoản 5 Điều 32 của Luật quản lý thuế"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="2",
            attributes={
                "type": "dan_chieu",
                "target": "khoản 2 Điều 32 của Luật quản lý thuế",
                "evidence": "quy định tại các Khoản 1, 2, 3 và Khoản 5 Điều 32 của Luật quản lý thuế"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="3",
            attributes={
                "type": "dan_chieu",
                "target": "khoản 3 Điều 32 của Luật quản lý thuế",
                "evidence": "quy định tại các Khoản 1, 2, 3 và Khoản 5 Điều 32 của Luật quản lý thuế"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Khoản 5 Điều 32 của Luật quản lý thuế",
            attributes={
                "type": "dan_chieu",
                "target": "khoản 5 Điều 32 của Luật quản lý thuế",
                "evidence": "quy định tại các Khoản 1, 2, 3 và Khoản 5 Điều 32 của Luật quản lý thuế"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Điều 33 Luật quản lý thuế",
            attributes={
                "type": "dan_chieu",
                "target": "Điều 33 Luật quản lý thuế",
                "evidence": "quy định tại Điều 33 Luật quản lý thuế"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Sửa đổi, bổ sung một số điều, khoản, điểm của Luật Nhà ở số 27/2023/QH15 đã được sửa đổi, bổ sung một số điều theo Luật số 43/2024/QH15, Luật số 47/2024/QH15, Luật số 84/2025/QH15, Luật số 90/2025/QH15 và Luật số 93/2025/QH15 như sau:""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Luật Nhà ở số 27/2023/QH15",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "Luật Nhà ở số 27/2023/QH15",
                "evidence": "Sửa đổi, bổ sung một số điều, khoản, điểm của Luật Nhà ở số 27/2023/QH15 đã được sửa đổi, bổ sung một số điều theo Luật số 43/2024/QH15, Luật số 47/2024/QH15, Luật số 84/2025/QH15, Luật số 90/2025/QH15 và Luật số 93/2025/QH15"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Sửa đổi, bổ sung một số điều của Luật Công chứng
    3. Sửa đổi, bổ sung điểm b và điểm c khoản 2 Điều 69 như sau:""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="điểm b",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "điểm b khoản 2 Điều 69 Luật Công chứng",
                "evidence": "Sửa đổi, bổ sung điểm b và điểm c khoản 2 Điều 69"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="điểm c khoản 2 Điều 69",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "điểm c khoản 2 Điều 69 Luật Công chứng",
                "evidence": "Sửa đổi, bổ sung điểm b và điểm c khoản 2 Điều 69"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Thay thế cụm từ bằng cụm từ tại điểm c khoản 1 Điều 20, khoản 2 Điều 21 và điểm c khoản 1 Điều 47 Luật Giao dịch điện tử số 20/2023/QH15.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="điểm c khoản 1 Điều 20",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "điểm c khoản 1 Điều 20 Luật Giao dịch điện tử số 20/2023/QH15",
                "evidence": "Thay thế cụm từ bằng cụm từ tại điểm c khoản 1 Điều 20, khoản 2 Điều 21 và điểm c khoản 1 Điều 47 Luật Giao dịch điện tử số 20/2023/QH15"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 2 Điều 21",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "khoản 2 Điều 21 Luật Giao dịch điện tử số 20/2023/QH15",
                "evidence": "Thay thế cụm từ bằng cụm từ tại điểm c khoản 1 Điều 20, khoản 2 Điều 21 và điểm c khoản 1 Điều 47 Luật Giao dịch điện tử số 20/2023/QH15"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="điểm c khoản 1 Điều 47 Luật Giao dịch điện tử số 20/2023/QH15",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "điểm c khoản 1 Điều 47 Luật Giao dịch điện tử số 20/2023/QH15",
                "evidence": "Thay thế cụm từ bằng cụm từ tại điểm c khoản 1 Điều 20, khoản 2 Điều 21 và điểm c khoản 1 Điều 47 Luật Giao dịch điện tử số 20/2023/QH15"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Điều khoản thi hành
    Luật Dự trữ quốc gia số 22/2012/QH13 được sửa đổi, bổ sung một số điều theo Luật số 21/2017/QH14 và Luật số 56/2024/QH15 hết hiệu lực kể từ ngày Luật này có hiệu lực thi hành.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Luật Dự trữ quốc gia số 22/2012/QH13",
            attributes={
                "type": "thay_the",
                "target": "Luật Dự trữ quốc gia số 22/2012/QH13",
                "evidence": "Luật Dự trữ quốc gia số 22/2012/QH13 được sửa đổi, bổ sung một số điều theo Luật số 21/2017/QH14 và Luật số 56/2024/QH15 hết hiệu lực kể từ ngày Luật này có hiệu lực thi hành"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Điều 1. Bãi bỏ toàn bộ các nghị định
    Bãi bỏ toàn bộ các nghị định sau đây:
    1. Nghị định số 105/2006/NĐ-CP ngày 22 tháng 9 năm 2006 của Chính phủ quy định chi tiết và hướng dẫn thi hành một số điều của Luật Sở hữu trí tuệ về bảo vệ quyền sở hữu trí tuệ và quản lý nhà nước về sở hữu trí tuệ.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Nghị định số 105/2006/NĐ-CP ngày 22 tháng 9 năm 2006",
            attributes={
                "type": "bai_bo",
                "target": "Nghị định số 105/2006/NĐ-CP ngày 22 tháng 9 năm 2006",
                "evidence": "Bãi bỏ toàn bộ các nghị định sau đây: 1. Nghị định số 105/2006/NĐ-CP ngày 22 tháng 9 năm 2006 của Chính phủ"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Điều 23. Bãi bỏ, thay thế một số cụm từ tại Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013 của Chính phủ:
    1. Bãi bỏ khoản 2 Điều 27a Nghị định này.
    2. Thay thế cụm từ bằng tại Điều 8b và Điều 8c Nghị định này.
    3. Thay thế cụm từ bằng tại Điều 17 Nghị định này.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 2 Điều 27a",
            attributes={
                "type": "bai_bo",
                "target": "khoản 2 Điều 27a Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013",
                "evidence": "Bãi bỏ khoản 2 Điều 27a Nghị định này"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Điều 8b",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "Điều 8b Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013",
                "evidence": "Thay thế cụm từ bằng tại Điều 8b và Điều 8c Nghị định này"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Điều 8c",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "Điều 8c Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013",
                "evidence": "Thay thế cụm từ bằng tại Điều 8b và Điều 8c Nghị định này"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Điều 17",
            attributes={
                "type": "sua_doi_bo_sung",
                "target": "Điều 17 Nghị định số 162/2013/NĐ-CP ngày 12 tháng 11 năm 2013",
                "evidence": "Thay thế cụm từ bằng tại Điều 17 Nghị định này"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Điều 1. Hủy bỏ hiệu lực thi hành các Quyết định của UBND tỉnh vì không còn phù hợp với Nghị định số 80/2005/NĐ-CP ngày 10/6/2005 của Chính phủ.
    - Quyết định số 12/2005/QĐ-UB ngày 15/5/2005 về chính sách hỗ trợ nhà ở cho cán bộ công chức.
    - Quyết định số 45/2007/QĐ-UB ngày 10/8/2007 về mức thu học phí các trường công lập.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Quyết định số 12/2005/QĐ-UB",
            attributes={
                "type": "huy_bo",
                "target": "Quyết định số 12/2005/QĐ-UB ngày 15/5/2005",
                "evidence": "Hủy bỏ hiệu lực thi hành các Quyết định...Quyết định số 12/2005/QĐ-UB ngày 15/5/2005 về chính sách hỗ trợ nhà ở cho cán bộ công chức"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Quyết định số 45/2007/QĐ-UB ngày 10/8/2007",
            attributes={
                "type": "huy_bo",
                "target": "Quyết định số 45/2007/QĐ-UB ngày 10/8/2007",
                "evidence": "Hủy bỏ hiệu lực thi hành các Quyết định...Quyết định số 45/2007/QĐ-UB ngày 10/8/2007 về mức thu học phí các trường công lập"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Đình chỉ thi hành Quyết định số 174/2004/QĐ-UB ngày 17/9/2004 của Ủy ban nhân dân tỉnh Khánh Hòa về việc ban hành quy định về quy trình thủ tục thực hiện cấp lại thuế thu nhập doanh nghiệp đã nộp khi được hưởng chính sách ưu đãi đầu tư.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Quyết định số 174/2004/QĐ-UB ngày 17/9/2004",
            attributes={
                "type": "dinh_chi",
                "target": "Quyết định số 174/2004/QĐ-UB ngày 17/9/2004",
                "evidence": "Đình chỉ thi hành Quyết định số 174/2004/QĐ-UB ngày 17/9/2004 của Ủy ban nhân dân tỉnh Khánh Hòa"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Đính chính một số nội dung của ban hành kèm theo Quyết định số 04/2016/QĐ-UBND ngày 23/3/2016 của UBND tỉnh Hải Dương như sau:
    Tại Mục b, Khoản 6, Điều 4: Sửa cụm từ thành.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Khoản 6, Điều 4",
            attributes={
                "type": "dinh_chinh",
                "target": "điểm b khoản 6 Điều 4 Quyết định số 04/2016/QĐ-UBND ngày 23/3/2016",
                "evidence": "Đính chính một số nội dung của ban hành kèm theo Quyết định số 04/2016/QĐ-UBND ngày 23/3/2016 của UBND tỉnh Hải Dương như sau: Tại Mục b, Khoản 6, Điều 4"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Điều 1. Phạm vi điều chỉnh
    Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số điều của Luật Dược ngày 21 tháng 11 năm 2024 và Nghị định số 163/2025/NĐ-CP ngày 29 tháng 6 năm 2025 của Chính phủ quy định chi tiết một số điều và biện pháp để tổ chức, hướng dẫn thi hành Luật Dược, bao gồm:""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Luật Dược ngày 06 tháng 4 năm 2016",
            attributes={
                "type": "huong_dan",
                "target": "Luật Dược ngày 06 tháng 4 năm 2016",
                "evidence": "Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược ngày 06 tháng 4 năm 2016"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Luật sửa đổi, bổ sung một số điều của Luật Dược ngày 21 tháng 11 năm 2024",
            attributes={
                "type": "huong_dan",
                "target": "Luật sửa đổi, bổ sung một số điều của Luật Dược ngày 21 tháng 11 năm 2024",
                "evidence": "Thông tư này quy định chi tiết và hướng dẫn thi hành một số điều của Luật Dược ngày 06 tháng 4 năm 2016 và Luật sửa đổi, bổ sung một số điều của Luật Dược ngày 21 tháng 11 năm 2024"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Nghị định số 163/2025/NĐ-CP ngày 29 tháng 6 năm 2025",
            attributes={
                "type": "huong_dan",
                "target": "Nghị định số 163/2025/NĐ-CP ngày 29 tháng 6 năm 2025",
                "evidence": "và Nghị định số 163/2025/NĐ-CP ngày 29 tháng 6 năm 2025"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Điều 1. Phạm vi điều chỉnh
    Nghị định này quy định chi tiết khoản 4 và khoản 5 Điều 60, điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13 và điểm a Khoản 4 Điều 1 Luật số 44/2024/QH15.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 4",
            attributes={
                "type": "quy_dinh_chi_tiet",
                "target": "Khoản 4 Điều 60 Luật Dược số 105/2016/QH13",
                "evidence": "Nghị định này quy định chi tiết khoản 4 và khoản 5 Điều 60, điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 5 Điều 60",
            attributes={
                "type": "quy_dinh_chi_tiet",
                "target": "khoản 5 Điều 60 Luật Dược số 105/2016/QH13",
                "evidence": "Nghị định này quy định chi tiết khoản 4 và khoản 5 Điều 60, điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13",
            attributes={
                "type": "quy_dinh_chi_tiet",
                "target": "Điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13",
                "evidence": "Nghị định này quy định chi tiết khoản 4 và khoản 5 Điều 60, điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="điểm a Khoản 4 Điều 1 Luật số 44/2024/QH15",
            attributes={
                "type": "quy_dinh_chi_tiet",
                "target": "điểm a Khoản 4 Điều 1 Luật số 44/2024/QH15",
                "evidence": "Nghị định này quy định chi tiết khoản 4 và khoản 5 Điều 60, điểm d khoản 26 Điều 2 Luật Dược số 105/2016/QH13 và điểm a Khoản 4 Điều 1 Luật số 44/2024/QH15"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Kéo dài thời gian thực hiện các nội dung và mức hỗ trợ: giống lúa thuần (tiêu chuẩn xác nhận); giống ngô lai; phát triển cây ăn quả tập trung và cải tạo vườn tạp; chuyển đổi phương thức chăn nuôi (trâu, bò, ngựa) và cải tạo đàn gia súc; vôi cải tạo đất ruộng; nuôi tôm, cá lồng; khai hoang ruộng nước; phát triển cơ giới hóa nông nghiệp trong chính sách hỗ trợ phát triển sản xuất nông nghiệp trên địa bàn tỉnh được quy định tại Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016, Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019 của Hội đồng nhân dân tỉnh đến hết ngày 31 tháng 12 năm 2022.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016",
            attributes={
                "type": "keo_dai_hieu_luc",
                "target": "Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016",
                "evidence": "Kéo dài thời gian thực hiện...được quy định tại Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019",
            attributes={
                "type": "keo_dai_hieu_luc",
                "target": "Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019",
                "evidence": "Kéo dài thời gian thực hiện...được quy định tại Nghị quyết số 33/2016/NQ-HĐND ngày 28/7/2016, Nghị quyết số 40/2019/NQ-HĐND ngày 11/12/2019"
            }
        ),
        ]
    ),

    lx.data.ExampleData(
        text="""Ngưng hiệu lực thi hành khoản 8, khoản 9 và khoản 10 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016 của Thống đốc Ngân hàng Nhà nước Việt Nam.""",
        extractions=[
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 8",
            attributes={
                "type": "ngung_hieu_luc",
                "target": "khoản 8 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016",
                "evidence": "Ngưng hiệu lực thi hành khoản 8, khoản 9 và khoản 10 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 9",
            attributes={
                "type": "ngung_hieu_luc",
                "target": "khoản 9 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016",
                "evidence": "Ngưng hiệu lực thi hành khoản 8, khoản 9 và khoản 10 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016"
            }
        ),
        lx.data.Extraction(
            extraction_class="Entity",
            extraction_text="khoản 10 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016",
            attributes={
                "type": "ngung_hieu_luc",
                "target": "khoản 10 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016",
                "evidence": "Ngưng hiệu lực thi hành khoản 8, khoản 9 và khoản 10 Điều 8 Thông tư số 39/2016/TT-NHNN ngày 30 tháng 12 năm 2016"
            }
        ),
        ]
    )
]


from src.shared.text.normalizers import unidecode

# These patterns are designed to capture common legal document types in Vietnamese legal texts, such as "Luật", "Nghị định", "Thông tư", etc. They can be further refined based on specific legal document structures and naming conventions.
_DOC_KEY_PATTERNS = (
    ("luat", r"\bluat\b"),
    ("boluat", r"\bbo\s+luat\b"),
    ("hienphap", r"\bhien\s+phap\b"),
    ("nghidinh", r"\bnghi\s+dinh\b"),
    ("nghiquyet", r"\bnghi\s+quyet\b"),
    ("nghiquyetlientich", r"\bnghi\s+quyet\s+lien\s+tich\b"),
    ("thongtu", r"\bthong\s+tu\b"),
    ("thongtulientich", r"\bthong\s+tu\s+lien\s+tich\b"),
    ("congvan", r"\bcong\s+van\b"),
    ("congdien", r"\bcong\s+dien\b"),
    ("dieuuocquocte", r"\bdieu\s+uoc\s+quoc\s+te\b"),
    ("huongdan", r"\bhuong\s+dan\b"),
    ("kehoach", r"\bke\s+hoach\b"),
    ("quyetdinh", r"\bquyet\s+dinh\b"),
    ("chithi", r"\bchi\s+thi\b"),
    ("phaplenh", r"\bphap\s+lenh\b"),
    ("lenh", r"\blenh\b"),
    ("saclenh", r"\bsac\s+lenh\b"),
    ("vanban", r"\bvan\s+ban\b"),
)

# These patterns are designed to capture common clause reference formats in legal texts, such as "Điều 69", "khoản 2", "điểm b", etc. They can be further refined based on specific legal document structures.
_CLAUSE_PATTERNS = (
    ("dieu", r"\bdieu\s+[0-9a-z/.-]+\b"),
    ("khoan", r"\bkhoan\s+[0-9a-z/.-]+\b"),
    ("diem", r"\bdiem\s+[0-9a-z/.-]+\b"),
)


def _build_reference_node(information: str, context_text: str = "") -> dict:
    """
    Build one node that matches BaseExtractor reference payload shape.

    Args:
        information: The text of the reference node (e.g. "Quyết định số 67...", "Điều 1").
        context_text: The full example sentence text used to locate the exact position.
    """
    information = information.strip()
    start_idx = context_text.find(information) if context_text and information else -1
    return {
        "information": information,
        "position_start": start_idx if start_idx != -1 else None,
        "position_end": start_idx + len(information) if start_idx != -1 else None,
    }


def _derive_reference_payload(target: str, context_text: str = "") -> dict:
    """
    Derive relation-match style attributes for _build_relations.

    Args:
        target: The full entity text (e.g. "điểm b khoản 2 Điều 69 Luật Công chứng").
                Used to derive the reference structure (doc key, clause components).
        context_text: The full example sentence text (example.text).
                      Used to locate the exact character positions of sub-nodes.

    Note:
        ``extraction_text`` (the short highlight span) is intentionally NOT used here.
        ``target`` contains the full structured entity; ``context_text`` is the anchor
        for computing accurate offsets.
    """
    source_text = target or ""
    if not source_text:
        return {}

    normalized_text = unidecode(source_text).lower()
    payload: dict = {}
    reference: dict = {}
    reference_doc_key = ""

    for doc_key, pattern in _DOC_KEY_PATTERNS:
        doc_match = re.search(pattern, normalized_text, re.IGNORECASE)
        if doc_match:
            reference_doc_key = doc_key
            # Slice from the doc keyword onwards to get the full doc information text
            # (e.g. "Quyết định số 67/QĐ-UBND ngày 10 tháng 01 năm 2011")
            doc_information = source_text[doc_match.start():].strip()
            break

    if not reference_doc_key:
        return payload

    payload["reference_doc_key"] = reference_doc_key
    payload["reference_doc_information"] = doc_information
    # Find the doc node position in context_text — this is the anchor for clause searches
    reference[reference_doc_key] = _build_reference_node(doc_information, context_text)
    doc_node = reference[reference_doc_key]
    # doc_pos: where the document keyword begins in the full clause content,
    # used to anchor the search for clause components that appear BEFORE it.
    doc_pos_in_context = doc_node.get("position_start")

    for clause_key, pattern in _CLAUSE_PATTERNS:
        clause_match = re.search(pattern, normalized_text, re.IGNORECASE)
        # Slice from source_text (target) to preserve Vietnamese casing (e.g. Điều, Khoản, điểm)
        clause_information = source_text[clause_match.start():clause_match.end()].strip() if clause_match else ""
        payload[f"reference_{clause_key}_information"] = clause_information
        if clause_information:
            if context_text and doc_pos_in_context is not None:
                # Use rfind to get the RIGHTMOST occurrence of clause_information that
                # appears BEFORE the document keyword
                found_pos = context_text.rfind(clause_information, 0, doc_pos_in_context)
                if found_pos == -1:
                    # Fallback: if not found before doc, look after (rare edge case)
                    found_pos = context_text.find(clause_information, doc_pos_in_context)
                reference[clause_key] = {
                    "information": clause_information,
                    "position_start": found_pos if found_pos != -1 else None,
                    "position_end": found_pos + len(clause_information) if found_pos != -1 else None,
                }
            else:
                reference[clause_key] = _build_reference_node(clause_information, context_text)

    payload["reference"] = reference

    return payload



def _convert_examples_to_relation_match_schema(example_list: list) -> list:
    """
    Convert legacy Entity examples to relation-match oriented output schema.

    - Keep ``type/target/evidence`` unchanged.
    - Add ``relation_type`` and structured reference fields.
    - Switch ``extraction_class`` to ``RELATION_MATCH``.
    """
    converted_examples = []
    for example in example_list or []:
        # context_text is the full sentence of the example used to locate character offsets
        context_text = getattr(example, "text", "") or ""
        converted_extractions = []
        for extraction in getattr(example, "extractions", []) or []:
            attributes = dict(getattr(extraction, "attributes", {}) or {})
            relation_type = attributes.get("type")
            if not relation_type:
                continue

            # target is the full structured entity text
            # extraction_text is only a short highlighted span (may not contain full entity)
            target = attributes.get("target", "")
            structured_reference = _derive_reference_payload(
                target=target,
                context_text=context_text,
            )
            if not structured_reference.get("reference"):
                continue

            attributes.update({
                "relation_type": relation_type,
                **structured_reference,
            })

            converted_extractions.append(
                lx.data.Extraction(
                    extraction_class="RELATION_MATCH",
                    extraction_text=getattr(extraction, "extraction_text", ""),
                    attributes=attributes,
                )
            )

        converted_examples.append(
            lx.data.ExampleData(
                text=context_text,
                extractions=converted_extractions,
            )
        )

    return converted_examples


langextract_examples = _convert_examples_to_relation_match_schema(langextract_examples)
