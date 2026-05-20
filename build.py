"""
Minecraft Agent 打包构建脚本

用法: python build.py
输出: dist/MinecraftAgent/  (可直接运行的文件夹)
"""
import subprocess
import sys
import os
import time
import shutil
import zipfile


ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_NAME = f"MinecraftAgent_{time.strftime('%Y%m%d_%H%M%S')}"
DIST = os.path.join(ROOT, "dist", DIST_NAME)
PYINSTALLER = [sys.executable, "-m", "PyInstaller"]


def step(msg):
    print(f"  -> {msg}...")


def done(msg="OK"):
    print(f"     {msg}")


def main():
    print()
    print("=" * 60)
    print("  Minecraft Agent 打包构建")
    print("=" * 60)
    print()

    # ---- 清理旧构建 ----
    step("清理旧构建产物")
    for exe in ["MinecraftAgent.exe"]:
        subprocess.run(["taskkill", "/f", "/im", exe],
                       capture_output=True, timeout=5)
    # 只清理 build 缓存，dist 用时间戳子目录避免文件锁
    build_path = os.path.join(ROOT, "build")
    if os.path.exists(build_path):
        shutil.rmtree(build_path, ignore_errors=True)
        print(f"     已删除 build/")
    spec = os.path.join(ROOT, "MinecraftAgent.spec")
    if os.path.exists(spec):
        os.remove(spec)
    done()

    # ---- PyInstaller 打包 ----
    step("PyInstaller 打包 (onedir 模式)")

    opts = [
        "--onedir",
        f"--name={DIST_NAME}",
        "--icon=app.ico",
        "--noconfirm",
        f"--distpath={os.path.join(ROOT, 'dist')}",
        "--hidden-import=langchain_community.chat_models.tongyi",
        "--hidden-import=langchain_chroma",
        "--hidden-import=langchain_huggingface",
        "--hidden-import=sentence_transformers",
        "--hidden-import=chromadb",
        "--hidden-import=chromadb.utils.embedding_functions",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=fastapi",
        "--hidden-import=transformers",
        "--hidden-import=torch",
        "--hidden-import=onnxruntime",
        "--hidden-import=sklearn",
        "--exclude-module=torch.cuda",
        "--exclude-module=torch.cuda.amp",
        "--exclude-module=torch.cuda.graphs",
        "--exclude-module=torch.cuda.nvtx",
        "--exclude-module=torch.cuda.profiler",
        "--exclude-module=torch.cuda.streams",
        "--exclude-module=torch.distributed",
        "--exclude-module=torch.distributions",
        "--exclude-module=triton",
        "--exclude-module=triton.language",
        "--exclude-module=triton.runtime",
        "--collect-all=sentence_transformers",
        "desktop_ui.py",
    ]

    result = subprocess.run(PYINSTALLER + opts, cwd=ROOT)
    if result.returncode != 0:
        print("\n  ERR PyInstaller 打包失败")
        sys.exit(1)
    done("PyInstaller 打包完成")

    # ---- 复制额外文件 ----
    step("复制运行时文件到 dist/MinecraftAgent/")

    copy_files = [
        "node.exe",
        "bot_server.js",
        "smart_pathfinding.js",
        "chat_service.py",
        "agent_graph.py",
        "vector_store.py",
        "config.py",
        "package.json",
        ".env.example",
        "desktop_ui.py",
        "launcher.py",
        "requirements.txt",
        "使用指南.md",
    ]

    for f in copy_files:
        src = os.path.join(ROOT, f)
        dst = os.path.join(DIST, f)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"     {f}")

    # 复制 node_modules（大量文件，使用 copytree）
    nm_src = os.path.join(ROOT, "node_modules")
    nm_dst = os.path.join(DIST, "node_modules")
    if os.path.exists(nm_src):
        if os.path.exists(nm_dst):
            shutil.rmtree(nm_dst, ignore_errors=True)
        step("复制 node_modules/ (约 546MB，稍等...)")
        shutil.copytree(nm_src, nm_dst)
        done("node_modules/ 已复制")

        # 瘦身：只保留 minecraft-data 1.20.1 / 1.21.1 版本
        step("裁剪 minecraft-data (只保留 1.20.1 / 1.21.1)")
        md_dir = os.path.join(nm_dst, "minecraft-data", "minecraft-data", "data")
        if os.path.exists(md_dir):
            # 删除 bedrock（Java 版不需要）
            bedrock_dir = os.path.join(md_dir, "bedrock")
            if os.path.exists(bedrock_dir):
                shutil.rmtree(bedrock_dir)
            # pc 目录只保留 1.21.1
            pc_dir = os.path.join(md_dir, "pc")
            if os.path.exists(pc_dir):
                for ver in os.listdir(pc_dir):
                    if ver not in ("1.20.1", "1.21.1"):
                        ver_path = os.path.join(pc_dir, ver)
                        if os.path.isdir(ver_path):
                            shutil.rmtree(ver_path)
            done("minecraft-data 已裁剪 (373MB → ~3MB)")

    # ---- 生成启动脚本 ----
    step("生成启动脚本")
    bat_path = os.path.join(DIST, "启动.bat")
    with open(bat_path, "w", encoding="gbk") as f:
        f.write("@echo off\n")
        f.write("title Minecraft Agent\n")
        f.write("echo 正在启动 Minecraft Agent...\n")
        f.write(f"start \"\" \"%~dp0{DIST_NAME}.exe\"\n")
    done(f"启动.bat 已生成")

    # ---- 清理旧构建（保留最新 2 个） ----
    dist_root = os.path.join(ROOT, "dist")
    builds = sorted(
        [d for d in os.listdir(dist_root) if d.startswith("MinecraftAgent_")],
        reverse=True
    )
    for old in builds[2:]:  # 删掉第3个及更早的
        old_path = os.path.join(dist_root, old)
        print(f"  清理旧构建: {old}")
        shutil.rmtree(old_path, ignore_errors=True)

    # ---- 汇总 ----
    print()
    print("=" * 60)
    print("  构建完成!")
    print(f"  输出目录: {DIST}")
    print("=" * 60)
    print()

    # 计算大小
    total = 0
    for dirpath, _, filenames in os.walk(DIST):
        for f in filenames:
            total += os.path.getsize(os.path.join(dirpath, f))
    print(f"  文件夹大小: {total / (1024**3):.1f} GB")
    print()
    print("  发布包内容:")
    print(f"    - {DIST_NAME}.exe     (主程序)")
    print(f"    - 启动.bat             (一键启动)")
    print(f"    - 使用指南.md           (用户使用说明)")
    print(f"    - .env.example         (配置文件模板)")
    print()
    print("  用户使用方法:")
    print(f"    1. 将 {DIST} 文件夹打包发给用户")
    print(f"    2. 用户参考 使用指南.md 操作即可")
    print()


if __name__ == "__main__":
    main()
