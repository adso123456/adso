"""
Minecraft 游戏内聊天服务
句首数字1 = 指令，否则 = 闲聊
聊天记忆持久化到文件
"""

import os
import json
import uuid
import threading
import random
import requests
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# 必须在任何 ML 库 import 之前加载 .env 并设置 HF_ENDPOINT，否则
# langchain_openai 导入时触发 huggingface_hub 加载，镜像配置会来不及生效
load_dotenv()
if os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT")

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agent_graph import graph

from config import cfg

app = FastAPI(title="Minecraft Chat Service")


# ========== 模型 ==========
# 闲聊使用轻量模型，指令执行使用 agent_graph 中的模型
chat_model = ChatOpenAI(model=cfg.LLM_CHAT_MODEL, base_url=cfg.DEEPSEEK_BASE_URL, api_key=cfg.DEEPSEEK_API_KEY)


# ========== 持久化聊天记忆 ==========

class PersistentMemory:
    def __init__(self, filepath=None, max_history=None):
        self.filepath = filepath or cfg.MEMORY_FILE
        self.max_history = max_history or cfg.MAX_MEMORY_HISTORY
        self.history = []
        self.load()

    def load(self):
        """启动时从文件加载历史记录"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    self.history = json.load(f)
                print(f"✓ 已加载 {len(self.history)} 条聊天记忆")
            except Exception as e:
                print(f"⚠ 加载记忆失败: {e}，将使用空记忆")
                self.history = []
        else:
            self.history = []
            print("✓ 首次启动，创建新的聊天记忆")

    def save(self):
        """保存到文件"""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠ 保存记忆失败: {e}")

    def add(self, username: str, message: str, reply: str, msg_type: str = "chat"):
        """添加一条记录并自动保存"""
        self.history.append({
            "username": username,
            "message": message,
            "reply": reply,
            "type": msg_type,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        # 超过上限就删旧的
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
        self.save()

    def get_recent_chats(self, n=10):
        """获取最近的闲聊记录（不含指令）"""
        chats = [h for h in self.history if h["type"] == "chat"]
        return chats[-n:]

    def get_recent_all(self, n=10):
        """获取最近所有记录"""
        return self.history[-n:]

    def format_for_prompt(self, n=8):
        """格式化为 prompt 用的历史文本"""
        recent = self.get_recent_chats(n)
        if not recent:
            return ""
        lines = []
        for h in recent:
            lines.append(f"[{h['time']}] {h['username']}: {h['message']}")
            lines.append(f"[{h['time']}] AIBot: {h['reply']}")
        return "\n".join(lines)

    def get_user_summary(self, username: str) -> str:
        """获取某个玩家的历史摘要"""
        user_records = [h for h in self.history if h["username"] == username]
        if not user_records:
            return f"这是你第一次和 {username} 聊天"

        chat_count = len([h for h in user_records if h["type"] == "chat"])
        cmd_count = len([h for h in user_records if h["type"] == "command"])
        last_time = user_records[-1]["time"]
        last_msg = user_records[-1]["message"]

        return f"你和 {username} 聊过 {chat_count} 次天，执行过 {cmd_count} 次指令。上次互动: {last_time}，说的是: {last_msg}"


memory = PersistentMemory()
active_tasks = {}
_vs_instance = None


def _get_vs():
    """延迟加载向量库单例，避免重复加载 embedding 模型"""
    global _vs_instance
    if _vs_instance is None and cfg.ENABLE_VECTOR_STORE:
        try:
            from vector_store import MinecraftVectorStore
            _vs_instance = MinecraftVectorStore()
        except Exception as e:
            print(f"⚠ 向量库加载失败: {e}")
            _vs_instance = False
    return _vs_instance if _vs_instance is not False else None


# ========== 请求模型 ==========

class GameChatRequest(BaseModel):
    username: str
    message: str
    bot_name: str = "AIBot"


# ========== 闲聊回复 ==========

def generate_chat_reply(username: str, message: str, bot_name: str) -> str:
    """用轻量模型生成闲聊回复"""

    history_text = memory.format_for_prompt(8)
    user_summary = memory.get_user_summary(username)

    system_prompt = f"""你是 Minecraft 里的 AI 玩家 {bot_name}，性格活泼友好。

关于你和这个玩家：
{user_summary}

聊天规则：
- 用简短自然的中文回复，像真实玩家一样
- 回复控制在30字以内
- 可以用游戏相关的梗和用语
- 记住之前聊过的内容，保持话题连贯
- 如果对方提到之前的事，要能接上
- 不要用表情符号
- 不要说"作为AI"之类的话

{f'最近聊天记录：{chr(10)}{history_text}' if history_text else ''}"""

    try:
        result = chat_model.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{username} 说: {message}")
        ])
        reply = result.content.strip()

        if len(reply) > 60:
            reply = reply[:57] + "..."

        return reply
    except Exception as e:
        print(f"聊天回复生成失败: {e}")
        return "啊？刚才走神了，你说啥"


# ========== 执行指令（后台） ==========

def execute_command_async(username: str, message: str, task_id: str):
    try:
        config = {
            "configurable": {"thread_id": f"game-cmd-{task_id}"},
            "recursion_limit": 50
        }

        result = graph.invoke(
            {"messages": [HumanMessage(content=f"玩家 {username} 要求你: {message}")]},
            config
        )

        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage) and m.content]
        if ai_messages:
            reply = ai_messages[-1].content.strip()
            if len(reply) > 100:
                reply = reply[:97] + "..."
            try:
                requests.post(f"{cfg.BOT_URL}/chat", json={"message": f"@{username} {reply}"}, timeout=8)
            except Exception as e:
                print(f"⚠ 发送回复到 Bot 失败: {e}，reply={reply[:40]}")

            memory.add(username, message, reply, "command")

            # ===== 保存到向量知识库 =====
            # 检查是否启用向量知识库
            if cfg.ENABLE_VECTOR_STORE:
                try:
                    vs = _get_vs()
                    if vs:
                        # 保存技能
                        vs.save_skill(task=message, result=reply)

                        # 如果涉及位置，保存位置记忆
                        try:
                            status = requests.get(f"{cfg.BOT_URL}/status", timeout=8).json()
                            pos = status.get("position", {})
                            if pos:
                                vs.save_memory(
                                    f"执行任务-{message[:20]}",
                                    {
                                        "task": message,
                                        "result": reply,
                                        "position": {"x": round(pos.get("x", 0)), "y": round(pos.get("y", 0)),
                                                     "z": round(pos.get("z", 0))},
                                        "player": username
                                    }
                                )
                        except Exception as e:
                            print(f"⚠ 保存位置记忆失败(status): {e}")
                except Exception as e:
                    print(f"⚠ 保存到向量库失败: {e}")

        active_tasks[task_id] = "done"

    except Exception as e:
        print(f"指令执行失败: {e}")
        active_tasks[task_id] = f"error: {e}"
        try:
            requests.post(f"{cfg.BOT_URL}/chat", json={
                "message": f"@{username} 任务失败了，再试一次吧"
            }, timeout=8)
        except Exception as e:
            print(f"⚠ 发送错误通知到 Bot 失败: {e}")
        memory.add(username, message, "执行失败", "command")


class BotEventRequest(BaseModel):
    event: str
    details: dict


@app.post("/bot_event")
async def handle_bot_event(request: BotEventRequest):
    """接收 Bot 上报的游戏事件，保存到向量库"""
    if cfg.ENABLE_VECTOR_STORE:
        try:
            vs = _get_vs()
            if vs:
                vs.save_memory(
                    f"游戏事件-{request.event}",
                    request.details
                )
                print(f"[事件] {request.event}: {json.dumps(request.details, ensure_ascii=False)[:80]}")
        except Exception as e:
            print(f"⚠ 保存事件到向量库失败: {e}")

    return {"status": "recorded"}


# ========== API 路由 ==========

@app.post("/game_chat")
async def handle_game_chat(request: GameChatRequest):
    """处理游戏内聊天"""

    username = request.username
    message = request.message.strip()
    bot_name = request.bot_name

    # 忽略空消息、自己的消息、游戏命令
    if not message or username == bot_name or message.startswith("/"):
        return {"reply": "", "is_command": False}

    print(f"\n[收到] {username}: {message}")

    # ===== 判定规则：句首是"1"就是指令 =====
    if message.startswith("1"):
        # 去掉开头的"1"和可能的空格
        command_text = message[1:].strip()

        if not command_text:
            return {"reply": "指令不能为空哦，1后面写你要我做的事", "is_command": False}

        print(f"[指令] {command_text}")

        task_id = uuid.uuid4().hex[:8]
        active_tasks[task_id] = "running"

        quick_replies = [
            "收到，马上去做",
            "好的，这就开始",
            "没问题，等我一下",
            "了解，正在执行",
            "收到指令，开搞",
        ]
        quick_reply = random.choice(quick_replies)

        thread = threading.Thread(
            target=execute_command_async,
            args=(username, command_text, task_id),
            daemon=True
        )
        thread.start()

        memory.add(username, f"[指令] {command_text}", quick_reply, "command")

        return {
            "reply": quick_reply,
            "is_command": True,
            "task_id": task_id
        }

    else:
        # ===== 闲聊模式 =====
        print(f"[闲聊] {message}")

        reply = generate_chat_reply(username, message, bot_name)
        memory.add(username, message, reply, "chat")

        return {
            "reply": reply,
            "is_command": False,
            "task_id": None
        }


@app.get("/task_status/{task_id}")
async def get_task_status(task_id: str):
    status = active_tasks.get(task_id, "not_found")
    return {"task_id": task_id, "status": status}


@app.get("/memory")
def view_memory(limit: int = 20):
    """查看聊天记忆"""
    return {
        "total": len(memory.history),
        "recent": memory.get_recent_all(limit)
    }


@app.delete("/memory")
def clear_memory():
    """清空聊天记忆"""
    memory.history = []
    memory.save()
    return {"status": "cleared"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "memory_count": len(memory.history),
        "active_tasks": len([t for t in active_tasks.values() if t == "running"])
    }


@app.get("/dashboard")
def dashboard():
    """聚合仪表盘：bot 状态 + 背包 + 聊天记录"""
    data = {
        "bot": {"connected": False},
        "equipment": None,
        "recent_chats": [],
        "memory_count": len(memory.history),
        "active_tasks": len([t for t in active_tasks.values() if t == "running"])
    }

    try:
        bot_status = requests.get(f"{cfg.BOT_URL}/status", timeout=8).json()
        data["bot"] = bot_status
    except Exception as e:
        data["bot"]["error"] = str(e)

    if data["bot"].get("connected"):
        try:
            equip = requests.get(f"{cfg.BOT_URL}/equipment", timeout=8).json()
            data["equipment"] = equip
        except Exception as e:
            print(f"⚠ 查询 equipment 失败: {e}")

    data["recent_chats"] = memory.get_recent_all(10)

    return data


@app.get("/panel", response_class=HTMLResponse)
async def dashboard_panel():
    """网页仪表盘：单文件 HTML，JS 轮询 /dashboard + 调 /game_chat 发指令"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Minecraft Agent Dashboard</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:"Microsoft YaHei","PingFang SC",sans-serif; background:#0d1117; color:#c9d1d9; min-height:100vh; }
.header { background:#161b22; border-bottom:1px solid #30363d; padding:12px 24px; display:flex; align-items:center; gap:12px; }
.header h1 { font-size:18px; color:#58a6ff; }
.status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
.status-dot.online { background:#3fb950; box-shadow:0 0 6px #3fb950; }
.status-dot.offline { background:#f85149; }
.main { display:flex; height:calc(100vh - 52px); }
.left { width:420px; min-width:420px; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px; border-right:1px solid #30363d; }
.card { background:#161b22; border:1px solid #30363d; border-radius:6px; padding:12px 16px; }
.card h3 { font-size:13px; color:#8b949e; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:10px; }
.stats-row { display:flex; gap:8px; }
.stat { flex:1; text-align:center; background:#0d1117; border-radius:4px; padding:8px; }
.stat .value { font-size:22px; font-weight:bold; color:#58a6ff; }
.stat .label { font-size:11px; color:#8b949e; margin-top:2px; }
.bar-row { margin-bottom:8px; }
.bar-row .bar-label { font-size:12px; color:#8b949e; margin-bottom:3px; }
.bar-row .bar-label span { float:right; color:#c9d1d9; }
.bar-track { height:8px; background:#21262d; border-radius:4px; overflow:hidden; }
.bar-fill { height:100%; border-radius:4px; transition:width 0.5s; }
.bar-fill.health { background:#3fb950; }
.bar-fill.health.low { background:#f85149; }
.bar-fill.food { background:#d29922; }
.pos-grid { display:flex; gap:12px; }
.pos-item { flex:1; text-align:center; background:#0d1117; border-radius:4px; padding:6px; }
.pos-item .coord { font-family:"Consolas",monospace; font-size:15px; color:#58a6ff; }
.pos-item .axis { font-size:11px; color:#8b949e; }
.kv-table { width:100%; font-size:12px; }
.kv-table td { padding:3px 0; }
.kv-table td:first-child { color:#8b949e; width:70px; }
.kv-table td:last-child { color:#c9d1d9; word-break:break-all; }
.item-list { font-size:12px; color:#c9d1d9; max-height:120px; overflow-y:auto; }
.item-list .item { padding:2px 0; border-bottom:1px solid #21262d; }
.empty { color:#484f58; font-style:italic; font-size:12px; }
.right { flex:1; display:flex; flex-direction:column; min-width:0; }
.chat-area { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:4px; }
.chat-msg { font-size:13px; padding:6px 10px; border-radius:4px; line-height:1.5; }
.chat-msg.user { background:#1a2332; }
.chat-msg.bot { background:#161b22; }
.chat-msg.cmd { border-left:2px solid #d29922; }
.chat-msg .meta { font-size:11px; color:#8b949e; margin-bottom:2px; }
.chat-msg .meta .tag { font-size:10px; padding:1px 5px; border-radius:3px; margin-left:6px; }
.chat-msg .meta .tag.command { background:#d29922; color:#0d1117; }
.chat-msg .meta .tag.chat { background:#30363d; color:#8b949e; }
.chat-error { color:#f85149; font-size:12px; padding:6px 10px; background:#1f1115; border-radius:4px; border-left:2px solid #f85149; }
.chat-input-area { padding:12px 16px; border-top:1px solid #30363d; background:#161b22; }
.chat-input-row { display:flex; gap:8px; }
.chat-input-row input { flex:1; background:#0d1117; border:1px solid #30363d; border-radius:6px; padding:10px 14px; color:#c9d1d9; font-size:14px; outline:none; }
.chat-input-row input:focus { border-color:#58a6ff; }
.chat-input-row button { background:#238636; color:white; border:none; border-radius:6px; padding:10px 20px; font-size:14px; cursor:pointer; font-weight:bold; }
.chat-input-row button:hover { background:#2ea043; }
.chat-input-row button:disabled { background:#30363d; color:#484f58; cursor:not-allowed; }
.hint { font-size:11px; color:#484f58; margin-top:6px; }
::-webkit-scrollbar { width:6px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:#30363d; border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:#484f58; }
</style>
</head>
<body>

<div class="header">
  <span class="status-dot offline" id="statusDot"></span>
  <h1>Minecraft Agent</h1>
  <span style="font-size:12px;color:#8b949e;margin-left:auto;" id="lastUpdate">--</span>
</div>

<div class="main">
  <div class="left">

    <!-- data.memory_count, data.active_tasks -->
    <div class="stats-row">
      <div class="stat">
        <div class="value" id="statMemory">--</div>
        <div class="label">记忆条数</div>
      </div>
      <div class="stat">
        <div class="value" id="statTasks">--</div>
        <div class="label">活跃任务</div>
      </div>
    </div>

    <!-- data.bot.connected, data.bot.username -->
    <div class="card">
      <h3>玩家信息</h3>
      <table class="kv-table">
        <tr><td>状态</td><td id="infoStatus">--</td></tr>
        <tr><td>名称</td><td id="infoName">--</td></tr>
      </table>
    </div>

    <!-- data.bot.health (0-20), data.bot.food (0-20) -->
    <div class="card">
      <h3>生命值 / 饥饿度</h3>
      <div class="bar-row">
        <div class="bar-label">生命值 <span id="healthText">--/20</span></div>
        <div class="bar-track"><div class="bar-fill health" id="healthBar" style="width:0%"></div></div>
      </div>
      <div class="bar-row">
        <div class="bar-label">饥饿度 <span id="foodText">--/20</span></div>
        <div class="bar-track"><div class="bar-fill food" id="foodBar" style="width:0%"></div></div>
      </div>
    </div>

    <!-- data.bot.position.x, .y, .z -->
    <div class="card">
      <h3>位置</h3>
      <div class="pos-grid">
        <div class="pos-item"><div class="coord" id="posX">--</div><div class="axis">X</div></div>
        <div class="pos-item"><div class="coord" id="posY">--</div><div class="axis">Y</div></div>
        <div class="pos-item"><div class="coord" id="posZ">--</div><div class="axis">Z</div></div>
      </div>
    </div>

    <!-- data.equipment: {held_item, armor:{head,chest,legs,feet}, tools:{pickaxe,axe,...}, total_items} -->
    <div class="card">
      <h3>装备</h3>
      <div id="equipContent"><span class="empty">未连接</span></div>
    </div>

    <!-- data.bot.inventory: [{name, count}, ...] -->
    <div class="card">
      <h3>背包</h3>
      <div id="invContent"><span class="empty">未连接</span></div>
    </div>

  </div>

  <div class="right">
    <!-- data.recent_chats: [{username, message, reply, type, time}, ...] -->
    <div class="chat-area" id="chatArea">
      <div style="color:#484f58;text-align:center;padding:40px;">等待数据...</div>
    </div>

    <div class="chat-input-area">
      <div class="chat-input-row">
        <input type="text" id="cmdInput" placeholder="输入消息 (1开头=指令, 否则=闲聊)" autocomplete="off">
        <button id="sendBtn" onclick="sendCommand()">发送</button>
      </div>
      <div class="hint">以 1 开头 = AI 指令执行 | 不加 1 = 闲聊模式 | Enter 发送</div>
    </div>
  </div>
</div>

<script>
/*
 * ============ 字段映射 (来自 GET /dashboard 实际返回) ============
 * data.bot.connected            → bool    连接状态
 * data.bot.username             → string  玩家名
 * data.bot.health               → int     生命值 0-20
 * data.bot.food                 → int     饥饿度 0-20
 * data.bot.position.x / .y / .z → float   坐标
 * data.bot.inventory            → array   [{name, count}, ...]
 * data.equipment                → null | {
 *     held_item: string,
 *     armor: {head, chest, legs, feet},
 *     tools: {pickaxe: [{name, durability, count}], axe: [...], shovel, hoe, sword},
 *     total_items: int
 * }
 * data.recent_chats             → array   [{username, message, reply, type, time}, ...]
 *   type: "chat" | "command"
 *   time: "YYYY-MM-DD HH:MM:SS"
 * data.memory_count             → int
 * data.active_tasks             → int
 *
 * POST /game_chat
 *   body:     {username: "Dashboard", message: string, bot_name: "AIBot"}
 *   response: {reply: string, is_command: bool, task_id: string|null}
 * ================================================================
 */

var chatArea = document.getElementById('chatArea');
var cmdInput = document.getElementById('cmdInput');
var sendBtn = document.getElementById('sendBtn');
var lastChatCount = 0;
var firstLoad = true;

cmdInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') sendCommand();
});

// ========== 轮询 /dashboard，每 3 秒刷新 ==========
function refresh() {
    fetch('/dashboard')
        .then(function(resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then(function(data) { updateUI(data); })
        .catch(function(e) {
            console.error('轮询失败:', e);
            if (firstLoad) {
                chatArea.innerHTML = '<div class="chat-error">无法连接服务 (localhost:8000)，请确认 chat_service.py 已启动</div>';
            }
        });
    document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString('zh-CN');
}

function updateUI(data) {
    var bot = data.bot || {};
    var equip = data.equipment;
    var chats = data.recent_chats || [];

    // 连接状态指示灯 — data.bot.connected
    document.getElementById('statusDot').className = 'status-dot ' + (bot.connected ? 'online' : 'offline');

    // 统计数字 — data.memory_count, data.active_tasks
    document.getElementById('statMemory').textContent = data.memory_count != null ? data.memory_count : '--';
    document.getElementById('statTasks').textContent = data.active_tasks != null ? data.active_tasks : '--';

    // 玩家信息 — data.bot.connected, data.bot.username
    var statusEl = document.getElementById('infoStatus');
    statusEl.textContent = bot.connected ? '已连接' : '未连接';
    statusEl.style.color = bot.connected ? '#3fb950' : '#f85149';
    document.getElementById('infoName').textContent = bot.username || '--';

    // 血量/饥饿 — data.bot.health, data.bot.food
    var health = bot.health != null ? bot.health : 0;
    var food = bot.food != null ? bot.food : 0;
    document.getElementById('healthText').textContent = health + '/20';
    document.getElementById('foodText').textContent = food + '/20';
    document.getElementById('healthBar').style.width = Math.min(100, health / 20 * 100) + '%';
    document.getElementById('healthBar').className = 'bar-fill health' + (health < 6 ? ' low' : '');
    document.getElementById('foodBar').style.width = Math.min(100, food / 20 * 100) + '%';

    // 坐标 — data.bot.position.x, .y, .z
    if (bot.position) {
        document.getElementById('posX').textContent = Math.round(bot.position.x);
        document.getElementById('posY').textContent = Math.round(bot.position.y);
        document.getElementById('posZ').textContent = Math.round(bot.position.z);
    } else {
        document.getElementById('posX').textContent = '--';
        document.getElementById('posY').textContent = '--';
        document.getElementById('posZ').textContent = '--';
    }

    // 装备 — data.equipment
    var equipDiv = document.getElementById('equipContent');
    if (equip) {
        var armor = equip.armor || {};
        var tools = equip.tools || {};
        var html = '<table class="kv-table">';
        html += '<tr><td>手持</td><td>' + esc(equip.held_item || '空') + '</td></tr>';
        // data.equipment.armor.head, .chest, .legs, .feet
        html += '<tr><td>头盔</td><td>' + esc(armor.head || '无') + '</td></tr>';
        html += '<tr><td>胸甲</td><td>' + esc(armor.chest || '无') + '</td></tr>';
        html += '<tr><td>腿甲</td><td>' + esc(armor.legs || '无') + '</td></tr>';
        html += '<tr><td>靴子</td><td>' + esc(armor.feet || '无') + '</td></tr>';
        // data.equipment.tools.{pickaxe,axe,shovel,hoe,sword} — 各为 [{name,durability,count}]
        ['pickaxe','axe','shovel','hoe','sword'].forEach(function(t) {
            if (tools[t] && tools[t].length) {
                html += '<tr><td>' + t + '</td><td>' + esc(tools[t][0].name) + ' (' + (tools[t][0].durability || '?') + ')</td></tr>';
            }
        });
        // data.equipment.total_items
        html += '<tr><td>总物品</td><td>' + (equip.total_items != null ? equip.total_items : '--') + '</td></tr>';
        html += '</table>';
        equipDiv.innerHTML = html;
    } else {
        equipDiv.innerHTML = '<span class="empty">未连接</span>';
    }

    // 背包 — data.bot.inventory: [{name, count}]
    var invDiv = document.getElementById('invContent');
    var inv = bot.inventory;
    if (inv && inv.length) {
        var list = '<div class="item-list">';
        inv.forEach(function(item) {
            list += '<div class="item">' + esc(item.name) + ' x' + item.count + '</div>';
        });
        list += '</div>';
        invDiv.innerHTML = list;
    } else if (bot.connected) {
        invDiv.innerHTML = '<span class="empty">背包为空</span>';
    } else {
        invDiv.innerHTML = '<span class="empty">未连接</span>';
    }

    // 聊天记录 — data.recent_chats: [{username, message, reply, type, time}]
    if (chats.length !== lastChatCount || firstLoad) {
        lastChatCount = chats.length;
        if (!chats.length) {
            chatArea.innerHTML = '<div style="color:#484f58;text-align:center;padding:40px;">暂无聊天记录</div>';
        } else {
            var chatHtml = '';
            chats.forEach(function(c) {
                var typeTag = c.type === 'command'
                    ? '<span class="tag command">指令</span>'
                    : '<span class="tag chat">闲聊</span>';
                chatHtml += '<div class="chat-msg user' + (c.type === 'command' ? ' cmd' : '') + '">';
                chatHtml += '<div class="meta">' + esc(c.time) + ' ' + esc(c.username) + typeTag + '</div>';
                chatHtml += '<div>' + esc(c.message) + '</div></div>';
                if (c.reply) {
                    chatHtml += '<div class="chat-msg bot">';
                    chatHtml += '<div class="meta">' + esc(c.time) + ' AIBot</div>';
                    chatHtml += '<div>' + esc(c.reply) + '</div></div>';
                }
            });
            chatArea.innerHTML = chatHtml;
        }
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    firstLoad = false;
}

// HTML 转义
function esc(s) {
    if (!s) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ========== 发送指令 → POST /game_chat ==========
function sendCommand() {
    var msg = cmdInput.value.trim();
    if (!msg) return;

    cmdInput.value = '';
    sendBtn.disabled = true;
    sendBtn.textContent = '...';

    var now = new Date().toLocaleTimeString('zh-CN');

    // 即时显示用户消息
    var userDiv = document.createElement('div');
    userDiv.className = 'chat-msg user';
    userDiv.innerHTML = '<div class="meta">' + now + ' Dashboard</div><div>' + esc(msg) + '</div>';
    chatArea.appendChild(userDiv);
    chatArea.scrollTop = chatArea.scrollHeight;

    fetch('/game_chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: 'Dashboard', message: msg, bot_name: 'AIBot'})
    })
    .then(function(resp) {
        if (!resp.ok) throw new Error('服务返回 ' + resp.status);
        return resp.json();
    })
    .then(function(data) {
        var reply = data.reply || '(无回复)';
        var isCmd = data.is_command;
        var botDiv = document.createElement('div');
        botDiv.className = 'chat-msg bot';
        var tag = isCmd ? '<span class="tag command">指令</span>' : '<span class="tag chat">闲聊</span>';
        botDiv.innerHTML = '<div class="meta">' + now + ' AIBot' + tag + '</div><div>' + esc(reply) + '</div>';
        chatArea.appendChild(botDiv);
        chatArea.scrollTop = chatArea.scrollHeight;
    })
    .catch(function(e) {
        var errDiv = document.createElement('div');
        errDiv.className = 'chat-error';
        errDiv.textContent = '[错误] 发送失败: ' + e.message + ' — 请检查 chat_service 是否正常运行';
        chatArea.appendChild(errDiv);
        chatArea.scrollTop = chatArea.scrollHeight;
    })
    .finally(function() {
        sendBtn.disabled = false;
        sendBtn.textContent = '发送';
    });
}

// 启动轮询
refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print("  Minecraft 聊天服务已启动")
    print(f"  聊天记忆: {len(memory.history)} 条")
    print("  规则: 句首带 1 = 指令，否则 = 闲聊")
    print("  例: '你好' → 闲聊")
    print("  例: '1砍3棵树给我' → 执行指令")
    print(f"  服务地址: {cfg.CHAT_SERVICE_HOST}:{cfg.CHAT_SERVICE_PORT}")
    print("=" * 50)
    uvicorn.run(app, host=cfg.CHAT_SERVICE_HOST, port=cfg.CHAT_SERVICE_PORT)
