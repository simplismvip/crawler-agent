from __future__ import annotations

from backend.store import ConversationStore


def test_create_list_rename_delete_and_search(tmp_path) -> None:
    store = ConversationStore(tmp_path / "agent.db")
    first = store.create_conversation(model="MiniMax-M3")
    second = store.create_conversation(model="MiniMax-M2.7", title="Fastify 升级")
    store.add_message(first.id, "user", "抓取 Hacker News 首页")
    store.set_title_from_first_message(first.id)

    listed = store.list_conversations()
    assert [item.id for item in listed] == [first.id, second.id]
    assert listed[0].title.startswith("抓取 Hacker News")

    found = store.list_conversations(query="fastify")
    assert [item.id for item in found] == [second.id]

    store.rename_conversation(second.id, "官方 breaking changes")
    assert store.get_conversation(second.id).title == "官方 breaking changes"

    assert store.delete_conversation(second.id) is True
    assert store.get_conversation(second.id) is None
    assert [item.id for item in store.list_conversations()] == [first.id]


def test_messages_and_tool_calls_roundtrip(tmp_path) -> None:
    store = ConversationStore(tmp_path / "agent.db")
    conv = store.create_conversation(model="MiniMax-M3")
    store.add_message(conv.id, "user", "搜索 Fastify")
    assistant = store.add_message(conv.id, "assistant", "")
    tool = store.add_tool_call(
        assistant.id,
        name="search_web",
        args={"query": "Fastify"},
        status="running",
    )
    store.update_tool_call(tool.id, status="ok", preview="3 results")
    store.update_message_content(assistant.id, "这是总结")

    loaded = store.get_conversation(conv.id)
    assert loaded is not None
    assert [message.role for message in loaded.messages] == ["user", "assistant"]
    assert loaded.messages[1].content == "这是总结"
    assert loaded.messages[1].tools[0].name == "search_web"
    assert loaded.messages[1].tools[0].status == "ok"
    assert loaded.messages[1].tools[0].preview == "3 results"
    assert store.history_turns(conv.id) == [
        {"role": "user", "content": "搜索 Fastify"},
        {"role": "assistant", "content": "这是总结"},
    ]


def test_history_turns_drops_transient_connection_errors(tmp_path) -> None:
    store = ConversationStore(tmp_path / "agent.db")
    conv = store.create_conversation(model="MiniMax-M3")
    store.add_message(conv.id, "user", "帮我下载 https://www.bilibili.com/video/BV1e61RYPEno")
    store.add_message(conv.id, "assistant", "下载完成")
    store.add_message(conv.id, "user", "重新下载")
    store.add_message(conv.id, "assistant", "Connection error.")
    store.add_message(conv.id, "user", "重新下载")
    store.add_message(conv.id, "assistant", "下载失败：Connection error.")
    store.add_message(conv.id, "user", "重新下载")
    store.add_message(conv.id, "assistant", "好的，重新下载视频：")
    assert store.history_turns(conv.id) == [
        {"role": "user", "content": "帮我下载 https://www.bilibili.com/video/BV1e61RYPEno"},
        {"role": "assistant", "content": "下载完成"},
    ]
