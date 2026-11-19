"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |
"""
from collections import defaultdict
from pathlib import Path

import yaml

from ..common import ERROR, parse_yolo_line

DROP_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
CLIP_CODES = {"BOX_OUT_OF_IMAGE"}
REMOVE_IMG_CODES = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}


def is_remove_image(code: str) -> bool:
    return code.startswith("DUP_IMAGE_") or code in REMOVE_IMG_CODES


def fix(ds, issues, cfg):
    # Chỉ xử lý các lỗi bắt buộc (severity ERROR)
    err_issues = [i for i in issues if i.severity == ERROR]
    fixes = []

    # 1. Nhận diện các ảnh cần xoá (DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE)
    removed_images = set()
    for i in err_issues:
        if is_remove_image(i.code):
            removed_images.add(i.image)

    for stem in sorted(removed_images):
        p_img = ds.image_path(stem)
        if p_img and p_img.exists():
            p_img.unlink()
        p_lbl = ds.label_path(stem)
        if p_lbl.exists():
            p_lbl.unlink()
        ds._size_cache.pop(stem, None)
        fixes.append({
            "image": stem,
            "line": None,
            "action": "remove_image",
            "before": stem,
            "after": "(đã xoá)",
        })

    # 2. Xử lý sửa tên lớp (BAD_CLASS_NAME) trong data.yaml
    has_bad_class_name = any(i.code == "BAD_CLASS_NAME" for i in err_issues)
    if has_bad_class_name and ds.yaml_path.exists():
        try:
            d = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            d = {}
        old_names = d.get("names", {})
        d["names"] = list(cfg["classes"])
        ds.yaml_path.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")
        fixes.append({
            "image": "data.yaml",
            "line": None,
            "action": "rename_classes",
            "before": str(old_names),
            "after": str(cfg["classes"]),
        })

    # 3. Xử lý ảnh thiếu file nhãn (MISSING_LABEL_FILE)
    # Ghi nhận needs_label cho người, tuyệt đối không tạo file nhãn rỗng
    missing_label_images = {i.image for i in err_issues if i.code == "MISSING_LABEL_FILE" and i.image not in removed_images}
    for stem in sorted(missing_label_images):
        fixes.append({
            "image": stem,
            "line": None,
            "action": "needs_label",
            "before": "(không có file)",
            "after": "chuyển người gán",
        })

    # 4. Gom các lỗi dòng theo từng file nhãn
    line_issues_by_img = defaultdict(lambda: defaultdict(list))
    for i in err_issues:
        if i.image in removed_images or i.image in ("data.yaml", "<dataset>"):
            continue
        if i.line is not None and (i.code in DROP_CODES or i.code in CLIP_CODES):
            line_issues_by_img[i.image][i.line].append(i)

    for stem, lines_dict in sorted(line_issues_by_img.items()):
        lbl_file = ds.label_path(stem)
        if not lbl_file.exists():
            continue

        raw_lines = lbl_file.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines = []

        # Duyệt từng dòng theo số dòng gốc 1..N
        for line_no, raw_line in enumerate(raw_lines, 1):
            if line_no not in lines_dict:
                new_lines.append(raw_line)
                continue

            cur_issues = lines_dict[line_no]
            cur_codes = {ci.code for ci in cur_issues}

            # Quy tắc ưu tiên: Nếu có bất kỳ lỗi drop_line nào -> xoá dòng thắng (chỉ ghi 1 drop_line)
            if cur_codes & DROP_CODES:
                fixes.append({
                    "image": stem,
                    "line": line_no,
                    "action": "drop_line",
                    "before": raw_line,
                    "after": "",
                })
                # Bỏ qua dòng này (không thêm vào new_lines)
                continue

            if "BOX_OUT_OF_IMAGE" in cur_codes:
                # Cắt box về trong [0, 1]
                try:
                    cls_id, cx, cy, w, h = parse_yolo_line(raw_line)
                    x1 = cx - w / 2.0
                    y1 = cy - h / 2.0
                    x2 = cx + w / 2.0
                    y2 = cy + h / 2.0

                    x1_c = max(0.0, min(1.0, x1))
                    x2_c = max(0.0, min(1.0, x2))
                    y1_c = max(0.0, min(1.0, y1))
                    y2_c = max(0.0, min(1.0, y2))

                    new_w = x2_c - x1_c
                    new_h = y2_c - y1_c

                    if new_w <= 0.0 or new_h <= 0.0:
                        # Box nằm hoàn toàn ngoài ảnh -> xoá dòng thay vì giữ box rỗng
                        fixes.append({
                            "image": stem,
                            "line": line_no,
                            "action": "drop_line",
                            "before": raw_line,
                            "after": "",
                        })
                        continue

                    new_cx = (x1_c + x2_c) / 2.0
                    new_cy = (y1_c + y2_c) / 2.0
                    clipped_line = f"{int(cls_id)} {new_cx:.6f} {new_cy:.6f} {new_w:.6f} {new_h:.6f}"
                    new_lines.append(clipped_line)
                    fixes.append({
                        "image": stem,
                        "line": line_no,
                        "action": "clip_box",
                        "before": raw_line,
                        "after": clipped_line,
                    })
                except ValueError:
                    # Nếu dòng không parse được, drop_line
                    fixes.append({
                        "image": stem,
                        "line": line_no,
                        "action": "drop_line",
                        "before": raw_line,
                        "after": "",
                    })
                    continue

        # Ghi lại file nhãn
        new_content = "\n".join(new_lines) + ("\n" if new_lines else "")
        lbl_file.write_text(new_content, encoding="utf-8")

    return fixes
