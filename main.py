import requests
import json
from datetime import date
import registry
from config import OLLAMA_URL, MODEL
from date_resolver import resolve_relative_dates

WEEKDAY_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _build_system_message():
    """
    Tiêm ngày hiện tại thật (Python tính, không phải model đoán) vào system
    prompt MỖI LẦN gọi chat() — không hardcode 1 lần lúc khởi động, vì app có
    thể chạy qua đêm/nhiều ngày (đặc biệt đúng với overlay chạy nền liên tục).
    """
    today = date.today()
    return {
        "role": "system",
        "content": (
            f"Hôm nay là {today.isoformat()} ({WEEKDAY_VI[today.weekday()]}). "
            "Nếu câu hỏi của người dùng có phần chú thích dạng "
            "'[Đã tính sẵn: ...]' ở cuối, đó là ngày/tuần đã được tính SẴN BẰNG "
            "PYTHON — LUÔN dùng trực tiếp giá trị đó để gọi tool, KHÔNG tự tính "
            "lại theo cách khác dù cảm thấy chắc chắn (Python luôn đúng hơn bạn "
            "trong việc cộng trừ ngày).\n\n"
            "Nếu câu hỏi CÓ ý nghĩa ngày tương đối (hôm nay/mai/tuần sau/cuối "
            "tuần...) nhưng KHÔNG có chú thích [Đã tính sẵn] đi kèm — nghĩa là "
            "câu hỏi ghép nhiều lớp thời gian quá phức tạp để tính tự động an "
            "toàn. Trong trường hợp này, HỎI LẠI người dùng để làm rõ thành 1 "
            "mốc thời gian duy nhất (ví dụ: 'bạn muốn hỏi ngày cụ thể nào?'), "
            "TUYỆT ĐỐI KHÔNG tự cộng trừ nhiều phép tính ngày trong đầu, và "
            "KHÔNG được tự viết ra đoạn hội thoại giả kiểu mô phỏng việc gọi "
            "tool/nhận kết quả — nếu chưa có tool call thật, chỉ được hỏi lại, "
            "không được bịa ra kết quả hay bịa ra cả quá trình tra cứu.\n\n"
            "QUAN TRỌNG: khi đã có ngày cụ thể (từ chú thích, hoặc từ ngày "
            "GỐC do người dùng gõ rõ ràng), GỌI TOOL NGAY trong CÙNG lượt trả "
            "lời — không dừng lại nói 'hãy chờ tôi tra cứu' rồi không gọi gì, "
            "PHẢI có tool call thật trong lượt đó.\n\n"
            "KHÔNG TỰ TÍNH THỨ TRONG TUẦN: kết quả các tool lịch học đã có sẵn "
            "trường 'weekday' — LUÔN dùng đúng giá trị đó khi nói về thứ, KHÔNG tự "
            "suy luận hay đoán thứ trong tuần theo cách khác, kể cả khi cảm thấy "
            "chắc chắn.\n\n"
            "Với câu hỏi về CẢ MỘT TUẦN (không phải 1 ngày cụ thể), dùng tool "
            "schedule_get_week_summary thay vì tự tính ra từng ngày rồi gọi "
            "schedule_get_day/schedule_find_free_slot nhiều lần.\n\n"
            "KHI TRÌNH BÀY KẾT QUẢ TOOL: các trường tên môn học (ten_mon/mon_hoc), "
            "mã phòng (phong/ma_phong), giờ học (gio_bat_dau/gio_ket_thuc) PHẢI được "
            "copy CHÍNH XÁC TỪNG KÝ TỰ từ dữ liệu tool trả về — KHÔNG được viết lại, "
            "đổi từ ngữ, rút gọn, hay 'nhớ nhầm' theo tên môn quen thuộc nào khác. "
            "Nếu không chắc cách đọc một chuỗi tiếng Việt có dấu trong dữ liệu, vẫn "
            "phải in ra đúng y nguyên chuỗi đó, không thay bằng từ gần giống."
        ),
    }


def _strip_system_messages(history):
    """Loại bỏ system message cũ khỏi history trước khi build lại — tránh
    system message ngày hôm qua còn sót lại lẫn với system message hôm nay."""
    return [m for m in history if m.get("role") != "system"]


def chat(user_message, history=None):
    if history is None:
        history = []

    # Tính sẵn ngày tương đối bằng Python TRƯỚC khi gửi lên model — xem
    # date_resolver.py để biết lý do (model tính sai câu ghép nhiều lớp).
    resolved_message = resolve_relative_dates(user_message)

    history = _strip_system_messages(history)
    messages = [_build_system_message()] + history + [{"role": "user", "content": resolved_message}]

    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": registry.all_tools(),
        "stream": False
    }

    resp = requests.post(OLLAMA_URL, json=payload)
    resp.raise_for_status()
    data = resp.json()
    msg = data["message"]

    tool_calls = msg.get("tool_calls")

    if not tool_calls:
        # trả về history KHÔNG kèm system message — _strip_system_messages ở
        # lượt chat() tiếp theo sẽ không có gì để lọc, nhưng giữ vậy cho nhất quán
        return msg["content"], messages[1:] + [msg]

    messages.append(msg)

    for call in tool_calls:
        tool_name = call["function"]["name"]
        args = call["function"]["arguments"]
        print(f"  → Gọi tool: {tool_name}({args})")

        try:
            result = registry.dispatch(tool_name, args)
        except Exception as e:
            result = {"error": str(e)}

        messages.append({
            "role": "tool",
            "content": json.dumps(result, ensure_ascii=False)
        })

    payload2 = {
        "model": MODEL,
        "messages": messages,
        "tools": registry.all_tools(),
        "stream": False
    }
    resp2 = requests.post(OLLAMA_URL, json=payload2)
    resp2.raise_for_status()
    data2 = resp2.json()
    final_msg = data2["message"]

    return final_msg["content"], messages[1:] + [final_msg]


def handle_query(user_input: str, history: list | None = None) -> str:
    """
    Dùng lại được từ cả CLI (vòng lặp bên dưới) và overlay
    (overlay/chat_worker.py) — 1 điểm vào duy nhất cho logic tool-calling.

    history=None -> hỏi độc lập, không giữ ngữ cảnh (overlay hiện tại dùng
    cách này). Truyền list message vào để giữ multi-turn — khi overlay bật
    multi-turn sau này, chỉ cần đổi tham số ở overlay_window.py, hàm này
    không cần sửa gì thêm.
    """
    answer, _ = chat(user_input, history=history)
    return answer


if __name__ == "__main__":
    history = []
    print("mpa at your service (gõ 'exit' để thoát)")
    while True:
        user_input = input("\nBạn: ")
        if user_input.lower() in ("exit", "quit"):
            break
        answer, history = chat(user_input, history)
        print(f"Bot: {answer}")