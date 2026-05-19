"""
Minecraft Agent 一键启动器

自动启动后端服务 + Web 控制台，按 Ctrl+C 关闭所有服务。

用法: python launcher.py
"""
import sys
import time
import signal
import webbrowser
import requests
import os

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    from web_ui import svc, app

    def cleanup():
        print("\n正在关闭所有服务...")
        svc.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, lambda *_: cleanup())
    signal.signal(signal.SIGTERM, lambda *_: cleanup())

    print()
    print("=" * 50)
    print("  Minecraft Agent 启动中...")
    print("=" * 50)
    print()

    # 启动后端服务
    print("  -> 启动 Minecraft 机器人...")
    print(f"     {svc.start_bot()}")
    print("  -> 启动 AI 聊天服务...")
    print(f"     {svc.start_chat()}")

    # 等待就绪
    for _ in range(30):
        try:
            r = requests.get("http://localhost:8000/health", timeout=1)
            if r.status_code == 200:
                print("  OK AI 聊天服务就绪 (localhost:8000)")
                break
        except:
            pass
        time.sleep(1)

    print()
    print("  -> 启动 Web 控制台...")

    # 开启进程守护
    svc.toggle_watchdog(True)

    # 打开浏览器
    webbrowser.open("http://localhost:7860")

    print("  OK Web 控制台已打开 (localhost:7860)")
    print()
    print("=" * 50)
    print("  所有服务已启动，按 Ctrl+C 关闭")
    print("=" * 50)

    app.launch(server_name="0.0.0.0", server_port=7860, inbrowser=False, quiet=True)
    cleanup()


if __name__ == "__main__":
    main()
