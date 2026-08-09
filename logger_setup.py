import sys
import os
import json
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

SESSION_LOG_PATH = os.path.join(DATA_DIR, "session_log.txt")
RESYNC_LOG_PATH = os.path.join(DATA_DIR, "resync_log.txt")
DATA_LOG_PATH = os.path.join(DATA_DIR, "data_log.jsonl")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _write_session_header(log_path: str, session_name: str) -> None:
    """Ghi header đánh dấu bắt đầu 1 session mới — LUÔN append, không ghi đè."""
    _ensure_data_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"\n{'=' * 70}\n[SESSION START] {session_name} — {timestamp}\n{'=' * 70}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(header)


class _Tee:
    """Ghi đồng thời ra stream gốc (terminal) VÀ ra file log, flush ngay lập tức."""
    def __init__(self, original_stream, log_file):
        self.original_stream = original_stream
        self.log_file = log_file

    def write(self, data):
        self.original_stream.write(data)
        self.log_file.write(data)
        self.log_file.flush()

    def flush(self):
        self.original_stream.flush()
        self.log_file.flush()


# ---------------------------------------------------------------------------
# 1) SESSION LOG — toàn bộ stdout/stderr của phiên chat
# ---------------------------------------------------------------------------

def start_session_logging(session_name: str = "main") -> None:
    """Ghi TOÀN BỘ print/traceback vào data/session_log.txt. Luôn append."""
    _write_session_header(SESSION_LOG_PATH, session_name)
    log_file = open(SESSION_LOG_PATH, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)


# ---------------------------------------------------------------------------
# 2) RESYNC LOG — riêng cho pipeline fetch UIS + sync Notion
# ---------------------------------------------------------------------------

def start_resync_logging(session_name: str = "resync_workflow"):
    """
    Trả về hàm log(message) dùng trong workflows/resync_schedule.py.
    Cùng format header với session log. Luôn append vào data/resync_log.txt.
    """
    _write_session_header(RESYNC_LOG_PATH, session_name)

    def log(message: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line)
        with open(RESYNC_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    return log


# ---------------------------------------------------------------------------
# 3) DATA LOG — dữ liệu có cấu trúc (JSONL), dùng để retrain model sau này
# ---------------------------------------------------------------------------

def start_data_logging(session_name: str = "main") -> None:
    """Ghi 1 dòng JSON đánh dấu bắt đầu session vào data/data_log.jsonl. Luôn append."""
    _ensure_data_dir()
    entry = {
        "type": "session_start",
        "session_name": session_name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    with open(DATA_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_turn(user_message: str, resolved_message: str, tool_calls: list, final_response: str) -> None:
    """
    Ghi 1 lượt hỏi-đáp hoàn chỉnh (input gốc, input đã resolve ngày, các tool
    call kèm kết quả, câu trả lời cuối) thành 1 dòng JSON — dữ liệu retrain.
    """
    _ensure_data_dir()
    entry = {
        "type": "turn",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "user_message": user_message,
        "resolved_message": resolved_message,
        "tool_calls": tool_calls,
        "final_response": final_response,
    }
    with open(DATA_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")