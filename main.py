import requests
import json
import traceback
from datetime import date
import registry
from config import OLLAMA_URL, MODEL
from date_resolver import resolve_relative_dates
from logger_setup import log_turn   # ← thêm import

WEEKDAY_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _build_system_message():
    """
    Dựng system message gửi lên model mỗi lượt chat. Luôn chèn ngày/thứ hôm
    nay theo giờ máy chạy thật (không để model tự đoán "hôm nay là ngày
    nào"), cùng hướng dẫn cách dùng chú thích [Đã tính sẵn: ...] do
    date_resolver.resolve_relative_dates() chèn vào user message.
    """
    today = date.today()
    today_str = f"{today.isoformat()} ({WEEKDAY_VI[today.weekday()]})"

    content = (
        "Bạn là MPA (My Personal Assistant) — trợ lý cá nhân, trả lời bằng "
        "tiếng Việt, ngắn gọn, tự nhiên, đi thẳng vào câu trả lời.\n\n"
        f"Hôm nay là {today_str}.\n\n"
        "Khi cần thông tin về lịch học, LUÔN dùng tool tương ứng (schedule_get_day, "
        "schedule_find_free_slot, schedule_get_week_summary, schedule_sync_to_notion, "
        "schedule_resync) thay vì tự suy đoán hoặc bịa dữ liệu — bạn không có sẵn "
        "lịch học trong bộ nhớ, mọi thông tin phải lấy qua tool.\n\n"
        "Nếu câu hỏi của người dùng có chứa dòng '[Đã tính sẵn: ...]', đó là ngày "
        "tháng đã được tính sẵn bằng Python — hãy dùng trực tiếp giá trị đó khi gọi "
        "tool, KHÔNG tự cộng trừ ngày/tuần trong đầu. Nếu câu hỏi có ý nghĩa ngày "
        "tháng ghép phức tạp mà KHÔNG thấy chú thích này, hãy hỏi lại người dùng để "
        "làm rõ một mốc ngày duy nhất thay vì tự đoán.\n\n"
        "Với câu hỏi về 'tuần này'/'tuần sau'/'tuần trước', ưu tiên gọi "
        "schedule_get_week_summary một lần thay vì gọi schedule_get_day lặp lại "
        "nhiều lần cho từng ngày trong tuần."
    )

    return {"role": "system", "content": content}


def _strip_system_messages(history):
    """Loại bỏ mọi message role='system' cũ khỏi history, vì system message
    luôn được dựng lại mới (với ngày hôm nay cập nhật) ở đầu mỗi lượt chat."""
    return [m for m in history if m.get("role") != "system"]


def chat(user_message, history=None):
    if history is None:
        history = []

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
        log_turn(user_message, resolved_message, [], msg["content"])   # ← ghi data log
        return msg["content"], messages[1:] + [msg]

    messages.append(msg)

    tool_call_log = []   # ← thu thập tool calls để ghi vào data log

    for call in tool_calls:
        tool_name = call["function"]["name"]
        args = call["function"]["arguments"]
        print(f"  → Gọi tool: {tool_name}({args})")

        try:
            result = registry.dispatch(tool_name, args)
        except Exception as e:
            print(f"  ❌ LỖI KHI DISPATCH '{tool_name}':")
            traceback.print_exc()
            result = {"error": str(e)}

        tool_call_log.append({"name": tool_name, "args": args, "result": result})

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

    log_turn(user_message, resolved_message, tool_call_log, final_msg["content"])   # ← ghi data log

    return final_msg["content"], messages[1:] + [final_msg]


def handle_query(user_input: str, history: list | None = None) -> str:
    answer, _ = chat(user_input, history=history)
    return answer


if __name__ == "__main__":
    import traceback
    from logger_setup import start_session_logging, start_data_logging

    start_session_logging(session_name="cli_chat")
    start_data_logging(session_name="cli_chat")

    history = []
    print("mpa at your service (gõ 'exit' để thoát)")
    while True:
        user_input = input("\nBạn: ")
        if user_input.lower() in ("exit", "quit"):
            break
        answer, history = chat(user_input, history)
        print(f"Bot: {answer}")