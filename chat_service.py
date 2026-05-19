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
from pydantic import BaseModel
from dotenv import load_dotenv

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from agent_graph import graph

from config import cfg

load_dotenv()

app = FastAPI(title="Minecraft Chat Service")


# ========== 模型 ==========
# 闲聊使用轻量模型，指令执行使用 agent_graph 中的模型
chat_model = ChatTongyi(model=cfg.LLM_CHAT_MODEL)


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
                requests.post(f"{cfg.BOT_URL}/chat", json={"message": f"@{username} {reply}"}, timeout=5)
            except:
                pass

            memory.add(username, message, reply, "command")

            # ===== 保存到向量知识库 =====
            # 检查是否启用向量知识库
            if cfg.ENABLE_VECTOR_STORE:
                try:
                    from vector_store import MinecraftVectorStore
                    vs = MinecraftVectorStore()

                    # 保存技能
                    vs.save_skill(task=message, result=reply)

                    # 如果涉及位置，保存位置记忆
                    try:
                        status = requests.get(f"{cfg.BOT_URL}/status", timeout=5).json()
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
                    except:
                        pass
                except Exception as e:
                    print(f"⚠ 保存到向量库失败: {e}")

        active_tasks[task_id] = "done"

    except Exception as e:
        print(f"指令执行失败: {e}")
        active_tasks[task_id] = f"error: {e}"
        try:
            requests.post(f"{cfg.BOT_URL}/chat", json={
                "message": f"@{username} 任务失败了，再试一次吧"
            }, timeout=5)
        except:
            pass
        memory.add(username, message, "执行失败", "command")


class BotEventRequest(BaseModel):
    event: str
    details: dict


@app.post("/bot_event")
async def handle_bot_event(request: BotEventRequest):
    """接收 Bot 上报的游戏事件，保存到向量库"""
    if cfg.ENABLE_VECTOR_STORE:
        try:
            from vector_store import MinecraftVectorStore
            vs = MinecraftVectorStore()
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
