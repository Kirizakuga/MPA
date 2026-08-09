import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")


def get_current_semester_code() -> int:
    """
    Tính mã học kỳ (nhhk) theo thời gian thực.

    - Tháng 8-12: HK1 năm nay
    - Tháng 1-6:  HK2 năm học trước
    - Tháng 7:    học kỳ hè, cần UIS_SEMESTER_OVERRIDE

    Ghi đè bất kỳ lúc nào bằng: export UIS_SEMESTER_OVERRIDE=<mã>
    """
    override = os.environ.get("UIS_SEMESTER_OVERRIDE")
    if override:
        return int(override)

    now = datetime.now()
    year, month = now.year, now.month

    if 8 <= month <= 12:
        return int(f"{year}1")
    if 1 <= month <= 6:
        return int(f"{year - 1}2")

    raise ValueError(
        f"Tháng {month} rơi vào học kỳ hè, chưa có mã tự động. "
        "Set UIS_SEMESTER_OVERRIDE=<mã_học_kỳ_hè> sau khi xác nhận trên UIS."
    )


def get_schedule_json_path() -> str:
    """Đường dẫn file TKB tương ứng học kỳ hiện tại — tự đổi theo mã hk."""
    return os.path.join(DATA_DIR, f"tkb_{get_current_semester_code()}.json")


OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:7b-instruct"