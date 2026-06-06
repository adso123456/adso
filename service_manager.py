"""
服务进程管理 — 启动/停止/守护 bot_server.js 和 chat_service.py
从 desktop_ui.py 抽取，供无界面启动器使用
"""
import subprocess
import sys
import os
import time
import threading
from collections import deque

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))

NODE_EXE = os.path.join(ROOT, "node.exe")
if not os.path.exists(NODE_EXE):
    NODE_EXE = "node"


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
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.bot_proc.pid)],
                    capture_output=True)
                try:
                    self.bot_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.bot_proc.kill()
            else:
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
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.chat_proc.pid)],
                    capture_output=True)
                try:
                    self.chat_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.chat_proc.kill()
            else:
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
