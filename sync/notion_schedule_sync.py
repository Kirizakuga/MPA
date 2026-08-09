import os
import time
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

from source import schedule_source

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DB_ID = os.environ.get("NOTION_SCHEDULE_DB_ID")
NOTION_VERSION = "2022-06-28"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

MAX_RETRIES = 3
RETRY_DELAY = 1.5   # giây, chờ trước khi thử lại
REQUEST_DELAY = 0.35  # giây, nghỉ giữa mỗi request để tránh rate limit


def _request_with_retry(method, url, **kwargs):
    """Gửi request có retry khi gặp lỗi mạng tạm thời."""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=15, **kwargs)
            return resp
        except requests.exceptions.ConnectionError as e:
            last_error = e
            print(f"  ⚠️ Lỗi kết nối (lần {attempt}/{MAX_RETRIES}), thử lại sau {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
    raise last_error


def _session_key(session: dict) -> str:
    raw = f"{session['id_tkb']}|{session['ngay']}"
    return hashlib.md5(raw.encode()).hexdigest()


def _find_existing_page(key: str) -> str | None:
    resp = _request_with_retry(
        "post",
        f"https://api.notion.com/v1/databases/{DB_ID}/query",
        headers=HEADERS,
        json={"filter": {"property": "SyncKey", "rich_text": {"equals": key}}},
    )
    if not resp.ok:
        print("NOTION ERROR:", resp.status_code, resp.text)
    resp.raise_for_status()
    results = resp.json()["results"]
    return results[0]["id"] if results else None


def _build_properties(session: dict, key: str) -> dict:
    start = f"{session['ngay']}T{session['gio_bat_dau']}:00+07:00"   # ← thêm +07:00
    end = f"{session['ngay']}T{session['gio_ket_thuc']}:00+07:00"    # ← thêm +07:00
    return {
        "Tên môn": {"title": [{"text": {"content": session["mon_hoc"]}}]},
        "Ngày": {"date": {"start": start, "end": end}},
        "Phòng": {"rich_text": [{"text": {"content": session["phong"]}}]},
        "Lớp": {"rich_text": [{"text": {"content": session["lop"]}}]},
        "Giảng viên": {"rich_text": [{"text": {"content": session["giang_vien"] or "—"}}]},
        "SyncKey": {"rich_text": [{"text": {"content": key}}]},
    }


def upsert_session(session: dict) -> str:
    if session["is_nghi_day"]:
        return "skipped"

    key = _session_key(session)
    props = _build_properties(session, key)
    existing_id = _find_existing_page(key)

    time.sleep(REQUEST_DELAY)

    if existing_id:
        resp = _request_with_retry(
            "patch",
            f"https://api.notion.com/v1/pages/{existing_id}",
            headers=HEADERS, json={"properties": props},
        )
        action = "updated"
    else:
        resp = _request_with_retry(
            "post",
            "https://api.notion.com/v1/pages",
            headers=HEADERS,
            json={"parent": {"database_id": DB_ID}, "properties": props},
        )
        action = "created"

    if not resp.ok:
        print("NOTION ERROR:", resp.status_code, resp.text)
    resp.raise_for_status()

    time.sleep(REQUEST_DELAY)
    return action


def sync_all() -> dict:
    if not NOTION_TOKEN or not DB_ID:
        return {"success": False, "error": "Thiếu NOTION_TOKEN hoặc NOTION_SCHEDULE_DB_ID trong .env"}

    sessions = schedule_source.get_all_sessions()
    created = updated = skipped = failed = 0
    errors = []

    for i, s in enumerate(sessions, 1):
        try:
            action = upsert_session(s)
        except Exception as e:
            failed += 1
            errors.append(f"{s.get('mon_hoc', '?')} - {s.get('ngay', '?')}: {e}")
            print(f"[{i}/{len(sessions)}] ❌ Lỗi: {e}")
            continue

        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        else:
            skipped += 1
        print(f"[{i}/{len(sessions)}] {action}: {s['mon_hoc']} - {s['ngay']}")

    return {
        "success": failed == 0,
        "total": len(sessions),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:5],  # chỉ trả về 5 lỗi đầu để tránh output quá dài
    }


if __name__ == "__main__":
    result = sync_all()
    print(result)