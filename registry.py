from source import schedule_source
# from source import vector_source   # bật khi đã viết xong
# from notes import notion_source    # bật khi đã viết xong

SOURCES = [schedule_source]


def all_tools():
    tools = []
    for src in SOURCES:
        tools.extend(src.TOOLS)
    return tools


def dispatch(tool_name, args):
    for src in SOURCES:
        if tool_name in src.TOOL_NAMES:
            return src.dispatch(tool_name, args)
    raise ValueError(f"Không nguồn nào xử lý tool: {tool_name}")