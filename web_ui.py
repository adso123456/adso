"""
Minecraft Agent Web 控制台
内置进程管理 + 日志集成

启动方式: python launcher.py  (推荐)
          python web_ui.py   (需先手动启动 bot_server + chat_service)
访问地址: http://localhost:7860
"""
import subprocess
import sys
import os
import time
import threading
import requests
from collections import deque

import gradio as gr
from config import cfg

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))

CHAT_URL = f"http://{cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT}"

# 便携版 node.exe
NODE_EXE = os.path.join(ROOT, "node.exe")
if not os.path.exists(NODE_EXE):
    NODE_EXE = "node"  # fallback to system node


# ============================================================
# ServiceManager - 后端进程管理
# ============================================================

class ServiceManager:
    def __init__(self):
        self.bot_proc = None
        self.chat_proc = None
        self.bot_logs = deque(maxlen=200)
        self.chat_logs = deque(maxlen=200)
        self.auto_restart = False
        self._bot_reader = None
        self._chat_reader = None
        self._watchdog = None
        self._alive = True

    # ----- 日志读取线程 -----

    def _stream_logs(self, proc, buffer, tag):
        for line in iter(proc.stdout.readline, ""):
            if not self._alive:
                break
            stripped = line.strip()
            if stripped:
                buffer.append(f"[{tag}] {stripped}")

    # ----- 机器人 -----

    def start_bot(self):
        if self.bot_proc and self.bot_proc.poll() is None:
            return "机器人已在运行中"
        try:
            self.bot_proc = subprocess.Popen(
                [NODE_EXE, "bot_server.js"],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace"
            )
            self._bot_reader = threading.Thread(
                target=self._stream_logs,
                args=(self.bot_proc, self.bot_logs, "bot"),
                daemon=True
            )
            self._bot_reader.start()
            self.bot_logs.append("[系统] Minecraft 机器人已启动")
            return "机器人已启动"
        except FileNotFoundError:
            self.bot_logs.append("[系统] 未找到 Node.js，请先安装")
            return "启动失败: 未找到 Node.js"
        except Exception as e:
            self.bot_logs.append(f"[系统] 启动失败: {e}")
            return f"启动失败: {e}"

    def stop_bot(self):
        if self.bot_proc and self.bot_proc.poll() is None:
            self.bot_proc.terminate()
            try:
                self.bot_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.bot_proc.kill()
            self.bot_logs.append("[系统] Minecraft 机器人已停止")
            return "机器人已停止"
        return "机器人未在运行"

    # ----- AI 聊天服务 -----

    def start_chat(self):
        if self.chat_proc and self.chat_proc.poll() is None:
            return "AI 服务已在运行中"
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--run-chat-service"]
            else:
                cmd = [sys.executable, "chat_service.py"]
            self.chat_proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace"
            )
            self._chat_reader = threading.Thread(
                target=self._stream_logs,
                args=(self.chat_proc, self.chat_logs, "chat"),
                daemon=True
            )
            self._chat_reader.start()
            self.chat_logs.append("[系统] AI 聊天服务已启动")
            return "AI 服务已启动"
        except Exception as e:
            self.chat_logs.append(f"[系统] 启动失败: {e}")
            return f"启动失败: {e}"

    def stop_chat(self):
        if self.chat_proc and self.chat_proc.poll() is None:
            self.chat_proc.terminate()
            try:
                self.chat_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.chat_proc.kill()
            self.chat_logs.append("[系统] AI 聊天服务已停止")
            return "AI 服务已停止"
        return "AI 服务未在运行"

    # ----- 批量控制 -----

    def start_all(self):
        r1 = self.start_bot()
        r2 = self.start_chat()
        return {bot_status: r1, chat_status: r2}

    def stop_all(self):
        r1 = self.stop_bot()
        r2 = self.stop_chat()
        return {bot_status: r1, chat_status: r2}

    # ----- 状态 -----

    def get_status(self):
        bot_ok = self.bot_proc is not None and self.bot_proc.poll() is None
        chat_ok = self.chat_proc is not None and self.chat_proc.poll() is None
        return {
            "bot_running": bot_ok,
            "chat_running": chat_ok,
            "auto_restart": self.auto_restart
        }

    def format_service_status(self):
        s = self.get_status()
        lines = [
            f"Minecraft 机器人: **{'运行中' if s['bot_running'] else '已停止'}**",
            f"AI 聊天服务: **{'运行中' if s['chat_running'] else '已停止'}**",
            f"进程守护: **{'已开启' if s['auto_restart'] else '已关闭'}**",
        ]
        return "\n".join(lines)

    # ----- 日志 -----

    def get_logs(self, service="all"):
        if service == "bot":
            return "\n".join(self.bot_logs) or "(暂无日志)"
        elif service == "chat":
            return "\n".join(self.chat_logs) or "(暂无日志)"
        else:
            combined = "\n".join(self.chat_logs) + "\n" + "\n".join(self.bot_logs)
            return combined.strip() or "(暂无日志)"

    def clear_logs(self):
        self.bot_logs.clear()
        self.chat_logs.clear()
        return "日志已清空"

    # ----- 进程守护 -----

    def toggle_watchdog(self, enable):
        if enable:
            self.auto_restart = True
            self._alive = True
            if self._watchdog is None or not self._watchdog.is_alive():
                self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
                self._watchdog.start()
            self.bot_logs.append("[系统] 进程守护已开启")
            return "进程守护已开启"
        else:
            self.auto_restart = False
            self.bot_logs.append("[系统] 进程守护已关闭")
            return "进程守护已关闭"

    def _watchdog_loop(self):
        while self.auto_restart:
            if self.bot_proc and self.bot_proc.poll() is not None:
                self.bot_logs.append("[守护] 机器人异常退出，自动重启...")
                self.start_bot()
            if self.chat_proc and self.chat_proc.poll() is not None:
                self.chat_logs.append("[守护] AI 服务异常退出，自动重启...")
                self.start_chat()
            time.sleep(5)

    # ----- 优雅关闭 -----

    def shutdown(self):
        self._alive = False
        self.auto_restart = False
        self.stop_bot()
        self.stop_chat()


# 全局实例
svc = ServiceManager()


# ============================================================
# Gradio UI 回调函数
# ============================================================

def fetch_dashboard():
    try:
        r = requests.get(f"{CHAT_URL}/dashboard", timeout=5)
        return r.json()
    except:
        return {"bot": {"connected": False}, "recent_chats": [], "memory_count": 0}


def format_bot_info():
    data = fetch_dashboard()
    bot = data.get("bot", {})

    if not bot.get("connected"):
        return "### 状态: 未连接\n\n机器人未连接到 Minecraft 服务器"

    pos = bot.get("position", {})
    equip = data.get("equipment", {})
    inventory = bot.get("inventory", [])

    lines = [
        "### 状态: 已连接",
        "",
        f"**玩家**: {bot.get('username', '?')}",
        f"**血量**: {bot.get('health', '?')}/20",
        f"**食物**: {bot.get('food', '?')}/20",
        f"**位置**: ({round(pos.get('x',0))}, {round(pos.get('y',0))}, {round(pos.get('z',0))})",
    ]

    if equip:
        lines.append(f"**手持**: {equip.get('held_item', '?')}")
        armor = equip.get("armor", {})
        parts = [v for v in armor.values() if v != "empty"]
        if parts:
            lines.append(f"**装备**: {', '.join(parts)}")

    if inventory:
        lines.append("")
        lines.append("**背包**:")
        for item in inventory[:12]:
            lines.append(f"- {item['name']} x{item['count']}")
        if len(inventory) > 12:
            lines.append(f"- ... 还有 {len(inventory) - 12} 种物品")

    return "\n".join(lines)


def send_command(message, username="Player"):
    if not message.strip():
        return "请输入指令或消息"

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

        return f"**{username}**: {message.strip()}\n**AIBot** ({prefix}): {reply}\n"
    except Exception as e:
        return f"发送失败: {e}"


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


def clear_memory():
    try:
        requests.delete(f"{CHAT_URL}/memory", timeout=5)
        return "聊天记忆已清空"
    except Exception as e:
        return f"清空失败: {e}"


# ============================================================
# Gradio 界面
# ============================================================

with gr.Blocks(title="Minecraft Agent 控制台", theme=gr.themes.Soft()) as app:
    gr.Markdown("# Minecraft Agent 控制台")

    with gr.Tabs():
        # ============ Tab 1: 控制面板 ============
        with gr.TabItem("控制面板"):
            with gr.Row():
                with gr.Column(scale=1):
                    bot_status_md = gr.Markdown("### 状态: 加载中...")
                    refresh_btn = gr.Button("刷新状态", size="sm")

                with gr.Column(scale=2):
                    gr.Markdown("以 `1` 开头触发 AI 指令执行，不加 `1` 则为闲聊")
                    with gr.Row():
                        cmd_input = gr.Textbox(
                            label="输入消息",
                            placeholder="例如: 1砍3棵树给我",
                            scale=4
                        )
                        send_btn = gr.Button("发送", variant="primary", scale=1)

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

            send_output = gr.Markdown("")

            # 刷新绑定
            app.load(fn=format_bot_info, outputs=bot_status_md, every=5)

            refresh_btn.click(fn=format_bot_info, outputs=bot_status_md)

            send_btn.click(fn=send_command, inputs=[cmd_input], outputs=send_output)\
                .then(fn=format_bot_info, outputs=bot_status_md)\
                .then(fn=lambda: "", outputs=cmd_input)

            cmd_input.submit(fn=send_command, inputs=[cmd_input], outputs=send_output)\
                .then(fn=format_bot_info, outputs=bot_status_md)\
                .then(fn=lambda: "", outputs=cmd_input)

        # ============ Tab 2: 服务管理 ============
        with gr.TabItem("服务管理"):
            gr.Markdown("### 后端服务控制")

            service_status_md = gr.Markdown("加载中...")
            svc_result = gr.Textbox(label="操作结果", interactive=False)

            with gr.Row():
                start_all_btn = gr.Button("全部启动", variant="primary")
                stop_all_btn = gr.Button("全部停止", variant="stop")

            with gr.Row():
                start_bot_btn = gr.Button("启动机器人", size="sm")
                stop_bot_btn = gr.Button("停止机器人", size="sm")
                start_chat_btn = gr.Button("启动 AI 服务", size="sm")
                stop_chat_btn = gr.Button("停止 AI 服务", size="sm")

            with gr.Row():
                watchdog_on = gr.Button("开启进程守护", size="sm")
                watchdog_off = gr.Button("关闭进程守护", size="sm")

            def refresh_service_status():
                return svc.format_service_status()

            app.load(fn=refresh_service_status, outputs=service_status_md, every=3)

            start_all_btn.click(fn=lambda: (svc.start_all() or "已执行全部启动") and svc.format_service_status(),
                               outputs=service_status_md)
            stop_all_btn.click(fn=lambda: (svc.stop_all() or "已执行全部停止") and svc.format_service_status(),
                              outputs=service_status_md)

            start_bot_btn.click(fn=lambda: (svc.start_bot(), svc.format_service_status())[1],
                               outputs=service_status_md)
            stop_bot_btn.click(fn=lambda: (svc.stop_bot(), svc.format_service_status())[1],
                              outputs=service_status_md)
            start_chat_btn.click(fn=lambda: (svc.start_chat(), svc.format_service_status())[1],
                                outputs=service_status_md)
            stop_chat_btn.click(fn=lambda: (svc.stop_chat(), svc.format_service_status())[1],
                               outputs=service_status_md)

            watchdog_on.click(fn=lambda: (svc.toggle_watchdog(True), svc.format_service_status())[1],
                             outputs=service_status_md)
            watchdog_off.click(fn=lambda: (svc.toggle_watchdog(False), svc.format_service_status())[1],
                              outputs=service_status_md)

        # ============ Tab 3: 系统日志 ============
        with gr.TabItem("系统日志"):
            with gr.Row():
                log_filter = gr.Dropdown(
                    choices=[("全部", "all"), ("Minecraft 机器人", "bot"), ("AI 聊天服务", "chat")],
                    value="all",
                    label="筛选服务"
                )
                log_clear_btn = gr.Button("清空日志", size="sm")

            log_display = gr.Textbox(
                label="日志输出",
                lines=18,
                max_lines=25,
                interactive=False,
                autoscroll=True
            )

            def refresh_logs(service):
                return svc.get_logs(service)

            app.load(fn=lambda: svc.get_logs("all"), outputs=log_display, every=2)

            log_filter.change(fn=refresh_logs, inputs=[log_filter], outputs=log_display)
            log_clear_btn.click(fn=lambda: svc.clear_logs() and svc.get_logs("all"),
                               outputs=log_display)

        # ============ Tab 4: 聊天记录 ============
        with gr.TabItem("聊天记录"):
            chat_display = gr.Markdown("*暂无聊天记录*")
            app.load(fn=update_chat_history, outputs=chat_display, every=5)

        # ============ Tab 5: 设置 ============
        with gr.TabItem("设置"):
            gr.Markdown("### 数据管理")
            clear_mem_btn = gr.Button("清空聊天记忆", variant="stop", size="sm")
            clear_mem_result = gr.Textbox(label="操作结果", interactive=False)

            clear_mem_btn.click(fn=clear_memory, outputs=clear_mem_result)\
                .then(fn=update_chat_history, outputs=chat_display)


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run-chat-service":
        # 子进程模式：运行 AI 聊天服务
        import uvicorn
        from chat_service import app as chat_app
        print("=" * 50)
        print("  Minecraft AI 聊天服务 (子进程)")
        print(f"  监听: {cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT}")
        print("=" * 50)
        uvicorn.run(chat_app, host=cfg.CHAT_SERVICE_HOST, port=cfg.CHAT_SERVICE_PORT)
    else:
        # 主进程模式：运行 Web 控制台
        print("=" * 50)
        print("  Minecraft Agent Web 控制台")
        print(f"  后端 API: {CHAT_URL}")
        print(f"  控制台:   http://localhost:7860")
        print("=" * 50)
        app.launch(server_name="0.0.0.0", server_port=7860)
