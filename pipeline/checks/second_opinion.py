"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds


def run(ds, cfg, preds=None):
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    so_cfg = cfg.get("second_opinion", {})
    conf_thresh = so_cfg.get("conf", 0.25)
    min_area_px = so_cfg.get("min_area_px", 600)
    fp_conf = so_cfg.get("fp_conf", 0.1)
    iou_missing = so_cfg.get("iou_missing", 0.3)
    iou_match = so_cfg.get("iou_match", 0.5)
    iou_loose = so_cfg.get("iou_loose", 0.5)

    issues = []

    # Duyệt theo thứ tự ds.image_files()
    for img_path in ds.image_files():
        stem = img_path.stem

        # Bỏ qua ảnh không có trong preds hoặc không có file nhãn
        if stem not in preds or preds[stem] is None:
            continue
        if not ds.label_path(stem).exists():
            continue

        im_size = ds.image_size(stem)
        im_w, im_h = im_size if im_size else (1, 1)

        # Lấy danh sách các dòng nhãn hợp lệ kèm số dòng gốc
        valid_labels = []
        raw_lines = ds.read_label_lines(stem) or []
        for line_no, raw_line in raw_lines:
            try:
                cls_id, cx, cy, w, h = parse_yolo_line(raw_line)
            except ValueError:
                continue
            if 0 <= cls_id < len(ds.classes):
                valid_labels.append((line_no, cls_id, (cx, cy, w, h)))

        stem_preds = preds.get(stem) or []

        # 1. Tập dự đoán P: conf >= conf_thresh VÀ diện tích px >= min_area_px
        P = []
        for p in stem_preds:
            r_cls = int(p[0])
            r_conf = float(p[1])
            r_box = (float(p[2]), float(p[3]), float(p[4]), float(p[5]))
            area_px = (r_box[2] * im_w) * (r_box[3] * im_h) if im_size else 0
            if r_conf >= conf_thresh and area_px >= min_area_px:
                P.append((r_cls, r_conf, r_box))

        # Đánh giá từng dự đoán r trong P
        for r_cls, r_conf, r_box in P:
            # Lấy cands: các nhãn có IoU(r, nhãn) >= iou_missing
            cands = []
            for line_no, l_cls, l_box in valid_labels:
                iou = iou_xywh(r_box, l_box)
                if iou >= iou_missing:
                    cands.append((iou, line_no, l_cls, l_box))

            if not cands:
                # Không có cand nào -> POSSIBLE_MISSING
                cls_name = ds.classes[r_cls] if r_cls < len(ds.classes) else str(r_cls)
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_MISSING",
                        stem,
                        f"model phát hiện {cls_name} (conf={r_conf:.2f}) nhưng nhãn thiếu",
                        line=None,
                        extra={"conf": r_conf},
                    )
                )
            else:
                same_class_cands = [c for c in cands if c[2] == r_cls]
                if same_class_cands:
                    best_same_iou = max(c[0] for c in same_class_cands)
                    if best_same_iou < iou_loose:
                        cls_name = ds.classes[r_cls] if r_cls < len(ds.classes) else str(r_cls)
                        issues.append(
                            Issue(
                                "second_opinion",
                                WARN,
                                "POSSIBLE_LOOSE_BOX",
                                stem,
                                f"box nhãn cùng lớp {cls_name} nhưng IoU {best_same_iou:.2f} < {iou_loose}",
                                line=None,
                                extra={"conf": r_conf, "iou": best_same_iou},
                            )
                        )
                    # Nếu best_same_iou >= iou_loose: Không cờ gì
                else:
                    diff_class_cands = [c for c in cands if c[2] != r_cls]
                    if diff_class_cands:
                        best_diff_iou = max(c[0] for c in diff_class_cands)
                        if best_diff_iou >= iou_match:
                            cls_name = ds.classes[r_cls] if r_cls < len(ds.classes) else str(r_cls)
                            issues.append(
                                Issue(
                                    "second_opinion",
                                    WARN,
                                    "POSSIBLE_WRONG_CLASS",
                                    stem,
                                    f"model phát hiện {cls_name} (conf={r_conf:.2f}) nhưng nhãn gán lớp khác (IoU={best_diff_iou:.2f})",
                                    line=None,
                                    extra={"conf": r_conf, "iou": best_diff_iou},
                                )
                            )
                        # Nếu best_diff_iou < iou_match: không cờ gì (mơ hồ)

        # 2. Kiểm tra POSSIBLE_FALSE_POS
        # Dự đoán dùng cho FP: conf >= fp_conf (không lọc diện tích)
        fp_preds = [
            (float(p[2]), float(p[3]), float(p[4]), float(p[5]))
            for p in stem_preds
            if float(p[1]) >= fp_conf
        ]

        for line_no, l_cls, l_box in valid_labels:
            if not fp_preds:
                max_iou = 0.0
            else:
                max_iou = max(iou_xywh(l_box, pb) for pb in fp_preds)

            if max_iou < iou_missing:
                issues.append(
                    Issue(
                        "second_opinion",
                        WARN,
                        "POSSIBLE_FALSE_POS",
                        stem,
                        f"box nhãn dòng {line_no} không khớp vật nào model thấy (max IoU = {max_iou:.2f})",
                        line=line_no,
                        extra={"iou": max_iou},
                    )
                )

    return issues
