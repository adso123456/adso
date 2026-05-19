"""
Minecraft Agent 统一启动器

一键启动所有服务，自动打开浏览器。按 Ctrl+C 关闭所有服务。

用法: python launcher.py
"""
import subprocess
import sys
import time
import signal
import webbrowser
import os
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

processes = []
startup_ok = True


def print_status(icon, msg):
    print(f"  {icon}  {msg}")


def start_bot_server():
    """启动 Minecraft 机器人 (Node.js)"""
    print_status("", "启动 Minecraft 机器人...")
    try:
        p = subprocess.Popen(
            ["node", "bot_server.js"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        processes.append(("Minecraft 机器人", p))
        # 等待就绪
        for _ in range(30):
            try:
                r = requests.get("http://localhost:3001/status", timeout=2)
                if r.status_code == 200:
                    print_status("ok", "Minecraft 机器人就绪 (localhost:3001)")
                    return True
            except:
                pass
            time.sleep(1)
        print_status("warn", "机器人 API 已启动，但 Minecraft 可能未连接")
        return True
    except FileNotFoundError:
        print_status("err", "未找到 Node.js，请先安装: https://nodejs.org")
        return False
    except Exception as e:
        print_status("err", f"机器人启动失败: {e}")
        return False


def start_chat_service():
    """启动 AI 聊天服务 (Python/FastAPI)"""
    print_status("", "启动 AI 聊天服务...")
    try:
        p = subprocess.Popen(
            [sys.executable, "chat_service.py"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        processes.append(("AI 聊天服务", p))
        for _ in range(30):
            try:
                r = requests.get("http://localhost:8000/health", timeout=2)
                if r.status_code == 200:
                    print_status("ok", "AI 聊天服务就绪 (localhost:8000)")
                    return True
            except:
                pass
            time.sleep(1)
        print_status("err", "AI 聊天服务启动超时")
        return False
    except Exception as e:
        print_status("err", f"AI 聊天服务启动失败: {e}")
        return False


def launch_ui():
    """启动 Web 控制台 (Gradio)"""
    print_status("", "启动 Web 控制台...")
    try:
        from web_ui import app
        webbrowser.open("http://localhost:7860")
        print_status("ok", "Web 控制台已打开 (localhost:7860)")
        print()
        print("=" * 50)
        print("  所有服务已启动，按 Ctrl+C 关闭")
        print("=" * 50)
        app.launch(server_name="0.0.0.0", server_port=7860, inbrowser=False, quiet=True)
    except Exception as e:
        print_status("err", f"Web 控制台启动失败: {e}")


def cleanup():
    """清理所有子进程"""
    print()
    print("正在关闭所有服务...")
    for name, p in reversed(processes):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
            print(f"  已关闭: {name}")


def signal_handler(sig, frame):
    cleanup()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print()
    print("=" * 50)
    print("  Minecraft Agent 启动中...")
    print("=" * 50)
    print()

    if not start_bot_server():
        print_status("warn", "机器人未启动，部分功能不可用")
    if not start_chat_service():
        print_status("err", "AI 服务未启动，无法继续")
        cleanup()
        sys.exit(1)

    launch_ui()
    cleanup()
