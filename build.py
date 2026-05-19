"""
Minecraft Agent 打包构建脚本

用法: python build.py
输出: dist/MinecraftAgent/  (可直接运行的文件夹)
"""
import subprocess
import sys
import os
import shutil
import zipfile


ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist", "MinecraftAgent")
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
    for d in ["build", "dist"]:
        path = os.path.join(ROOT, d)
        if os.path.exists(path):
            shutil.rmtree(path)
            print(f"     已删除 {d}/")
    # 删除 PyInstaller 生成的 spec
    spec = os.path.join(ROOT, "MinecraftAgent.spec")
    if os.path.exists(spec):
        os.remove(spec)
    done()

    # ---- PyInstaller 打包 ----
    step("PyInstaller 打包 (onedir 模式)")

    opts = [
        "--onedir",
        "--name=MinecraftAgent",
        "--noconfirm",
        "--clean",
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
        "--collect-all=gradio",
        "--collect-all=sentence_transformers",
        "web_ui.py",
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
        "advanced_synthesis_system.py",
        "config.py",
        "import_wiki_data.py",
        "extract_wiki.js",
        "package.json",
        ".env.example",
        "launcher.py",
        "requirements.txt",
        "README.md",
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
            shutil.rmtree(nm_dst)
        step("复制 node_modules/ (约 546MB，稍等...)")
        shutil.copytree(nm_src, nm_dst)
        done("node_modules/ 已复制")

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
    print("  使用方法:")
    print(f"    1. 进入 {DIST}")
    print(f"    2. 双击 MinecraftAgent.exe")
    print(f"    3. 首次运行复制 .env.example 为 .env 并填写 API Key")
    print()


if __name__ == "__main__":
    main()
