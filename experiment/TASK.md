Tôi muốn thực hiện một nghiên cứu và proof-of-concept để đánh giá tính khả thi của việc sử dụng LLM cho bài toán trích xuất quan hệ trong văn bản pháp luật Việt Nam.

Bối cảnh hiện tại:

* Hệ thống đang sử dụng rule-based và regex để nhận diện quan hệ.
* Mục tiêu của sprint hiện tại là nâng precision lên mức gần như tuyệt đối, hạn chế tối đa false positives.
* Chúng tôi sẵn sàng chấp nhận giảm recall ở tầng rule nếu cần.
* Ý tưởng đang được cân nhắc là sử dụng LLM để xử lý các trường hợp mà rule không bao phủ được nhằm kéo recall lên.
* Tuy nhiên các thử nghiệm trước đây cho thấy LLM có thể tạo ra false positives, dẫn đến việc làm giảm precision chung của hệ thống.
* Dữ liệu thực tế có quy mô khoảng 600.000 văn bản pháp luật cấp trung ương, địa phương với rất nhiều cách diễn đạt khác nhau.

Tôi muốn trước tiên đánh giá độc lập khả năng của LLM trước khi quyết định tích hợp vào hệ thống production.

Hãy thực hiện nghiên cứu trong folder `experiment`.

Nguồn lực có sẵn:

* Có thể sử dụng LLM nội bộ thông qua API.
* Có thể sử dụng LangExtract (https://github.com/google/langextract) nếu thấy phù hợp. Đã thực hiện thử trước đó ở folder src/domain/llms/
* Không bắt buộc phải dùng LangExtract. Nếu có giải pháp tốt hơn, hãy đề xuất và chứng minh bằng lập luận kỹ thuật.

Tôi muốn bạn tiếp cận vấn đề như một AI Engineer đang thiết kế một hệ thống Information Extraction production-grade, không phải chỉ là một demo dùng prompt.

Các câu hỏi tôi muốn được trả lời:

1. LLM có thực sự phù hợp cho bài toán trích xuất quan hệ trong văn bản pháp luật Việt Nam hay không?
2. Những rủi ro lớn nhất khi dùng LLM cho bài toán này là gì?
3. Có những kỹ thuật nào để tối đa hóa precision và kiểm soát false positives?
4. Có những kiến trúc nào nên cân nhắc ngoài cách tiếp cận "đưa văn bản vào LLM rồi lấy kết quả extraction"?
5. Trong bối cảnh ưu tiên precision hơn recall, kiến trúc nào có xác suất thành công cao nhất?
6. Nếu triển khai production, nên thiết kế hệ thống như thế nào?

Tôi muốn bạn:

* Research các phương pháp hiện đại liên quan đến relation extraction, information extraction, legal NLP, legal knowledge graph và hybrid rule-LLM systems.
* Đề xuất một hoặc nhiều hướng tiếp cận khả thi.
* Thiết kế các thử nghiệm để kiểm chứng các giả thuyết quan trọng.
* Chủ động đề xuất benchmark, phương pháp đánh giá và error analysis.
* Thực hiện proof-of-concept trong folder `experiment`.
* Tổng hợp kết quả thành một báo cáo kỹ thuật có thể dùng để trình bày với Engineering Manager hoặc Tech Lead.

Đừng mặc định rằng LLM là lời giải đúng. Bộ đánh giá dùng evaluation/dataset/golden_eval.csv. Lưu ý rằng, có thể bộ đánh giá lỗi gán tay một số mẫu do con người gán.

Nếu sau khi nghiên cứu và thử nghiệm, kết luận hợp lý nhất là không nên dùng LLM hoặc chỉ nên dùng LLM ở một vai trò rất hạn chế thì hãy nêu rõ và đưa ra bằng chứng.

Tôi quan tâm tới các quyết định kỹ thuật có thể đứng vững khi triển khai trên dữ liệu thực tế quy mô lớn, hơn là các kết quả đẹp trên một tập dữ liệu nhỏ.
