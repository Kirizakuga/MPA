import os
import sys
from dotenv import load_dotenv

load_dotenv()

from ingestion.schedule_fetch import run_fetch_and_save
from sync import notion_schedule_sync
from logger_setup import start_resync_logging   # ← thay thế toàn bộ _log() cũ


def run_full_resync() -> dict:
    """Chạy toàn bộ pipeline: fetch UIS -> sync Notion. Dùng cho cả Task Scheduler lẫn tool chat."""
    log = start_resync_logging(session_name="resync")   # ← khởi tạo logger riêng cho lần chạy này

    log("Bắt đầu resync...")

    fetch_result = run_fetch_and_save()
    if not fetch_result["success"]:
        log(f"❌ Fetch thất bại: {fetch_result['error']}")
        return {"success": False, "stage": "fetch", "error": fetch_result["error"]}

    log(f"✅ Fetch thành công: {fetch_result['so_tuan']} tuần, tuần hiện tại: {fetch_result['current_week']}")

    sync_result = notion_schedule_sync.sync_all()
    if not sync_result["success"]:
        log(f"❌ Sync Notion thất bại: {sync_result.get('error')}")
        return {"success": False, "stage": "sync", "fetch_result": fetch_result, "sync_result": sync_result}

    log(
        f"✅ Sync Notion thành công: {sync_result['created']} tạo mới, "
        f"{sync_result['updated']} cập nhật, {sync_result['skipped']} bỏ qua"
    )

    return {"success": True, "fetch": fetch_result, "sync": sync_result}


if __name__ == "__main__":
    result = run_full_resync()
    sys.exit(0 if result["success"] else 1)