"""
Minecraft Agent 一键启动器
启动后端服务 + 桌面控制窗口
用法: python launcher.py
"""
if __name__ == "__main__":
    from desktop_ui import DesktopApp
    print()
    print("=" * 50)
    print("  Minecraft Agent 桌面端")
    print("=" * 50)
    print()
    DesktopApp().run()
