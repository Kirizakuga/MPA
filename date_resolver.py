"""
Phân giải các biểu thức ngày tương đối tiếng Việt BẰNG PYTHON, không để model
tự cộng trừ ngày/tuần trong đầu — test thực tế cho thấy qwen2.5:7b-instruct
tính sai với câu ghép nhiều lớp (vd: "3 hôm nữa của 5 tuần kế" tính lệch ~11
ngày) và có xu hướng "diễn" một đoạn tool-call/tool-response giả bằng text
thay vì gọi tool thật khi câu hỏi vượt quá khả năng suy luận nối tiếp của nó.

CÁCH DÙNG: gọi resolve_relative_dates(text) TRƯỚC khi gửi user_message lên
model trong main.py::chat(). Hàm KHÔNG thay đổi câu hỏi gốc, chỉ CHÈN THÊM
1 dòng chú thích ngày đã tính sẵn vào cuối, ví dụ:

    "mai học môn gì"
    -> "mai học môn gì\n[Đã tính sẵn: 'mai' = 2026-08-07 (Thứ Sáu)]"

Model chỉ cần đọc chú thích và gọi tool với ngày đó, không cần tự tính nữa.

GIỚI HẠN CÓ CHỦ ĐÍCH: chỉ nhận diện các mẫu câu đơn (1 phép biến đổi: hôm
nay/mai/hôm qua/ngày kia/N hôm nữa/tuần này/tuần sau/tuần trước/N tuần
sau/cuối tuần) VÀ 1 mẫu ghép đã được xác nhận ngữ nghĩa rõ ràng: "N hôm/ngày
nữa của M tuần sau/kế" = hôm_nay + M tuần + N ngày (cộng dồn). Các câu ghép
khác CHỦ ĐỘNG KHÔNG được tự động phân giải — ngữ nghĩa vốn mơ hồ ngay cả với
người đọc, tự đoán dễ sai hơn là hỏi lại. System prompt sẽ được dặn: gặp câu
hỏi phức tạp kiểu này mà không thấy chú thích [Đã tính sẵn], hãy hỏi lại
người dùng làm rõ theo 1 mốc duy nhất, không tự cộng dồn nhiều phép tính.
"""

import re
from datetime import date, timedelta

WEEKDAY_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

_WEEK_OFFSET_RE = re.compile(r"(\d+)\s*tuần\s*(sau|nữa|tới|kế)")
_DAY_OFFSET_RE = re.compile(r"(\d+)\s*(hôm|ngày)\s*nữa")
_COMPOUND_RE = re.compile(r"(hôm|ngày)\s*nữa.{0,20}tuần|tuần.{0,20}(hôm|ngày)\s*nữa")

# Ngữ nghĩa đã xác nhận với người dùng: "N hôm/ngày nữa của M tuần sau/kế"
# = hôm_nay + M tuần + N ngày (cộng dồn, không phải "N ngày trong tuần thứ M")
_COMPOUND_DAY_OF_WEEK_RE = re.compile(
    r"(\d+)\s*(?:hôm|ngày)\s*nữa\s*(?:của|cách)?\s*(\d+)\s*tuần\s*(?:sau|nữa|tới|kế)"
)
_COMPOUND_WEEK_THEN_DAY_RE = re.compile(
    r"(\d+)\s*tuần\s*(?:sau|nữa|tới|kế)\s*(?:và|,|cộng|thêm)?\s*(\d+)\s*(?:hôm|ngày)\s*nữa"
)


def _monday_of_week(base: date, week_offset: int = 0) -> date:
    monday = base - timedelta(days=base.weekday())
    return monday + timedelta(weeks=week_offset)


def _fmt(d: date) -> str:
    return f"{d.isoformat()} ({WEEKDAY_VI[d.weekday()]})"


def resolve_relative_dates(text: str, today: date | None = None) -> str:
    today = today or date.today()
    lower = text.lower()
    notes: list[str] = []

    # Ngữ nghĩa đã xác nhận: "N hôm nữa của M tuần sau" = hôm_nay + M tuần + N ngày
    m = _COMPOUND_DAY_OF_WEEK_RE.search(lower)
    if m:
        days_n, weeks_n = int(m.group(1)), int(m.group(2))
    else:
        m = _COMPOUND_WEEK_THEN_DAY_RE.search(lower)
        days_n, weeks_n = (int(m.group(2)), int(m.group(1))) if m else (None, None)

    if m:
        target = today + timedelta(weeks=weeks_n, days=days_n)
        notes.append(
            f"'{m.group(0)}' = hôm nay + {weeks_n} tuần + {days_n} ngày = {_fmt(target)}"
        )
        return text + "\n[Đã tính sẵn — dùng trực tiếp, không tự tính lại: " + "; ".join(notes) + "]"

    # Câu ghép khác chưa có ngữ nghĩa xác định rõ ràng — bỏ qua, để model hỏi lại
    if _COMPOUND_RE.search(lower):
        return text

    if "hôm nay" in lower:
        notes.append(f"'hôm nay' = {_fmt(today)}")
    if "ngày kia" in lower:
        notes.append(f"'ngày kia' = {_fmt(today + timedelta(days=2))}")
    elif "hôm qua" in lower:
        notes.append(f"'hôm qua' = {_fmt(today - timedelta(days=1))}")
    elif re.search(r"\bmai\b", lower):
        notes.append(f"'mai' = {_fmt(today + timedelta(days=1))}")

    m = _DAY_OFFSET_RE.search(lower)
    if m:
        n = int(m.group(1))
        notes.append(f"'{m.group(0)}' = {_fmt(today + timedelta(days=n))}")

    weekend_match = re.search(r"cuối tuần", lower)
    week_offset_match = _WEEK_OFFSET_RE.search(lower)

    if weekend_match:
        if week_offset_match:
            offset = int(week_offset_match.group(1))
        elif "tuần sau" in lower or "tuần tới" in lower:
            offset = 1
        elif "tuần trước" in lower:
            offset = -1
        else:
            offset = 0
        monday = _monday_of_week(today, offset)
        sat, sun = monday + timedelta(days=5), monday + timedelta(days=6)
        notes.append(
            f"'cuối tuần' (week_offset={offset}) = {_fmt(sat)} và {_fmt(sun)}"
        )
    elif week_offset_match:
        offset = int(week_offset_match.group(1))
        monday = _monday_of_week(today, offset)
        notes.append(
            f"'{week_offset_match.group(0)}' -> tuần bắt đầu {_fmt(monday)} (week_offset={offset})"
        )
    elif "tuần này" in lower:
        notes.append(f"'tuần này' -> tuần bắt đầu {_fmt(_monday_of_week(today, 0))} (week_offset=0)")
    elif "tuần sau" in lower or "tuần tới" in lower:
        notes.append(f"'tuần sau' -> tuần bắt đầu {_fmt(_monday_of_week(today, 1))} (week_offset=1)")
    elif "tuần trước" in lower:
        notes.append(f"'tuần trước' -> tuần bắt đầu {_fmt(_monday_of_week(today, -1))} (week_offset=-1)")

    if not notes:
        return text

    return text + "\n[Đã tính sẵn — dùng trực tiếp, không tự tính lại: " + "; ".join(notes) + "]"