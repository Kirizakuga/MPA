import json
from datetime import date, timedelta
from config import get_schedule_json_path
from sync import notion_schedule_sync

WEEKDAY_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _load_schedule():
    with open(get_schedule_json_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def _build_tiet_map(data):
    """tiet number -> (gio_bat_dau, gio_ket_thuc)"""
    return {t["tiet"]: (t["gio_bat_dau"], t["gio_ket_thuc"]) for t in data["data"]["ds_tiet_trong_ngay"]}


def _find_sessions_by_date(data, date_str):
    """date_str: YYYY-MM-DD. Duyệt trực tiếp ngay_hoc, không cần tính qua thu_kieu_so."""
    sessions = []
    for week in data["data"]["ds_tuan_tkb"]:
        for s in week["ds_thoi_khoa_bieu"]:
            if s["ngay_hoc"].startswith(date_str):
                sessions.append(s)
    return sessions


def _format_session(s, tiet_map):
    tiet_start = s["tiet_bat_dau"]
    tiet_end = tiet_start + s["so_tiet"] - 1
    gio_bat_dau = tiet_map.get(tiet_start, ("?", "?"))[0]
    gio_ket_thuc = tiet_map.get(tiet_end, ("?", "?"))[1]
    return {
        "mon_hoc": s["ten_mon"],
        "phong": s["ma_phong"],
        "gio_bat_dau": gio_bat_dau,
        "gio_ket_thuc": gio_ket_thuc,
        "tiet": f"{tiet_start}-{tiet_end}",
        "lop": s.get("ma_lop", ""),
    }


def _monday_of_week(base_date: date, week_offset: int = 0) -> date:
    """
    Thứ Hai của tuần cách base_date `week_offset` tuần.
    week_offset: 0 = tuần chứa base_date, 1 = tuần sau, -1 = tuần trước.
    Tính hoàn toàn bằng Python (date.today() + timedelta) — không để model
    tự suy luận ngày, tránh lặp lại lỗi bịa ngày như đã gặp.
    """
    monday_this_week = base_date - timedelta(days=base_date.weekday())
    return monday_this_week + timedelta(weeks=week_offset)


def _weekday_vi(date_str: str) -> str:
    d = date.fromisoformat(date_str)
    return WEEKDAY_VI[d.weekday()]
def get_all_sessions():
    """Trả về TẤT CẢ buổi học trong toàn bộ học kỳ, đã chuẩn hóa — dùng cho sync sang Notion."""
    data = _load_schedule()
    tiet_map = _build_tiet_map(data)

    sessions = []
    for week in data["data"]["ds_tuan_tkb"]:
        for s in week["ds_thoi_khoa_bieu"]:
            formatted = _format_session(s, tiet_map)
            sessions.append({
                **formatted,
                "ma_mon": s["ma_mon"],
                "ngay": s["ngay_hoc"].split("T")[0],
                "id_tkb": s["id_tkb"],
                "co_so": s.get("ma_co_so", ""),
                "giang_vien": s.get("ten_giang_vien", ""),
                "is_nghi_day": s.get("is_nghi_day", False),
            })
    return sessions

# ---- Tool functions ----

def schedule_get_day(date_str):
    """date_str: 'YYYY-MM-DD'. Trả về danh sách buổi học ngày đó, đã sắp theo giờ."""
    data = _load_schedule()
    tiet_map = _build_tiet_map(data)
    sessions = _find_sessions_by_date(data, date_str)
    weekday = _weekday_vi(date_str)
    if not sessions:
        return {"date": date_str, "weekday": weekday, "sessions": [], "message": "Không có lịch học ngày này"}
    formatted = [_format_session(s, tiet_map) for s in sessions]
    formatted.sort(key=lambda x: x["gio_bat_dau"])
    return {"date": date_str, "weekday": weekday, "sessions": formatted}


def schedule_find_free_slot(date_str):
    """Tìm khoảng trống trong ngày, dựa trên các tiết đã có lịch."""
    data = _load_schedule()
    tiet_map = _build_tiet_map(data)
    sessions = _find_sessions_by_date(data, date_str)
    weekday = _weekday_vi(date_str)
    busy_tiets = set()
    for s in sessions:
        for t in range(s["tiet_bat_dau"], s["tiet_bat_dau"] + s["so_tiet"]):
            busy_tiets.add(t)
    all_tiets = sorted(tiet_map.keys())
    free_tiets = [t for t in all_tiets if t not in busy_tiets]
    return {"date": date_str, "weekday": weekday, "free_tiets": free_tiets, "busy_tiets": sorted(busy_tiets)}


def schedule_get_week_summary(week_offset: int = 0):
    """
    Tóm tắt lịch học/ngày rảnh cho cả 1 tuần (Thứ 2 - Chủ nhật).
    week_offset: 0 = tuần này, 1 = tuần sau, -1 = tuần trước — tính từ
    date.today() thật trong Python, KHÔNG dựa vào model tự tính ngày bắt đầu
    tuần. Dùng tool này thay vì gọi schedule_get_day/schedule_find_free_slot
    lặp lại nhiều lần cho câu hỏi kiểu 'tuần sau rảnh ngày nào'.
    """
    data = _load_schedule()
    tiet_map = _build_tiet_map(data)

    monday = _monday_of_week(date.today(), week_offset)
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        d_str = d.isoformat()
        sessions = _find_sessions_by_date(data, d_str)
        if sessions:
            formatted = sorted(
                (_format_session(s, tiet_map) for s in sessions),
                key=lambda x: x["gio_bat_dau"],
            )
            days.append({
                "date": d_str,
                "weekday": WEEKDAY_VI[i],
                "sessions": formatted,
                "free_all_day": False,
            })
        else:
            days.append({
                "date": d_str,
                "weekday": WEEKDAY_VI[i],
                "sessions": [],
                "free_all_day": True,
            })

    return {
        "week_start": monday.isoformat(),
        "week_offset": week_offset,
        "days": days,
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "schedule_get_day",
            "description": "Lấy danh sách lớp học của một ngày cụ thể trong lịch học",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Ngày dạng YYYY-MM-DD"}
                },
                "required": ["date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_find_free_slot",
            "description": "Tìm các tiết học còn trống trong một ngày cụ thể",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Ngày dạng YYYY-MM-DD"}
                },
                "required": ["date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_get_week_summary",
            "description": (
                "Lấy tóm tắt lịch học/ngày rảnh cho CẢ MỘT TUẦN (7 ngày, Thứ 2 - "
                "Chủ nhật). Dùng khi người dùng hỏi về 'tuần này', 'tuần sau', "
                "'tuần trước' — KHÔNG dùng schedule_get_day/schedule_find_free_slot "
                "lặp lại nhiều lần cho trường hợp này."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "week_offset": {
                        "type": "integer",
                        "description": "0 = tuần này, 1 = tuần sau, -1 = tuần trước. Mặc định 0."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type" : "function",
        "function": {
            "name": "schedule_sync_to_notion",
            "description": "Đồng bộ toàn bộ thời khóa biểu hiện có lên Notion database, "
                        "để hiển thị trên Notion Calendar. Dùng khi user yêu cầu cập nhật/đồng bộ lịch",
            "parameters": {
                "type": "object", "properties": {}},
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_resync",
            "description": (
                "Lấy lại thời khóa biểu mới nhất từ UIS và đồng bộ lại lên Notion "
                "trong 1 lần. Dùng khi user muốn 'cập nhật lịch mới nhất', "
                "'refresh lịch học', hoặc nghi ngờ lịch trên Notion đã cũ."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    }
]

TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def dispatch(tool_name, args):
    if tool_name == "schedule_get_day":
        return schedule_get_day(args["date"])
    if tool_name == "schedule_find_free_slot":
        return schedule_find_free_slot(args["date"])
    if tool_name == "schedule_get_week_summary":
        return schedule_get_week_summary(args.get("week_offset", 0))
    if tool_name == "schedule_sync_to_notion":
        return notion_schedule_sync.sync_all()
    if tool_name == "schedule_resync":
        from workflows.resync_schedule import run_full_resync
        return run_full_resync()
    raise ValueError(f"Unknown tool: {tool_name}")



if __name__ == "__main__":
    print(schedule_get_day("2026-08-11"))
    print(schedule_find_free_slot("2026-08-11"))
    print(schedule_get_week_summary(1))