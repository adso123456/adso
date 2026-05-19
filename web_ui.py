"""
Minecraft Agent Web 控制台
基于 Gradio 的可视化操作界面

启动方式: python web_ui.py
访问地址: http://localhost:7860
"""
import requests
import gradio as gr
from config import cfg

CHAT_URL = f"http://{cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT}"


def fetch_dashboard():
    """获取仪表盘数据"""
    try:
        r = requests.get(f"{CHAT_URL}/dashboard", timeout=5)
        return r.json()
    except:
        return {"bot": {"connected": False}, "recent_chats": [], "memory_count": 0}


def format_bot_info():
    """格式化机器人为状态文本"""
    data = fetch_dashboard()
    bot = data.get("bot", {})

    if not bot.get("connected"):
        return "### 状态: 未连接", "---\n机器人未连接到 Minecraft 服务器\n启动 bot_server.js 后会自动连接"

    pos = bot.get("position", {})
    inventory = bot.get("inventory", [])
    equip = data.get("equipment", {})

    lines = [
        f"### 状态: 已连接",
        f"",
        f"**玩家**: {bot.get('username', '?')}",
        f"**血量**: {bot.get('health', '?')}/20",
        f"**食物**: {bot.get('food', '?')}/20",
        f"**位置**: ({round(pos.get('x',0))}, {round(pos.get('y',0))}, {round(pos.get('z',0))})",
    ]

    if equip:
        lines.append(f"**手持**: {equip.get('held_item', '?')}")
        armor = equip.get("armor", {})
        armor_parts = [v for k, v in armor.items() if v != "empty"]
        if armor_parts:
            lines.append(f"**装备**: {', '.join(armor_parts)}")

    items_text = ""
    if inventory:
        lines.append("")
        lines.append("**背包**:")
        for item in inventory[:12]:
            lines.append(f"- {item['name']} x{item['count']}")
        if len(inventory) > 12:
            lines.append(f"- ... 还有 {len(inventory) - 12} 种物品")
        items_text = "\n".join(lines[-len(inventory[:12]) - 2:])

    return "\n".join(lines), items_text


def send_command(message, username="Player"):
    """发送指令到聊天服务"""
    if not message.strip():
        return "请输入指令或消息", update_chat_history()

    try:
        r = requests.post(
            f"{CHAT_URL}/game_chat",
            json={"username": username, "message": message.strip(), "bot_name": "AIBot"},
            timeout=60
        )
        result = r.json()
        reply = result.get("reply", "无回复")
        is_cmd = result.get("is_command", False)
        task_id = result.get("task_id", "")

        prefix = "指令" if is_cmd else "闲聊"
        if task_id:
            prefix += f" [{task_id}]"

        log_line = f"**{username}**: {message.strip()}\n**AIBot** ({prefix}): {reply}\n"

        return log_line + "\n---\n"
    except Exception as e:
        return f"发送失败: {e}"


def clear_memory():
    try:
        requests.delete(f"{CHAT_URL}/memory", timeout=5)
        return "聊天记忆已清空"
    except Exception as e:
        return f"清空失败: {e}"


def update_chat_history():
    data = fetch_dashboard()
    chats = data.get("recent_chats", [])
    if not chats:
        return "*暂无聊天记录*"

    lines = []
    for h in chats[-15:]:
        tag = "指令" if h["type"] == "command" else "闲聊"
        lines.append(f"[{h['time']}] **{h['username']}** ({tag}): {h['message']}\nAIBot: {h['reply']}")
        lines.append("")

    return "\n".join(lines)


def quick_command(cmd):
    return cmd


with gr.Blocks(title="Minecraft Agent 控制台", theme=gr.themes.Soft()) as app:
    gr.Markdown("# Minecraft Agent 控制台")

    with gr.Row():
        with gr.Column(scale=1):
            bot_status = gr.Markdown("### 状态: 加载中...", every=5, value=format_bot_info()[0] if False else "")
            refresh_btn = gr.Button("刷新状态", size="sm")

        with gr.Column(scale=2):
            with gr.Tab("发送指令"):
                gr.Markdown("以 `1` 开头触发 AI 指令执行，不加 `1` 则为闲聊")
                with gr.Row():
                    cmd_input = gr.Textbox(
                        label="输入消息",
                        placeholder="例如: 1砍3棵树给我",
                        scale=4
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)

                with gr.Row():
                    gr.Examples(
                        examples=[
                            "1砍3棵树给我",
                            "1合成一把石镐",
                            "1去看看周围有什么",
                            "1帮我挖10个石头",
                            "你好啊",
                        ],
                        inputs=cmd_input,
                        label="快捷指令"
                    )

            with gr.Tab("聊天记录"):
                chat_display = gr.Markdown(value="*暂无聊天记录*")

            with gr.Tab("设置"):
                clear_btn = gr.Button("清空聊天记忆", variant="stop", size="sm")
                clear_result = gr.Textbox(label="操作结果", interactive=False)

    send_output = gr.Markdown("")

    # 自动定时刷新
    app.load(fn=lambda: format_bot_info()[0], outputs=bot_status, every=5)
    app.load(fn=update_chat_history, outputs=chat_display, every=5)

    # 事件绑定
    refresh_btn.click(fn=lambda: format_bot_info()[0], outputs=bot_status)
    send_btn.click(fn=send_command, inputs=[cmd_input], outputs=send_output).then(
        fn=lambda: format_bot_info()[0], outputs=bot_status
    ).then(
        fn=update_chat_history, outputs=chat_display
    ).then(
        fn=lambda: "", outputs=cmd_input
    )
    cmd_input.submit(fn=send_command, inputs=[cmd_input], outputs=send_output).then(
        fn=lambda: format_bot_info()[0], outputs=bot_status
    ).then(
        fn=update_chat_history, outputs=chat_display
    ).then(
        fn=lambda: "", outputs=cmd_input
    )

    clear_btn.click(fn=clear_memory, outputs=clear_result).then(
        fn=update_chat_history, outputs=chat_display
    )


if __name__ == "__main__":
    print("=" * 50)
    print("  Minecraft Agent Web 控制台")
    print(f"  后端服务: {CHAT_URL}")
    print(f"  控制台地址: http://localhost:7860")
    print("=" * 50)
    app.launch(server_name="0.0.0.0", server_port=7860)
