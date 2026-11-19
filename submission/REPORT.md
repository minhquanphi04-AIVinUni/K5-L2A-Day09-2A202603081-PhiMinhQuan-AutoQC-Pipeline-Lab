# Báo cáo Day 09 — Phí Minh Quân, 2A202603081

## 1. Kết luận trước
Pipeline đưa ra kết luận **RELEASE**.
Từ 224 ảnh đầu vào trong lô `data/raw/`, pipeline đã quét và loại bỏ 21 ảnh lỗi ở cửa vào (intake: hỏng, quá nhỏ, trùng lặp, rò rỉ test), tiếp nhận 203 ảnh hợp lệ. Sau quá trình sửa lỗi tự động và hoàn thành duyệt 80 ảnh theo ngân sách mô phỏng, toàn bộ 0 lỗi bắt buộc (severity ERROR) đã được giải quyết triệt để, tỉ lệ ảnh còn cảnh báo đạt **7.88%** (16/203 ảnh), thấp hơn ngưỡng Hold 10.00%. Bộ dữ liệu sạch đã được xuất bản chính thức tại `submission/export/clean_v1/` kèm `manifest.json`.

## 2. Lỗi và phân việc
Tổng hợp các lỗi phát hiện trong vòng QC 1 (`02_error_list_v1`):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| BAD_CLASS_ID | 6 dòng | Máy (autofix) | ID lớp ngoài dải 0..3 (do gán nhầm hoặc gõ sai số), máy xoá dòng an toàn |
| BAD_CLASS_NAME | 2 lỗi | Máy (autofix) | Tên lớp trong `data.yaml` sai chuẩn ('Person', 'Bus'), máy chuẩn hoá lại theo cấu hình dự án |
| BAD_FORMAT | 3 dòng | Máy (autofix) | Dòng nhãn hỏng (chứa nan/inf hoặc thiếu cột), không parse được nên máy xoá dòng |
| BAD_SIZE | 3 ảnh | Máy (autofix) | Kích thước cạnh ngắn ảnh < 250px theo quy định dự án, máy loại bỏ ảnh và nhãn |
| BOX_OUT_OF_IMAGE | 8 dòng | Máy (autofix) | Box tràn viền quá dung sai cho phép, máy cắt tọa độ (clip) về [0, 1] |
| BOX_ZERO | 4 dòng | Máy (autofix) | Box có chiều rộng hoặc chiều cao <= 0, máy xoá dòng |
| CORRUPT_IMAGE | 2 ảnh | Máy (autofix) | File ảnh bị hỏng không đọc được (UnidentifiedImageError/OSError), máy loại bỏ ảnh |
| DUP_BOX | 7 dòng | Máy (autofix) | Box trùng lặp cùng lớp với box trước đó (IoU > 0.9), máy xoá dòng lặp phía sau |
| DUP_IMAGE_EXACT | 8 ảnh | Máy (autofix) | Ảnh trùng từng byte (trùng mã băm md5) với ảnh khác trong lô, máy loại bỏ ảnh trùng |
| DUP_IMAGE_NEAR | 3 ảnh | Máy (autofix) | Ảnh trùng gần đúng (perceptual hash phash <= 8), máy loại bỏ ảnh trùng |
| LEAK_TEST | 5 ảnh | Máy (autofix) | Ảnh bị trùng với kho test/val tham chiếu (rò rỉ dữ liệu đánh giá), máy loại bỏ ảnh |
| MISSING_LABEL_FILE | 6 ảnh | Người (review queue) | Ảnh thiếu file nhãn; máy không thể tự bịa nhãn nên chuyển người gán |
| BOX_HUGE | 3 dòng | Người | Cảnh báo box chiếm > 95% diện tích ảnh, người kiểm tra xem có phải gán nhầm toàn cảnh |
| BOX_TINY | 6 dòng | Người | Cảnh báo cạnh ngắn box < 12px, người kiểm tra xem vật quá nhỏ hay là nhiễu |
| CLASS_RARE | 4 lớp | Thống kê | Cảnh báo lớp xuất hiện ít trong lô (thông tin phân bố) |
| EMPTY_LABEL | 12 ảnh | Người | File nhãn rỗng, cần người xác nhận là ảnh nền thật hay bị quên gán |
| POSSIBLE_FALSE_POS | 29 dòng | Người | Box nhãn không khớp với vật thể nào model phát hiện, người kiểm tra box thừa |
| POSSIBLE_LOOSE_BOX | 12 dòng | Người | Box nhãn cùng lớp nhưng IoU < 0.5 so với model, người chỉnh lại viền box |
| POSSIBLE_MISSING | 32 dự đoán | Người | Model phát hiện vật thể tin cậy cao nhưng nhãn thiếu, người gán bổ sung |
| POSSIBLE_WRONG_CLASS | 14 dự đoán | Người | Model và nhãn lệch lớp nhau (IoU >= 0.5), người thẩm định lớp đúng |

**Giải thích hàng đợi duyệt (`05_review_queue.csv`):**
Hàng đợi ưu tiên dựa trên trọng số nguy cơ: lỗi `NEEDS_LABEL` có trọng số cao nhất (weight 10.0) nên cả 6 ảnh thiếu nhãn (`img_0031`, `img_0053`, `img_0126`, `img_0135`, `img_0170`, `img_0219`) lập tức được đẩy lên đầu hàng đợi. Tiếp theo là các ảnh có nhiều lỗi kết hợp (như `img_0020` có điểm ưu tiên 11.524 do vừa bị drop line vừa có missing và wrong class).
Với ngân sách 80 ảnh, người duyệt đã xem xét và xử lý toàn bộ 6 ảnh thiếu file nhãn (chuyển thành nhãn người, xóa bỏ mọi ERROR), đồng thời xử lý được phần lớn các lỗi ngữ nghĩa nghiêm trọng nhất (13/14 `POSSIBLE_WRONG_CLASS`, 31/32 `POSSIBLE_MISSING`, 11/12 `POSSIBLE_LOOSE_BOX`).

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | P: 1.00 → 1.00<br>R: 0.50 → 0.67 | Ngưỡng 2 quá khắt khe, bỏ sót ảnh biến đổi (recall chỉ 50%). Ngưỡng 8 tăng recall lên 67% mà vẫn giữ precision tuyệt đối (1.00). Không chọn 16 (dù calib đạt R=0.83) để tránh nguy cơ cờ sai và xóa nhầm ảnh thật trên lô raw lớn. |
| `second_opinion.conf` | 0.25 | 0.8 | P: 0.56 → 1.00 (WrongClass)<br>R: 0.83 → 0.83 (WrongClass)<br>P: 0.50 → 0.67 (Missing)<br>R: 1.00 → 0.75 (Missing) | Ở conf 0.25, checker quá nhạy sinh ra 273 cảnh báo giả (hàng đợi 145 ảnh), vượt quá ngân sách 80 ảnh khiến pipeline bị Hold (29.27% cảnh báo). Nâng lên 0.8 giúp tăng độ chính xác của các cảnh báo, thu hẹp hàng đợi về 102 ảnh, giúp người duyệt xử lý gọn trong 80 ảnh để đạt chuẩn Release. |

**Một chỗ calibration có thể đánh lừa bạn:**
Tập `data/calib/` chỉ gồm 39 ảnh với các lỗi được chèn nhân tạo theo quy tắc cố định. Khi sweep `duplicates.phash_dist`, giá trị 16 cho F1 cao nhất trên tập calib (0.91, bắt được 5/6 ảnh gần trùng). Tuy nhiên, trên tập dữ liệu thật `data/raw/` (224 ảnh đa dạng bối cảnh đường phố COCO), đặt khoảng cách phash quá lớn (>= 16) sẽ có rủi ro rất cao nhận nhầm hai ảnh chụp cùng góc phố hoặc cùng kiểu nền nhưng có các đối tượng xe cộ khác nhau thành ảnh trùng lặp. Vì hành động của máy ở đây là `remove_image` (xoá vĩnh viễn cả ảnh lẫn nhãn), chi phí của một False Positive (xoá nhầm ảnh hợp lệ) nguy hiểm hơn nhiều so với việc sót một ảnh gần trùng. Do đó, việc chọn ngưỡng an toàn `phash_dist = 8` là đánh đổi thận trọng cần thiết.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Chứng minh gate chặn đúng (Thực nghiệm Rework & Chặn xuất):**
Chạy thử nghiệm với ngân sách người duyệt bằng 0:
```bash
python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb
```
- **Kết quả thực tế**: Do không có người duyệt (`budget = 0`), 6 ảnh thiếu nhãn không được ai gán bổ sung. Sau bước autofix, 6 lỗi bắt buộc `MISSING_LABEL_FILE` vẫn còn nguyên. Cửa chặn gate đã phát hiện còn lỗi ERROR và đưa ra kết luận:
  `kết luận: REWORK — Còn 6 lỗi bắt buộc (severity ERROR).`
- **Mã thoát**: Trả về đúng mã `20`.
- **Cửa chặn hoạt động**: Pipeline xuất thông báo `KHÔNG xuất: còn lỗi bắt buộc (Rework) — trả về bước 3` và hoàn toàn không sinh thư mục `work/exp_nb`. Điều này chứng minh cửa chặn đã ngăn chặn triệt để việc phát hành dữ liệu khi còn lỗi nghiêm trọng.

**(b) Các điểm mù mà pipeline KHÔNG bắt được:**
1. **Box lỏng nhẹ hoặc lệch góc trong ngưỡng chấp nhận ($0.5 \le \text{IoU} < 0.9$):** Pipeline đặt ngưỡng `iou_loose = 0.5`. Nếu nhãn người vẽ thừa nền hoặc thiếu một phần đuôi xe nhưng vẫn đạt IoU trên 0.5 so với model checker, hệ thống sẽ coi là hợp lệ và bỏ qua, không thể bắt được độ lỏng tinh tế này.
2. **Nhầm lẫn các lớp có ngoại hình tương đồng mà model checker cũng bị nhầm:** Giữa lớp `truck` và `bus`, hoặc giữa `car` (xe con 7 chỗ) và `truck` (xe bán tải), nếu cả nhãn ban đầu và model YOLO26l đều nhầm lẫn về cùng một lớp sai, pipeline sẽ coi như có sự đồng thuận và hoàn toàn im lặng.
3. **Ảnh trùng bị biến đổi nặng:** Ảnh bị xoay góc lớn, crop trên 50% diện tích hoặc chỉnh màu tương phản mạnh khiến perceptual hash vượt quá ngưỡng khoảng cách 8 sẽ lọt qua cửa vào intake mà không bị phát hiện.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy do môi trường thực thi hiện tại là máy trạm CPU cá nhân không có GPU chuyên dụng. Phần huấn luyện so sánh mô hình YOLO26n (raw vs clean, 2 seed, 20 epoch) được thiết kế chạy trên môi trường Google Colab T4 (~20 phút) theo notebook `notebooks/day09_train_compare.ipynb`. Báo cáo này tập trung hoàn thành và kiểm chứng toàn bộ phần lõi chất lượng dữ liệu của Pipeline AutoQC theo tiêu chuẩn kiểm định `make check-core`.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối cùng:**
**RELEASE** — Bộ dữ liệu sạch `clean_v1` đáp ứng đầy đủ tiêu chí chất lượng: 0 lỗi bắt buộc, tỉ lệ ảnh có cảnh báo sau người duyệt chỉ còn 7.88% (< 10.00%). Nếu sau này ngân sách người duyệt bị cắt giảm dưới 80 ảnh khiến tỉ lệ cảnh báo vượt 10% (Hold), đội ngũ cần hoặc bổ sung ngân sách duyệt thêm các ảnh cảnh báo ngữ nghĩa, hoặc lọc bỏ các ảnh có cảnh báo phức tạp trước khi phát hành.

**(b) Ghi chú sử dụng AI:**
- **Prompt chính:** *"Viết 4 module pipeline/checks/label_format.py, pipeline/steps/gate.py, pipeline/steps/autofix.py, pipeline/checks/second_opinion.py theo đúng chuẩn TDD, bám sát docstring và các ca kiểm thử trong thư mục tests/, đảm bảo không can thiệp vào data/raw."*
- **Cách kiểm tra code AI:** Chạy unit test từng module qua `pytest tests/test_<module>.py -v`, chạy toàn bộ 79 bài test kiểm tra tích hợp `test_pipeline_e2e.py`, và kiểm tra mã thoát thực tế của pipeline (`echo $?`).
- **Một lần AI sai và cách khắc phục:** Khi viết hàm cắt box (`clip_box`) trong `autofix.py`, ban đầu AI để box nằm hoàn toàn ngoài ảnh được cắt về tọa độ 0 nhưng vẫn giữ lại dòng nhãn. Qua kiểm tra test `test_box_fully_outside_is_dropped_not_negative`, logic đã được chỉnh sửa để nếu `new_w <= 0` hoặc `new_h <= 0`, dòng nhãn sẽ tự động chuyển thành hành vi `drop_line` thay vì ghi nhận box rỗng.
