import json
import os
import sys
from datetime import datetime
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

from config import DATA_DIR, get_current_semester_code

load_dotenv()

TARGET_API_PATH = "w-locdstkbtuanusertheohocky"
LOGIN_URL = "https://uis.ptithcm.edu.vn/"
SCHEDULE_URL = "https://uis.ptithcm.edu.vn/#/tkb-tuan"

DEBUG = os.environ.get("UIS_DEBUG", "0") == "1"


def dprint(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)


def find_current_week(schedule_data: dict) -> dict | None:
    """So ngày hôm nay với ngay_bat_dau/ngay_ket_thuc thật của từng tuần."""
    today = datetime.now().date()
    for tuan in schedule_data["data"]["ds_tuan_tkb"]:
        start = datetime.strptime(tuan["ngay_bat_dau"], "%d/%m/%Y").date()
        end = datetime.strptime(tuan["ngay_ket_thuc"], "%d/%m/%Y").date()
        if start <= today <= end:
            return tuan
    return None


def fetch_schedule(username: str, password: str, headless: bool = True) -> dict | None:
    target_nhhk = get_current_semester_code()
    print(f"Mã học kỳ mục tiêu: {target_nhhk}")

    captured_headers: dict | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        def capture_default_request(request):
            nonlocal captured_headers
            if TARGET_API_PATH in request.url and captured_headers is None:
                captured_headers = dict(request.headers)
                dprint("Đã bắt được header xác thực từ request mặc định.")
                dprint(f"   Payload request mặc định: {request.post_data}")

        page.on("request", capture_default_request)

        page.goto(LOGIN_URL)
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)
        page.click("button:has-text('Đăng nhập')")

        try:
            page.wait_for_url("**/home*", timeout=15000)
        except Exception:
            browser.close()
            raise RuntimeError(
                "Đăng nhập thất bại hoặc URL sau khi login khác kỳ vọng. "
                "Kiểm tra lại username/password hoặc selector form đăng nhập."
            )

        page.goto(SCHEDULE_URL)
        page.wait_for_timeout(2000)

        if captured_headers is None:
            browser.close()
            raise RuntimeError(
                f"Không bắt được request mặc định nào tới '{TARGET_API_PATH}'. "
                "Có thể route/API đã đổi, cần kiểm tra lại bằng tab Network của DevTools."
            )

        payload = {
            "filter": {"hoc_ky": target_nhhk, "ten_hoc_ky": ""},
            "additional": {
                "paging": {"limit": 100, "page": 1},
                "ordering": [{"name": None, "order_type": None}],
            },
        }

        forbidden = {"content-length", "host", "connection"}
        safe_headers = {
            k: v for k, v in captured_headers.items() if k.lower() not in forbidden
        }

        captured_data = page.evaluate(
            """async ({ headers, payload }) => {
                const res = await fetch('/api/sch/w-locdstkbtuanusertheohocky', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify(payload)
                });
                const text = await res.text();
                let json = null;
                try { json = JSON.parse(text); } catch (e) { json = null; }
                return { status: res.status, ok: res.ok, json: json, raw: text.slice(0, 1000) };
            }""",
            {"headers": safe_headers, "payload": payload},
        )

        dprint(f"Kết quả request tùy chỉnh: status={captured_data['status']}")
        if not captured_data["ok"] or captured_data["json"] is None:
            print(f"   Raw body: {captured_data['raw']}")

        browser.close()
        return captured_data["json"]


def run_fetch_and_save() -> dict:
    """Chạy fetch + lưu file, trả về dict tóm tắt. Gọi được từ script khác (workflows/, tools/)."""
    uis_username = os.environ.get("UIS_USERNAME")
    uis_password = os.environ.get("UIS_PASSWORD")

    if not uis_username or not uis_password:
        return {"success": False, "error": "Thiếu UIS_USERNAME/UIS_PASSWORD trong .env"}

    try:
        result = fetch_schedule(uis_username, uis_password, headless=True)
    except Exception as e:
        return {"success": False, "error": str(e)}

    if not result or not result.get("result"):
        return {"success": False, "error": "Không lấy được dữ liệu hợp lệ từ UIS"}

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, f"tkb_{get_current_semester_code()}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    so_tuan = len(result["data"]["ds_tuan_tkb"])
    current_week = find_current_week(result)

    return {
        "success": True,
        "so_tuan": so_tuan,
        "out_path": out_path,
        "current_week": current_week["thong_tin_tuan"] if current_week else None,
    }


if __name__ == "__main__":
    result = run_fetch_and_save()
    if not result["success"]:
        print(f"Lỗi: {result['error']}")
        sys.exit(1)
    print(f"Lấy TKB thành công: {result['so_tuan']} tuần, đã lưu vào {result['out_path']}")
    if result["current_week"]:
        print(f"Tuần hiện tại: {result['current_week']}")
    else:
        print("⚠️ Hôm nay nằm ngoài phạm vi các tuần của học kỳ này (có thể đang nghỉ hè/tết).")