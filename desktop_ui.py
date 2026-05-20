"""
Minecraft Agent 桌面控制台
原生 tkinter 窗口界面 — 像 QQ 一样简单
"""
import subprocess
import sys
import os
import time
import threading
import requests
import shutil
from collections import deque
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

from dotenv import load_dotenv, dotenv_values, set_key
from config import cfg

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))

CHAT_URL = f"http://{cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT}"
NODE_EXE = os.path.join(ROOT, "node.exe")
if not os.path.exists(NODE_EXE):
    NODE_EXE = "node"

load_dotenv()


# ============================================================
# ServiceManager — 后端进程管理
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

    def _stream_logs(self, proc, buf, tag):
        for line in iter(proc.stdout.readline, ""):
            if not self._alive:
                break
            s = line.strip()
            if s:
                buf.append(f"[{tag}] {s}")

    def start_bot(self):
        if self.bot_proc and self.bot_proc.poll() is None:
            return "机器人已在运行中"
        try:
            self.bot_proc = subprocess.Popen(
                [NODE_EXE, "bot_server.js"], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            self._bot_reader = threading.Thread(
                target=self._stream_logs, args=(self.bot_proc, self.bot_logs, "bot"), daemon=True)
            self._bot_reader.start()
            self.bot_logs.append("[系统] Minecraft 机器人已启动")
            return "机器人已启动"
        except FileNotFoundError:
            self.bot_logs.append("[系统] 未找到 Node.js")
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

    def start_chat(self):
        if self.chat_proc and self.chat_proc.poll() is None:
            return "AI 服务已在运行中"
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--run-chat-service"]
            else:
                cmd = [sys.executable, "chat_service.py"]
            self.chat_proc = subprocess.Popen(
                cmd, cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace")
            self._chat_reader = threading.Thread(
                target=self._stream_logs, args=(self.chat_proc, self.chat_logs, "chat"), daemon=True)
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

    def get_status(self):
        bot_ok = self.bot_proc is not None and self.bot_proc.poll() is None
        chat_ok = self.chat_proc is not None and self.chat_proc.poll() is None
        return {"bot": bot_ok, "chat": chat_ok, "watchdog": self.auto_restart}

    def get_logs(self, svc="all"):
        if svc == "bot":
            return "\n".join(self.bot_logs) or "(暂无日志)"
        if svc == "chat":
            return "\n".join(self.chat_logs) or "(暂无日志)"
        return "\n".join(self.chat_logs) + "\n" + "\n".join(self.bot_logs)

    def clear_logs(self):
        self.bot_logs.clear()
        self.chat_logs.clear()

    def toggle_watchdog(self, on):
        if on:
            self.auto_restart = True
            self._alive = True
            if self._watchdog is None or not self._watchdog.is_alive():
                self._watchdog = threading.Thread(target=self._loop, daemon=True)
                self._watchdog.start()
            return "进程守护已开启"
        else:
            self.auto_restart = False
            return "进程守护已关闭"

    def _loop(self):
        while self.auto_restart:
            if self.bot_proc and self.bot_proc.poll() is not None:
                self.bot_logs.append("[守护] 机器人异常退出，自动重启...")
                self.start_bot()
            if self.chat_proc and self.chat_proc.poll() is not None:
                self.chat_logs.append("[守护] AI 服务异常退出，自动重启...")
                self.start_chat()
            time.sleep(5)

    def shutdown(self):
        self._alive = False
        self.auto_restart = False
        self.stop_bot()
        self.stop_chat()


svc = ServiceManager()


# ============================================================
# DesktopApp — tkinter QQ 风格界面
# ============================================================

class DesktopApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Minecraft Agent")
        self.root.geometry("860x620")
        self.root.minsize(700, 500)
        self.root.configure(bg="#f0f0f0")

        self._build_ui()
        self._start_services()
        self._schedule_refresh()

        # 窗口关闭 → 优雅关闭服务
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # ---- 顶部标题栏 ----
        title_frame = tk.Frame(self.root, bg="#2196F3", height=44)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="  Minecraft Agent", font=("Microsoft YaHei", 14, "bold"),
                 fg="white", bg="#2196F3").pack(side=tk.LEFT, padx=12, pady=8)

        # 进程守护开关
        self.watchdog_var = tk.BooleanVar(value=False)
        tk.Checkbutton(title_frame, text="进程守护", variable=self.watchdog_var,
                       command=self._toggle_watchdog,
                       fg="white", bg="#2196F3", selectcolor="#2196F3",
                       activebackground="#2196F3", activeforeground="white",
                       font=("Microsoft YaHei", 9)).pack(side=tk.RIGHT, padx=12)

        # ---- 主区域 (上下分区) ----
        main = tk.Frame(self.root, bg="#f0f0f0")
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # ---- 上半区：状态 + 控制 (左右分栏) ----
        top = tk.Frame(main, bg="#f0f0f0")
        top.pack(fill=tk.X, pady=(0, 6))

        # --- 左: 机器人状态 ---
        status_frame = tk.LabelFrame(top, text="机器人状态", font=("Microsoft YaHei", 10),
                                     bg="white", fg="#333", padx=8, pady=4)
        status_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.bot_status_text = tk.Text(status_frame, height=6, width=40, font=("Consolas", 10),
                                       bg="white", fg="#333", relief=tk.FLAT,
                                       wrap=tk.WORD, state=tk.DISABLED)
        self.bot_status_text.pack(fill=tk.BOTH, expand=True)

        # --- 右: 服务控制 ---
        ctrl_frame = tk.LabelFrame(top, text="服务控制", font=("Microsoft YaHei", 10),
                                   bg="white", fg="#333", padx=8, pady=4)
        ctrl_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(8, 0))

        # 服务状态指示灯
        status_row = tk.Frame(ctrl_frame, bg="white")
        status_row.pack(fill=tk.X, pady=(2, 6))

        self.bot_light = tk.Label(status_row, text=" ● Bot: 检测中...", font=("Microsoft YaHei", 9),
                                  fg="#999", bg="white")
        self.bot_light.pack(side=tk.LEFT, padx=(0, 16))
        self.chat_light = tk.Label(status_row, text="● AI: 检测中...", font=("Microsoft YaHei", 9),
                                   fg="#999", bg="white")
        self.chat_light.pack(side=tk.LEFT)

        # 按钮区
        btn_font = ("Microsoft YaHei", 9)
        row1 = tk.Frame(ctrl_frame, bg="white")
        row1.pack(fill=tk.X, pady=2)
        tk.Button(row1, text="全部启动", font=btn_font, bg="#4CAF50", fg="white",
                  relief=tk.FLAT, padx=12, pady=2, command=self._start_all).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(row1, text="全部停止", font=btn_font, bg="#f44336", fg="white",
                  relief=tk.FLAT, padx=12, pady=2, command=self._stop_all).pack(side=tk.LEFT)

        row2 = tk.Frame(ctrl_frame, bg="white")
        row2.pack(fill=tk.X, pady=2)
        tk.Button(row2, text="启动 Bot", font=btn_font, relief=tk.FLAT, padx=8, pady=1,
                  command=self._start_bot).pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(row2, text="停止 Bot", font=btn_font, relief=tk.FLAT, padx=8, pady=1,
                  command=self._stop_bot).pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(row2, text="启动 AI", font=btn_font, relief=tk.FLAT, padx=8, pady=1,
                  command=self._start_chat).pack(side=tk.LEFT, padx=(0, 2))
        tk.Button(row2, text="停止 AI", font=btn_font, relief=tk.FLAT, padx=8, pady=1,
                  command=self._stop_chat).pack(side=tk.LEFT)

        row3 = tk.Frame(ctrl_frame, bg="white")
        row3.pack(fill=tk.X, pady=2)
        tk.Button(row3, text="连接 MC", font=btn_font, bg="#FF9800", fg="white",
                  relief=tk.FLAT, padx=8, pady=1, command=self._connect_bot).pack(side=tk.LEFT)
        tk.Button(row3, text="⚙ 设置", font=btn_font, relief=tk.FLAT, padx=8, pady=1,
                  command=self._open_settings).pack(side=tk.RIGHT)

        # ---- 下半区：日志 + 指令 ----
        bottom = tk.Frame(main, bg="#f0f0f0")
        bottom.pack(fill=tk.BOTH, expand=True)

        log_frame = tk.LabelFrame(bottom, text="系统日志", font=("Microsoft YaHei", 10),
                                  bg="white", fg="#333", padx=4, pady=2)
        log_frame.pack(fill=tk.BOTH, expand=True)

        # 日志过滤行
        log_toolbar = tk.Frame(log_frame, bg="white")
        log_toolbar.pack(fill=tk.X, pady=(0, 2))

        self.log_filter_var = tk.StringVar(value="all")
        for val, label in [("all", "全部"), ("bot", "Bot"), ("chat", "AI")]:
            tk.Radiobutton(log_toolbar, text=label, variable=self.log_filter_var, value=val,
                           font=("Microsoft YaHei", 8), bg="white", command=self._refresh_logs)\
                .pack(side=tk.LEFT, padx=2)

        tk.Button(log_toolbar, text="清空日志", font=("Microsoft YaHei", 8), relief=tk.FLAT,
                  command=self._clear_logs).pack(side=tk.RIGHT, padx=4)

        # 日志文本框
        self.log_text = tk.Text(log_frame, font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="white", relief=tk.FLAT,
                                wrap=tk.WORD, state=tk.DISABLED)
        log_scroll = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # ---- 底部指令栏 ----
        cmd_frame = tk.Frame(main, bg="#f0f0f0")
        cmd_frame.pack(fill=tk.X, pady=(6, 0))

        tk.Label(cmd_frame, text="指令:", font=("Microsoft YaHei", 10),
                 bg="#f0f0f0", fg="#333").pack(side=tk.LEFT, padx=(0, 6))

        self.cmd_var = tk.StringVar()
        self.cmd_entry = tk.Entry(cmd_frame, textvariable=self.cmd_var, font=("Microsoft YaHei", 11),
                                  relief=tk.FLAT, bg="white", fg="#333",
                                  insertbackground="#333")
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
        self.cmd_entry.bind("<Return>", lambda e: self._send_cmd())
        self.cmd_entry.bind("<KP_Enter>", lambda e: self._send_cmd())

        tk.Button(cmd_frame, text="发送", font=("Microsoft YaHei", 10, "bold"),
                  bg="#2196F3", fg="white", relief=tk.FLAT, padx=20, pady=4,
                  command=self._send_cmd).pack(side=tk.LEFT, padx=(6, 0))

        # 提示文字
        tk.Label(main, text="以 1 开头 = AI 指令执行 | 不加 1 = 闲聊模式",
                 font=("Microsoft YaHei", 8), fg="#999", bg="#f0f0f0")\
            .pack(anchor=tk.W, pady=(2, 0))

        # ---- 状态栏 ----
        self.status_bar = tk.Label(self.root, text="就绪", font=("Microsoft YaHei", 8),
                                   bg="#e0e0e0", fg="#666", anchor=tk.W, padx=8)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # ----- 服务操作 -----

    def _start_services(self):
        threading.Thread(target=self._do_start_all, daemon=True).start()

    def _wait_for_bot_ready(self, timeout=15):
        """轮询等待 Bot 服务端口就绪，返回 True/False"""
        for _ in range(timeout):
            # 先检查进程是不是已经挂了
            if svc.bot_proc and svc.bot_proc.poll() is not None:
                exit_code = svc.bot_proc.returncode
                self._log(f"[错误] Bot 进程异常退出，退出码: {exit_code}")
                # 打印最近几条 bot 日志帮助排查
                recent = list(svc.bot_logs)[-5:]
                for line in recent:
                    self._log(f"  {line}")
                return False
            try:
                r = requests.get(f"{cfg.BOT_URL}/status", timeout=2)
                if r.status_code == 200:
                    return True
            except:
                pass
            time.sleep(1)
        return False

    def _do_start_all(self):
        self._log("[系统] 正在启动所有服务...")
        svc.start_bot()
        if self._wait_for_bot_ready():
            self._log("[系统] Bot 服务就绪 (port 3001)")
        else:
            self._log("[警告] Bot 服务启动超时，请检查日志")
        svc.start_chat()
        # 等待 AI 服务就绪
        for _ in range(15):
            try:
                r = requests.get(f"{CHAT_URL}/health", timeout=1)
                if r.status_code == 200:
                    self._log("[系统] AI 聊天服务就绪 (port 8000)")
                    break
            except:
                pass
            time.sleep(1)
        # 连接 Minecraft
        self._connect_bot()
        svc.toggle_watchdog(True)
        self.root.after(0, lambda: self.watchdog_var.set(True))
        self._log("[系统] 所有服务已启动，可以开始使用")
        self.root.after(0, self._refresh_all)

    def _connect_bot(self, port=None):
        """发送连接请求让 Bot 连入 Minecraft"""
        mc_port = port or int(os.getenv("MC_SERVER_PORT", "25565"))
        try:
            r = requests.post(f"{cfg.BOT_URL}/connect",
                            json={"port": mc_port}, timeout=10)
            if r.status_code == 200:
                self._log(f"[系统] 已发送连接请求 → localhost:{mc_port}")
            else:
                self._log(f"[系统] 连接请求失败: {r.status_code}")
        except Exception as e:
            self._log(f"[系统] Bot 服务未就绪，请先启动 Bot: {e}")

    def _start_all(self):
        threading.Thread(target=lambda: (
            svc.start_bot(),
            self._wait_for_bot_ready(),
            svc.start_chat(),
            time.sleep(1),
            self._connect_bot(),
            self.root.after(0, self._refresh_all)
        ), daemon=True).start()
        self._log("[系统] 已执行全部启动")

    def _stop_all(self):
        svc.stop_chat()
        svc.stop_bot()
        self._refresh_all()
        self._log("[系统] 已执行全部停止")

    def _start_bot(self):
        result = svc.start_bot()
        self._log(f"[系统] {result}")
        self._refresh_all()

    def _stop_bot(self):
        result = svc.stop_bot()
        self._log(f"[系统] {result}")
        self._refresh_all()

    def _start_chat(self):
        result = svc.start_chat()
        self._log(f"[系统] {result}")
        self._refresh_all()

    def _stop_chat(self):
        result = svc.stop_chat()
        self._log(f"[系统] {result}")
        self._refresh_all()

    def _toggle_watchdog(self):
        on = self.watchdog_var.get()
        result = svc.toggle_watchdog(on)
        self._log(f"[系统] {result}")

    # ----- 日志 -----

    def _log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"{msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_logs(self):
        svc_name = self.log_filter_var.get()
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.insert("1.0", svc.get_logs(svc_name))
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_logs(self):
        svc.clear_logs()
        self._refresh_logs()
        self._log("[系统] 日志已清空")

    # ----- 指令发送 -----

    def _send_cmd(self):
        msg = self.cmd_var.get().strip()
        if not msg:
            return
        self.cmd_var.set("")
        self._log(f">> {msg}")
        threading.Thread(target=self._do_send, args=(msg,), daemon=True).start()

    def _do_send(self, msg):
        try:
            r = requests.post(f"{CHAT_URL}/game_chat",
                              json={"username": "Player", "message": msg, "bot_name": "AIBot"},
                              timeout=60)
            data = r.json()
            reply = data.get("reply", "无回复")
            is_cmd = data.get("is_command", False)
            tag = "指令" if is_cmd else "闲聊"
            self.root.after(0, lambda: self._log(f"   AIBot ({tag}): {reply}"))
        except Exception as e:
            self.root.after(0, lambda: self._log(f"   [错误] 发送失败: {e}"))

    # ----- 状态刷新 -----

    def _refresh_all(self):
        """刷新 bot 状态 + 服务指示灯"""
        # 服务指示灯
        s = svc.get_status()
        self.bot_light.config(
            text=" ● Bot: 运行中" if s["bot"] else " ● Bot: 已停止",
            fg="#4CAF50" if s["bot"] else "#f44336")
        self.chat_light.config(
            text="● AI: 运行中" if s["chat"] else "● AI: 已停止",
            fg="#4CAF50" if s["chat"] else "#f44336")

        # 机器人详情
        threading.Thread(target=self._fetch_bot_info, daemon=True).start()

    # 自动重连：上次连接失败时记录时间，避免频繁重试
    _last_reconnect_attempt = 0

    def _fetch_bot_info(self):
        try:
            r = requests.get(f"{CHAT_URL}/dashboard", timeout=5)
            data = r.json()
            bot = data.get("bot", {})

            if not bot.get("connected"):
                self.root.after(0, lambda: self._set_bot_status(
                    "状态: 未连接\n\n请确保 Minecraft 已打开世界并开启局域网模式"))
                # 自动重连：每30秒尝试一次
                now = time.time()
                if svc.get_status()["bot"] and now - self._last_reconnect_attempt > 30:
                    self._last_reconnect_attempt = now
                    threading.Thread(target=self._connect_bot, daemon=True).start()
                return

            pos = bot.get("position", {})
            equip = data.get("equipment", {})
            inv = bot.get("inventory", [])

            lines = [
                f"玩家: {bot.get('username', '?')}",
                f"血量: {bot.get('health', '?')}/20    食物: {bot.get('food', '?')}/20",
                f"位置: ({round(pos.get('x', 0))}, {round(pos.get('y', 0))}, {round(pos.get('z', 0))})",
            ]
            if equip:
                lines.append(f"手持: {equip.get('held_item', '?')}")
            if inv:
                items = [f"{it['name']} x{it['count']}" for it in inv[:6]]
                lines.append(f"背包: {', '.join(items)}")
                if len(inv) > 6:
                    lines[-1] += f" (共 {len(inv)} 种)"

            self.root.after(0, lambda: self._set_bot_status("\n".join(lines)))
        except:
            self.root.after(0, lambda: self._set_bot_status(
                "状态: 无法获取\n\n请检查服务是否已启动"))

    def _set_bot_status(self, text):
        self.bot_status_text.configure(state=tk.NORMAL)
        self.bot_status_text.delete("1.0", tk.END)
        self.bot_status_text.insert("1.0", text)
        self.bot_status_text.configure(state=tk.DISABLED)

    def _schedule_refresh(self):
        self._refresh_all()
        self._refresh_logs()
        self.root.after(3000, self._schedule_refresh)

    # ----- 设置窗口 -----

    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.geometry("500x380")
        win.resizable(False, False)
        win.configure(bg="white")
        win.transient(self.root)
        win.grab_set()

        tk.Label(win, text="Minecraft Agent 设置", font=("Microsoft YaHei", 14, "bold"),
                 fg="#2196F3", bg="white").pack(pady=(16, 4))
        tk.Label(win, text="API Key 可从 dashscope.aliyun.com 免费获取",
                 font=("Microsoft YaHei", 8), fg="#999", bg="white").pack()

        # API Key
        f1 = tk.Frame(win, bg="white")
        f1.pack(fill=tk.X, padx=20, pady=(16, 4))
        tk.Label(f1, text="DashScope API Key", font=("Microsoft YaHei", 10),
                 bg="white", fg="#333").pack(anchor=tk.W)
        api_key_var = tk.StringVar(value=os.getenv("DASHSCOPE_API_KEY", ""))
        api_entry = tk.Entry(f1, textvariable=api_key_var, font=("Consolas", 10),
                             show="*", relief=tk.SOLID, bd=1)
        api_entry.pack(fill=tk.X, ipady=4, pady=(4, 0))

        # MC 端口
        f2 = tk.Frame(win, bg="white")
        f2.pack(fill=tk.X, padx=20, pady=4)
        tk.Label(f2, text="MC 服务器端口", font=("Microsoft YaHei", 10),
                 bg="white", fg="#333").pack(anchor=tk.W)
        port_var = tk.StringVar(value=os.getenv("MC_SERVER_PORT", "25565"))
        tk.Entry(f2, textvariable=port_var, font=("Consolas", 10),
                 relief=tk.SOLID, bd=1, width=10).pack(anchor=tk.W, ipady=4, pady=(4, 0))

        def do_save():
            env_path = os.path.join(ROOT, ".env")
            example_path = os.path.join(ROOT, ".env.example")
            if not os.path.exists(env_path) and os.path.exists(example_path):
                shutil.copy(example_path, env_path)
            if not os.path.exists(env_path):
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("")
            if api_key_var.get().strip():
                set_key(env_path, "DASHSCOPE_API_KEY", api_key_var.get().strip())
                os.environ["DASHSCOPE_API_KEY"] = api_key_var.get().strip()
            if port_var.get().strip():
                set_key(env_path, "MC_SERVER_PORT", port_var.get().strip())
            result_label.config(text="配置已保存", fg="#4CAF50")
            self._log("[系统] 配置已更新")

        def do_test():
            key = api_key_var.get().strip()
            if not key:
                result_label.config(text="请先输入 API Key", fg="#f44336")
                return
            try:
                import dashscope
                dashscope.api_key = key
                from dashscope import Generation
                resp = Generation.call(model="qwen-turbo", prompt="hi", result_format="message")
                if resp.status_code == 200:
                    result_label.config(text="API Key 有效", fg="#4CAF50")
                else:
                    result_label.config(text=f"API 错误: {resp.code} {resp.message}", fg="#f44336")
            except Exception as e:
                result_label.config(text=f"连接失败: {e}", fg="#f44336")

        btn_row = tk.Frame(win, bg="white")
        btn_row.pack(fill=tk.X, padx=20, pady=8)
        tk.Button(btn_row, text="保存配置", font=("Microsoft YaHei", 10),
                  bg="#4CAF50", fg="white", relief=tk.FLAT, padx=16, pady=4,
                  command=do_save).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(btn_row, text="测试连接", font=("Microsoft YaHei", 10),
                  relief=tk.FLAT, padx=12, pady=4, command=do_test).pack(side=tk.LEFT)

        result_label = tk.Label(win, text="", font=("Microsoft YaHei", 9), bg="white")
        result_label.pack(pady=4)

        # 环境检测
        env_frame = tk.LabelFrame(win, text="环境检测", font=("Microsoft YaHei", 9),
                                  bg="white", fg="#333", padx=12, pady=8)
        env_frame.pack(fill=tk.X, padx=20, pady=(12, 8))

        checks = {}
        if os.path.isfile(NODE_EXE) or shutil.which("node"):
            checks["Node.js"] = True
        else:
            checks["Node.js"] = False
        if os.path.exists(os.path.join(ROOT, "node_modules")):
            checks["node_modules"] = True
        else:
            checks["node_modules"] = False
        api_key = os.getenv("DASHSCOPE_API_KEY", "")
        checks["API Key"] = bool(api_key and api_key != "your_api_key_here")

        for i, (name, ok) in enumerate(checks.items()):
            tk.Label(env_frame, text=f"{'✓' if ok else '✗'} {name}",
                     font=("Microsoft YaHei", 9),
                     fg="#4CAF50" if ok else "#f44336",
                     bg="white").grid(row=i // 2, column=i % 2, sticky=tk.W, padx=8, pady=2)

    # ----- 关闭 -----

    def _on_close(self):
        if messagebox.askokcancel("退出", "确定要退出吗？\n所有服务将被关闭。"):
            svc.shutdown()
            self.root.destroy()

    def run(self):
        self.root.mainloop()


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run-chat-service":
        import uvicorn
        from chat_service import app as chat_app
        print(f"Minecraft AI 聊天服务 (监听 {cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT})")
        uvicorn.run(chat_app, host=cfg.CHAT_SERVICE_HOST, port=cfg.CHAT_SERVICE_PORT)
    else:
        print("启动 Minecraft Agent 桌面端...")
        DesktopApp().run()
