import requests
import json
from datetime import date
import registry
from config import OLLAMA_URL, MODEL
from date_resolver import resolve_relative_dates
from logger_setup import log_turn   # ← thêm import

WEEKDAY_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def _build_system_message():
    # ... giữ nguyên toàn bộ, không đổi ...


def _strip_system_messages(history):
    # ... giữ nguyên ...


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