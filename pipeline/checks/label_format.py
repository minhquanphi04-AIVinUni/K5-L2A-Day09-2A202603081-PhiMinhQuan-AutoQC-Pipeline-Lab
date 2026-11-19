"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line


def run(ds, cfg):
    issues = []
    lf_cfg = cfg.get("label_format", {})
    overflow_tol = lf_cfg.get("overflow_tol", 0.002)
    min_box_px = lf_cfg.get("min_box_px", 12)
    max_box_frac = lf_cfg.get("max_box_frac", 0.95)
    dup_box_iou = lf_cfg.get("dup_box_iou", 0.9)

    for label_path in ds.label_files():
        stem = label_path.stem
        lines = ds.read_label_lines(stem)
        if not lines:
            continue

        im_size = ds.image_size(stem)
        prev_boxes = []  # list of (line_no, cls_id, (cx, cy, w, h))

        for line_no, raw_line in lines:
            try:
                cls_id, cx, cy, w, h = parse_yolo_line(raw_line)
            except ValueError as e:
                issues.append(
                    Issue("label_format", ERROR, "BAD_FORMAT", stem, f"dòng nhãn sai định dạng: {e}", line=line_no)
                )
                continue

            if not (0 <= cls_id < len(ds.classes)):
                issues.append(
                    Issue(
                        "label_format",
                        ERROR,
                        "BAD_CLASS_ID",
                        stem,
                        f"id lớp {cls_id} ngoài phạm vi 0..{len(ds.classes) - 1}",
                        line=line_no,
                        extra={"class_id": cls_id},
                    )
                )
                continue

            if w <= 0 or h <= 0:
                issues.append(
                    Issue(
                        "label_format",
                        ERROR,
                        "BOX_ZERO",
                        stem,
                        f"kích thước box <= 0 (w={w}, h={h})",
                        line=line_no,
                        extra={"w": w, "h": h},
                    )
                )
                continue

            # Mép box [x1, y1, x2, y2]
            x1 = cx - w / 2.0
            y1 = cy - h / 2.0
            x2 = cx + w / 2.0
            y2 = cy + h / 2.0

            overflow = max(0.0, -x1, -y1, x2 - 1.0, y2 - 1.0)
            if overflow > overflow_tol:
                issues.append(
                    Issue(
                        "label_format",
                        ERROR,
                        "BOX_OUT_OF_IMAGE",
                        stem,
                        f"box tràn mép ảnh mức {overflow:.4f} > tol {overflow_tol}",
                        line=line_no,
                        extra={"overflow": overflow},
                    )
                )

            # DUP_BOX: cùng lớp với dòng TRƯỚC ĐÓ và IoU > dup_box_iou
            curr_box = (cx, cy, w, h)
            is_dup = False
            for _, p_cls, p_box in prev_boxes:
                if p_cls == cls_id and iou_xywh(curr_box, p_box) > dup_box_iou:
                    issues.append(
                        Issue(
                            "label_format",
                            ERROR,
                            "DUP_BOX",
                            stem,
                            f"box trùng với một box trước đó cùng lớp {cls_id}",
                            line=line_no,
                        )
                    )
                    is_dup = True
                    break

            prev_boxes.append((line_no, cls_id, curr_box))

            # BOX_TINY
            if im_size:
                im_w, im_h = im_size
                short_side_px = min(w * im_w, h * im_h)
                if short_side_px < min_box_px:
                    issues.append(
                        Issue(
                            "label_format",
                            WARN,
                            "BOX_TINY",
                            stem,
                            f"cạnh ngắn của box ({short_side_px:.1f}px) < {min_box_px}px",
                            line=line_no,
                            extra={"short_side_px": short_side_px},
                        )
                    )

            # BOX_HUGE
            if w * h > max_box_frac:
                issues.append(
                    Issue(
                        "label_format",
                        WARN,
                        "BOX_HUGE",
                        stem,
                        f"diện tích box ({w * h:.3f}) > {max_box_frac}",
                        line=line_no,
                        extra={"frac": w * h},
                    )
                )

    return issues
