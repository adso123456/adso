"""
Minecraft Agent 无界面启动器
Phase 1: 无 API Key 时启动轻量配置服务器引导用户填写
Phase 2: 启动 bot_server.js + chat_service，进程守护，自动打开网页仪表盘
用法: python launcher.py
      python launcher.py --run-chat-service  (PyInstaller 子进程入口)
"""
import json
import shutil
import sys
import os
import time
import signal
import webbrowser
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv, set_key
from config import cfg

load_dotenv()

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))

CHAT_URL = f"http://{cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT}"
PANEL_URL = f"http://localhost:{cfg.CHAT_SERVICE_PORT}/panel"


# ============================================================
# Phase 1: 首次配置引导（轻量 HTTP Server）
# 注意：不用 chat_service 加路由，因为 chat_service 启动时需要
#       模块级初始化 ChatOpenAI，无 key 会直接报错。
#       这里用 Python 内置 http.server，零额外依赖。
# ============================================================

SETUP_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Minecraft Agent - 首次配置</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:"Microsoft YaHei","PingFang SC",sans-serif; background:#0d1117; color:#c9d1d9;
       display:flex; justify-content:center; align-items:center; min-height:100vh; }
.card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:32px;
        width:440px; max-width:95vw; }
.card h1 { font-size:20px; color:#58a6ff; margin-bottom:4px; }
.card .sub { font-size:12px; color:#8b949e; margin-bottom:24px; }
.field { margin-bottom:16px; }
.field label { display:block; font-size:13px; color:#c9d1d9; margin-bottom:6px; }
.field .input-row { display:flex; gap:8px; }
.field input { flex:1; background:#0d1117; border:1px solid #30363d; border-radius:6px;
               padding:10px 14px; color:#c9d1d9; font-size:14px; font-family:"Consolas",monospace;
               outline:none; }
.field input:focus { border-color:#58a6ff; }
.field .toggle-btn { background:#21262d; border:1px solid #30363d; color:#8b949e;
                     border-radius:6px; padding:10px 12px; cursor:pointer; font-size:13px; }
.field .toggle-btn:hover { color:#c9d1d9; }
.port-row { display:flex; align-items:center; gap:8px; }
.port-row input { width:100px; }
.port-row .hint { font-size:12px; color:#484f58; }
.actions { display:flex; gap:8px; margin-top:20px; }
.btn { padding:10px 20px; border-radius:6px; font-size:14px; cursor:pointer; border:none; font-weight:bold; }
.btn-test { background:#21262d; color:#c9d1d9; border:1px solid #30363d; }
.btn-test:hover { background:#30363d; }
.btn-test:disabled { opacity:0.5; cursor:not-allowed; }
.btn-save { background:#238636; color:white; flex:1; }
.btn-save:hover { background:#2ea043; }
.btn-save:disabled { background:#30363d; color:#484f58; cursor:not-allowed; }
.result { margin-top:16px; padding:10px 14px; border-radius:6px; font-size:13px; min-height:20px; }
.result.ok { background:#0d1b11; color:#3fb950; border:1px solid #1b3824; }
.result.err { background:#1f1115; color:#f85149; border:1px solid #3d1f24; }
.result.info { background:#0d1117; color:#8b949e; border:1px solid #21262d; }
.spinner { display:inline-block; width:14px; height:14px; border:2px solid #30363d;
           border-top-color:#58a6ff; border-radius:50%; animation:spin 0.8s linear infinite;
           vertical-align:middle; margin-right:8px; }
@keyframes spin { to { transform:rotate(360deg); } }
.footer { margin-top:24px; font-size:11px; color:#484f58; line-height:1.6; }
.footer a { color:#58a6ff; }
</style>
</head>
<body>
<div class="card">
  <h1>Minecraft Agent</h1>
  <div class="sub">首次使用需要配置 DeepSeek API Key</div>

  <div class="field">
    <label>DeepSeek API Key</label>
    <div class="input-row">
      <input type="password" id="apiKey" placeholder="sk-xxxxxxxxxxxxxxxx" autocomplete="off">
      <button class="toggle-btn" id="toggleBtn" onclick="toggleKey()">显示</button>
    </div>
  </div>

  <div class="field">
    <label>MC 服务器端口（可选，默认 25565）</label>
    <div class="port-row">
      <input type="number" id="mcPort" placeholder="25565" value="25565">
      <span class="hint">局域网联机端口</span>
    </div>
  </div>

  <div class="actions">
    <button class="btn btn-test" id="testBtn" onclick="testKey()">测试连接</button>
    <button class="btn btn-save" id="saveBtn" onclick="saveAndStart()">保存并启动</button>
  </div>

  <div class="result" id="result"></div>

  <div class="footer">
    API Key 可从 <a href="https://platform.deepseek.com/" target="_blank">platform.deepseek.com</a> 获取<br>
    配置将保存到项目根目录的 .env 文件
  </div>
</div>

<script>
var apiInput = document.getElementById('apiKey');
var portInput = document.getElementById('mcPort');
var testBtn = document.getElementById('testBtn');
var saveBtn = document.getElementById('saveBtn');
var resultDiv = document.getElementById('result');
var toggleBtn = document.getElementById('toggleBtn');

// Enter key to submit
apiInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') testKey();
});

function toggleKey() {
    if (apiInput.type === 'password') {
        apiInput.type = 'text';
        toggleBtn.textContent = '隐藏';
    } else {
        apiInput.type = 'password';
        toggleBtn.textContent = '显示';
    }
}

function showResult(msg, cls) {
    resultDiv.textContent = msg;
    resultDiv.className = 'result ' + cls;
}

function setLoading(btn, loading) {
    btn.disabled = loading;
    if (loading) {
        btn.dataset.orig = btn.textContent;
        btn.innerHTML = '<span class="spinner"></span>' + btn.textContent;
    } else {
        btn.textContent = btn.dataset.orig || btn.textContent;
    }
}

function testKey() {
    var key = apiInput.value.trim();
    if (!key) { showResult('请先输入 API Key', 'err'); return; }

    setLoading(testBtn, true);
    showResult('正在测试连接...', 'info');

    fetch('/api/test-key', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        setLoading(testBtn, false);
        showResult(data.message, data.status === 'ok' ? 'ok' : 'err');
    })
    .catch(function(e) {
        setLoading(testBtn, false);
        showResult('请求失败: ' + e.message, 'err');
    });
}

function saveAndStart() {
    var key = apiInput.value.trim();
    if (!key) { showResult('请先输入 API Key', 'err'); return; }

    setLoading(saveBtn, true);
    testBtn.disabled = true;

    fetch('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: key, port: portInput.value.trim() || '25565'})
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            showResult('配置已保存，正在启动服务...', 'info');
            // 等待 Phase 2 启动完成后跳转
            waitForPanel();
        } else {
            setLoading(saveBtn, false);
            testBtn.disabled = false;
            showResult(data.message || '保存失败', 'err');
        }
    })
    .catch(function(e) {
        setLoading(saveBtn, false);
        testBtn.disabled = false;
        showResult('请求失败: ' + e.message, 'err');
    });
}

function waitForPanel() {
    var attempts = 0;
    var maxAttempts = 120; // 最多等 4 分钟

    function poll() {
        attempts++;
        fetch('/panel')
            .then(function(r) {
                if (r.ok) {
                    showResult('服务已启动，正在跳转...', 'ok');
                    setTimeout(function() { window.location.href = '/panel'; }, 500);
                } else {
                    scheduleNext();
                }
            })
            .catch(function() {
                scheduleNext();
            });
    }

    function scheduleNext() {
        if (attempts >= maxAttempts) {
            showResult('服务启动超时，请检查终端日志后手动刷新页面', 'err');
            saveBtn.disabled = false;
            testBtn.disabled = false;
            return;
        }
        if (attempts === 1) {
            showResult('配置已保存，正在启动服务...'
                + '\n\n首次启动需加载 AI 模型和知识库，可能需数分钟，请耐心等待...', 'info');
        }
        if (attempts % 10 === 0) {
            showResult('正在等待服务就绪 (' + (attempts * 2) + 's)...'
                + '\n首次启动需加载模型/知识库，可能需数分钟', 'info');
        }
        setTimeout(poll, 2000);
    }

    setTimeout(poll, 2000);  // 给 setup server 关闭 + chat 启动留时间
}
</script>
</body>
</html>"""


class SetupHandler(BaseHTTPRequestHandler):
    """轻量配置服务器 — 仅服务 /setup 页面和两个 API 端点"""

    def do_GET(self):
        if self.path in ("/", "/setup"):
            self._serve_html()
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/test-key":
            self._handle_test_key()
        elif self.path == "/api/config":
            self._handle_config()
        else:
            self._send_json(404, {"error": "not found"})

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(SETUP_HTML.encode("utf-8"))

    def _send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_test_key(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"status": "error", "message": "请求格式错误"})
            return

        key = body.get("key", "").strip()
        if not key:
            self._send_json(400, {"status": "error", "message": "API Key 不能为空"})
            return

        try:
            resp = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 5,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                self._send_json(200, {"status": "ok", "message": "DeepSeek API Key 有效"})
            elif resp.status_code == 401:
                self._send_json(200, {"status": "error", "message": "API Key 无效 (401)"})
            else:
                self._send_json(200, {"status": "error",
                                "message": f"API 错误: {resp.status_code} {resp.text[:100]}"})
        except Exception as e:
            self._send_json(200, {"status": "error", "message": f"连接失败: {e}"})

    def _handle_config(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"status": "error", "message": "请求格式错误"})
            return

        key = body.get("key", "").strip()
        port = body.get("port", "").strip()

        if not key:
            self._send_json(400, {"status": "error", "message": "API Key 不能为空"})
            return

        env_path = os.path.join(ROOT, ".env")
        example_path = os.path.join(ROOT, ".env.example")

        try:
            if not os.path.exists(env_path) and os.path.exists(example_path):
                shutil.copy(example_path, env_path)
            if not os.path.exists(env_path):
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write("")

            set_key(env_path, "DEEPSEEK_API_KEY", key)
            if port:
                set_key(env_path, "MC_SERVER_PORT", port)

            # 更新当前进程环境变量，确保后续代码读到新值
            os.environ["DEEPSEEK_API_KEY"] = key
            if port:
                os.environ["MC_SERVER_PORT"] = port

        except Exception as e:
            self._send_json(500, {"status": "error", "message": f"写入配置失败: {e}"})
            return

        self._send_json(200, {"status": "ok", "message": "配置已保存，正在启动服务..."})

        # 从另一个线程关闭服务器，释放端口 8000 供 Phase 2 使用
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, format, *args):
        """抑制 HTTP 请求日志，保持终端输出整洁"""
        pass


def _check_api_key():
    """检查 .env 中是否有有效的 DEEPSEEK_API_KEY"""
    key = os.getenv("DEEPSEEK_API_KEY", "")
    return bool(key and key != "your_api_key_here")


def _run_setup_server(host, port):
    """Phase 1: 启动轻量配置服务器，引导用户填写 API Key"""
    HTTPServer.allow_reuse_address = True
    server = HTTPServer((host, port), SetupHandler)

    print(f"[配置] 未检测到有效的 API Key，启动配置引导...")
    print(f"[配置] 配置页面 -> http://localhost:{port}/setup")
    print()

    webbrowser.open(f"http://localhost:{port}/setup")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[配置] 用户取消配置")
        return False
    finally:
        # 确保端口完全释放: shutdown 通知 serve_forever 退出,
        # server_close 关闭 socket 释放端口
        server.server_close()
        time.sleep(0.5)  # 给 OS 时间释放端口

    # 重新加载 .env，让当前进程读到刚写入的配置
    load_dotenv(override=True)
    print("[配置] API Key 配置完成\n")
    return True


# ============================================================
# Phase 2: 正常启动（bot + chat 全服务）
# ============================================================

def _wait_for_bot(svc, timeout=15):
    """轮询等待 Bot 服务端口就绪"""
    for _ in range(timeout):
        if svc.bot_proc and svc.bot_proc.poll() is not None:
            print(f"  [错误] Bot 进程异常退出，退出码: {svc.bot_proc.returncode}")
            return False
        try:
            r = requests.get(f"{cfg.BOT_URL}/status", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _wait_for_chat(timeout=60):
    """轮询等待 Chat 服务就绪（首次可能下载/加载模型，给较长超时）"""
    for i in range(timeout):
        try:
            r = requests.get(f"{CHAT_URL}/health", timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if i == 0:
            print("  首次启动需加载 AI 模型和知识库，可能需数分钟，请耐心等待...")
        time.sleep(1)
    return False


def _try_connect_bot():
    """发送连接请求让 Bot 连入 Minecraft"""
    mc_port = int(os.getenv("MC_SERVER_PORT", "25565"))
    try:
        r = requests.post(f"{cfg.BOT_URL}/connect",
                          json={"port": mc_port}, timeout=10)
        if r.status_code == 200:
            print(f"[连接] 已发送连接请求 -> localhost:{mc_port}")
        else:
            print(f"[连接] 连接请求失败: {r.status_code}")
    except Exception as e:
        print(f"[连接] Bot 未就绪，请稍后手动连接: {e}")


def _register_signals(stop_event):
    """注册退出信号处理（兼容 Windows / Linux / macOS）"""
    def handler(sig, frame):
        print("\n[系统] 收到退出信号，正在关闭所有服务...")
        stop_event.set()

    signal.signal(signal.SIGINT, handler)
    # SIGTERM 在 Windows 上不可用
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, handler)
        except ValueError:
            pass


def main():
    from service_manager import ServiceManager

    print()
    print("=" * 50)
    print("  Minecraft Agent 启动器")
    print("=" * 50)
    print()

    # ---- Phase 1: 检查 API Key，无 key 时启动配置引导 ----
    host = cfg.CHAT_SERVICE_HOST
    port = cfg.CHAT_SERVICE_PORT

    if not _check_api_key():
        if not _run_setup_server(host, port):
            print("[系统] 配置未完成，退出")
            return

    # ---- Phase 2: 正常启动全服务 ----
    svc = ServiceManager()

    print("[启动] 正在启动 Minecraft Bot 服务...")
    svc.start_bot()
    if _wait_for_bot(svc):
        print(f"[就绪] Bot 服务已就绪 ({cfg.BOT_URL})")
    else:
        print("[警告] Bot 服务启动超时，请检查 Node.js 和 bot_server.js")

    print("[启动] 正在启动 AI 聊天服务...")
    svc.start_chat()
    if _wait_for_chat():
        print(f"[就绪] AI 服务已就绪 ({CHAT_URL})")
    else:
        print("[警告] AI 服务启动超时，请检查 API Key 和网络连接")

    # 进程守护（异常退出自动重启）
    svc.toggle_watchdog(True)
    print("[守护] 进程守护已开启")

    # 自动连接 Minecraft
    _try_connect_bot()

    # 打开网页仪表盘
    print(f"[面板] 正在打开浏览器 -> {PANEL_URL}")
    print()
    webbrowser.open(PANEL_URL)

    print("所有服务已启动，按 Ctrl+C 退出")
    print()

    # 阻塞等待退出信号
    # Windows 上 stop_event.wait() 无超时会阻止信号处理介入,
    # 改为轮询循环, 每 0.5s 醒一次让 SIGINT 能被及时捕获
    stop_event = threading.Event()
    _register_signals(stop_event)

    try:
        while not stop_event.is_set():
            stop_event.wait(0.5)
    except KeyboardInterrupt:
        print("\n[系统] 收到中断信号，正在关闭所有服务...")
    finally:
        svc.shutdown()
        print("[系统] 已退出")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--run-chat-service":
        import uvicorn
        from chat_service import app
        print(f"Minecraft AI 聊天服务 (监听 {cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT})")
        uvicorn.run(app, host=cfg.CHAT_SERVICE_HOST, port=cfg.CHAT_SERVICE_PORT)
    else:
        main()
