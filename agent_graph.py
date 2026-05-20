"""
Minecraft AI Agent - LangGraph 版本
用图状态机替代简单 AgentExecutor，实现更复杂的状态管理
"""

import os
import sys
import requests
import uuid
from typing import Annotated, Literal
from dotenv import load_dotenv

# 必须在任何 ML 库之前加载 .env 并设置镜像
load_dotenv()
if os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT")
if os.getenv("DASHSCOPE_API_KEY"):
    os.environ["DASHSCOPE_API_KEY"] = os.getenv("DASHSCOPE_API_KEY")

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain.tools import tool
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from config import cfg

load_dotenv()

# ========== 工具定义 ==========

@tool
def connect_bot(port: int = cfg.MC_SERVER_PORT) -> str:
    """连接到 Minecraft 服务器"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/connect", json={"port": port}, timeout=30)
        return str(res.json())
    except Exception as e:
        return f"连接失败: {e}"

@tool
def get_bot_status() -> str:
    """获取 Bot 当前状态（位置、血量、食物、背包）"""
    try:
        res = requests.get(f"{cfg.BOT_URL}/status", timeout=10)
        return str(res.json())
    except Exception as e:
        return f"获取状态失败: {e}"

@tool
def move_to(x: int, y: int, z: int) -> str:
    """移动 Bot 到指定坐标，会等待到达"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/goto", json={"x": x, "y": y, "z": z}, timeout=60)
        return str(res.json())
    except Exception as e:
        return f"移动失败: {e}"

@tool
def send_chat(message: str) -> str:
    """让 Bot 发送聊天消息"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/chat", json={"message": message}, timeout=10)
        return str(res.json())
    except Exception as e:
        return f"发送失败: {e}"

@tool
def run_command(command: str) -> str:
    """执行MC命令，只允许 /tp 传送"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/command", json={"command": command}, timeout=10)
        return str(res.json())
    except Exception as e:
        return f"执行失败: {e}"

@tool
def find_block(name: str, distance: int = 64) -> str:
    """搜索指定方块，name是英文名如oak_log, diamond_ore"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/find_block", json={"name": name, "distance": distance}, timeout=10)
        return str(res.json())
    except Exception as e:
        return f"搜索失败: {e}"

@tool
def chop_and_deliver(count: int = 1) -> str:
    """砍指定数量的树，收集所有木头，然后走到玩家身边丢给玩家。count是要砍的树的数量"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/chop_and_deliver", json={"count": count}, timeout=120)
        return str(res.json())
    except requests.exceptions.Timeout:
        return "砍树交付超时，可能树太远了"
    except Exception as e:
        return f"失败: {e}"

@tool
def chop_tree() -> str:
    """砍一棵完整的树"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/chop_tree", timeout=60)
        return str(res.json())
    except requests.exceptions.Timeout:
        return "砍树超时，可能路径太远或被卡住了"
    except Exception as e:
        return f"砍树失败: {e}"

@tool
def collect_items() -> str:
    """收集附近掉落物"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/collect", timeout=10)
        return str(res.json())
    except Exception as e:
        return f"收集失败: {e}"

@tool
def goto_player() -> str:
    """走到最近的玩家身边（智能寻路，支持搭桥和爬升）"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/goto_player", timeout=60)
        result = res.json()
        if result.get("method") == "build_path":
            return f"成功走到玩家身边（通过搭建方块路径）"
        elif result.get("status") == "arrived":
            return f"成功走到玩家身边"
        else:
            return str(result)
    except Exception as e:
        return f"失败: {e}"

@tool
def drop_item(name: str) -> str:
    """丢出背包中的指定物品给玩家"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/drop_item", json={"name": name}, timeout=10)
        return str(res.json())
    except Exception as e:
        return f"丢弃失败: {e}"

@tool
def dig_at(x: int, y: int, z: int) -> str:
    """挖掘指定坐标的方块"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/dig", json={"x": x, "y": y, "z": z}, timeout=30)
        return str(res.json())
    except Exception as e:
        return f"挖掘失败: {e}"

@tool
def craft_item(name: str, count: int = 1) -> str:
    """合成物品（2x2背包合成）。name是英文名如oak_planks, stick等。简单物品可以直接合成"""
    result = ""

    # 方案二：自动注入知识库参考
    if HAS_KNOWLEDGE:
        knowledge = vs.search_wiki(f"合成 {name}")
        if "未找到" not in knowledge:
            result += f"【知识库参考】{knowledge}\n\n"

    try:
        res = requests.post(f"{cfg.BOT_URL}/craft", json={"name": name, "count": count}, timeout=30)
        result += f"【执行结果】{str(res.json())}"
        return result
    except Exception as e:
        return result + f"合成失败: {e}"

@tool
def craft_at_table(name: str, count: int = 1) -> str:
    """在工作台合成物品（3x3合成）。需要先走到工作台旁边。name是英文名如wooden_pickaxe, furnace等"""
    result = ""

    # 方案二：自动注入知识库参考
    if HAS_KNOWLEDGE:
        knowledge = vs.search_wiki(f"合成 {name}")
        if "未找到" not in knowledge:
            result += f"【知识库参考】{knowledge}\n\n"

    try:
        res = requests.post(f"{cfg.BOT_URL}/craft_at_table", json={"name": name, "count": count}, timeout=30)
        result += f"【执行结果】{str(res.json())}"
        return result
    except Exception as e:
        return result + f"合成失败: {e}"

@tool
def place_here(name: str) -> str:
    """在Bot当前位置旁边放置方块，最简单可靠的放置方式。name是英文名如crafting_table, furnace等"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/place_here", json={"name": name}, timeout=10)
        return str(res.json())
    except Exception as e:
        return f"放置失败: {e}"

@tool
def get_nearby_blocks() -> str:
    """获取 Bot 周围的方块列表"""
    try:
        res = requests.get(f"{cfg.BOT_URL}/nearby", timeout=10)
        return str(res.json())
    except Exception as e:
        return f"获取失败: {e}"

@tool
def check_equipment() -> str:
    """查看Bot当前装备和背包里的工具"""
    try:
        res = requests.get(f"{cfg.BOT_URL}/equipment", timeout=10)
        return str(res.json())
    except Exception as e:
        return f"查看失败: {e}"

@tool
def equip_item(name: str) -> str:
    """手动装备指定物品到手上。name是物品英文名如diamond_pickaxe, iron_sword等"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/equip", json={"name": name}, timeout=10)
        return str(res.json())
    except Exception as e:
        return f"装备失败: {e}"

@tool
def pickup_items(radius: int = 10) -> str:
    """手动触发拾取附近掉落物，radius是拾取范围默认10格"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/pickup", json={"radius": radius}, timeout=30)
        return str(res.json())
    except Exception as e:
        return f"拾取失败: {e}"

@tool
def place_block(x: int, y: int, z: int, name: str) -> str:
    """在指定坐标放置方块"""
    try:
        res = requests.post(f"{cfg.BOT_URL}/place_block", json={"x": x, "y": y, "z": z, "name": name}, timeout=10)
        return str(res.json())
    except Exception as e:
        return f"放置失败: {e}"

# 知识库工具（如果有 vector_store）
try:
    from vector_store import MinecraftVectorStore
    vs = MinecraftVectorStore()
    vs.load_wiki()

    @tool
    def search_knowledge(query: str) -> str:
        """搜索Minecraft知识库，查询合成表、方块信息、生存技巧等"""
        wiki = vs.search_wiki(query)
        skills = vs.search_skills(query)
        response = f"【知识库】\n{wiki}"
        if "还没有" not in skills:
            response += f"\n\n【历史经验】\n{skills}"
        return response

    @tool
    def remember_location(name: str, x: int, y: int, z: int) -> str:
        """记住一个重要位置"""
        vs.save_memory(f"重要位置-{name}", {"name": name, "x": x, "y": y, "z": z})
        return f"已记住: {name} ({x}, {y}, {z})"

    @tool
    def search_game_memory(query: str) -> str:
        """搜索游戏记忆"""
        return vs.search_memory(query)

    HAS_KNOWLEDGE = True
    print("✓ 知识库已加载")
except Exception as e:
    HAS_KNOWLEDGE = False
    print(f"⚠ 知识库未加载: {e}")


# ========== 构建工具列表 ==========

tools = [connect_bot, get_bot_status, move_to, send_chat, run_command,
         find_block, chop_tree, collect_items, goto_player, drop_item,
         dig_at, get_nearby_blocks, place_block, craft_item, craft_at_table,
         place_here, chop_and_deliver, pickup_items, equip_item, check_equipment]

if HAS_KNOWLEDGE:
    tools.extend([search_knowledge, remember_location, search_game_memory])


# ========== 构建 LangGraph ==========

SYSTEM_PROMPT = """你是一个Minecraft AI玩家助手，名叫AIBot，你在生存模式下游玩。

规则：
1. 第一次使用前，必须先用 connect_bot 连接到服务器
2. 你是生存模式玩家，所有物品必须通过砍树、挖矿、合成获得，严禁使用 /give、/gamemode 等作弊命令
3. run_command 只能用于 /tp 传送，禁止执行其他任何命令
4. 需要合成物品时，用 craft_item 或 craft_at_table 工具
5. 需要工具时先合成：砍树拿原木 → craft_item 合成木板 → craft_item 合成工具
6. 砍树用 chop_tree，挖矿用 find_block + dig_at
7. 给玩家物品：先获取 → goto_player → drop_item
8. 如果用户要求"砍N棵树给我"或"给我N个木头"，直接用 chop_and_deliver 一步完成
9. 涉及合成配方、矿石分布、生物属性、生存技巧时，必须先用 search_knowledge 查询，禁止凭记忆回答
10. 如果搜索不到方块，告诉用户而不是反复搜索
11. 放置方块优先用 place_here，它会自动在脚边找合适位置放
12. 用中文回复用户"""

# 初始化模型并绑定工具
model = ChatTongyi(model=cfg.LLM_COMMAND_MODEL)
model_with_tools = model.bind_tools(tools)

# 工具执行节点
tool_node = ToolNode(tools)


# ===== 定义节点 =====

# 判断是否需要查知识库的关键词
KNOWLEDGE_KEYWORDS = [
    "合成", "怎么做", "怎么合成", "配方", "制作",
    "哪里", "在哪", "分布", "生成", "刷新",
    "怎么打", "怎么杀", "弱点", "掉落",
    "什么是", "是什么", "有什么用",
    "附魔", "药水", "酿造",
    "挖", "矿", "钻石", "铁", "金", "煤",
    "生存", "技巧", "攻略", "教程",
]


def inject_knowledge(state: MessagesState):
    """方案三：在 LLM 推理之前自动查询知识库"""
    messages = state["messages"]

    # 取最后一条用户消息
    last_human = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            last_human = msg.content
            break

    # 没有用户消息或没有知识库，跳过
    if not last_human or not HAS_KNOWLEDGE:
        return {"messages": []}

    # 检查是否需要查知识库（包含关键词才查，避免每次都查浪费时间）
    need_knowledge = any(kw in last_human for kw in KNOWLEDGE_KEYWORDS)

    if not need_knowledge:
        return {"messages": []}

    # 查询知识库
    wiki_result = vs.search_wiki(last_human)
    memory_result = vs.search_memory(last_human)

    # 拼接知识
    knowledge_parts = []
    if wiki_result and "未找到" not in wiki_result:
        knowledge_parts.append(f"Wiki知识: {wiki_result}")
    if memory_result and "还没有" not in memory_result and "未找到" not in memory_result:
        knowledge_parts.append(f"游戏记忆: {memory_result}")

    if not knowledge_parts:
        return {"messages": []}

    # 作为系统消息注入，LLM 会看到这些知识
    knowledge_text = "\n".join(knowledge_parts)
    knowledge_msg = SystemMessage(
        content=f"【自动检索的参考知识，请优先参考以下内容回答，不要凭记忆编造】\n{knowledge_text}"
    )

    print(f"[知识注入] 检索到相关知识，已注入 prompt")
    return {"messages": [knowledge_msg]}


def call_model(state: MessagesState):
    """调用 LLM 进行推理"""
    messages = state["messages"]

    # 如果第一条不是系统消息，插入系统提示
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages

    response = model_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: MessagesState) -> Literal["tools", END]:
    """决定是调用工具还是结束"""
    last_message = state["messages"][-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return END


# ===== 构建图 =====

workflow = StateGraph(MessagesState)

# 添加节点（三个节点）
workflow.add_node("knowledge", inject_knowledge)  # 新增：知识注入节点
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)

# 添加边
workflow.add_edge(START, "knowledge")        # 入口 → 先查知识库
workflow.add_edge("knowledge", "agent")      # 知识注入完 → LLM 推理
workflow.add_conditional_edges(               # agent → tools 或 END
    "agent",
    should_continue,
)
workflow.add_edge("tools", "agent")           # tools → agent（工具执行完回到推理，不再重复查知识库）

# 添加记忆（支持多轮对话）
memory = MemorySaver()
graph = workflow.compile(checkpointer=memory)


# ========== 交互循环 ==========

if __name__ == "__main__":
    print("=" * 50)
    print("  Minecraft AI Agent (LangGraph 版)")
    print("  输入 'quit' 退出")
    print("  输入 'reset' 重置对话")
    print("  输入 'state' 查看当前状态")
    print("=" * 50)

    # 会话配置（同一个 thread_id 共享记忆）
    config = {"configurable": {"thread_id": "minecraft-session-1"}}

    # 最大步数限制，防止无限循环
    MAX_STEPS = 50

    while True:
        user_input = input("\n你的指令 > ").strip()

        if user_input.lower() == "quit":
            print("再见！")
            break

        if user_input.lower() == "reset":
            config = {"configurable": {"thread_id": f"minecraft-session-{uuid.uuid4().hex[:8]}"}}
            print("对话已重置")
            continue

        if user_input.lower() == "state":
            snapshot = graph.get_state(config)
            msgs = snapshot.values.get("messages", [])
            print(f"对话历史: {len(msgs)} 条消息")
            for msg in msgs[-5:]:
                role = type(msg).__name__
                content = str(msg.content)[:100] if msg.content else "(工具调用)"
                print(f"  [{role}] {content}")
            continue

        if not user_input:
            continue

        # 执行
        try:
            result = graph.invoke(
                {"messages": [HumanMessage(content=user_input)]},
                {**config, "recursion_limit": MAX_STEPS}
            )

            ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage) and m.content]
            if ai_messages:
                output = ai_messages[-1].content
                print(f"\nAgent: {output}")
            else:
                output = "(执行完毕)"
                print("\nAgent: (执行完毕，无文本回复)")

            # ===== 保存到向量知识库 =====
            if HAS_KNOWLEDGE:
                vs.save_skill(task=user_input, result=output)

                try:
                    status = requests.get(f"{cfg.BOT_URL}/status", timeout=5).json()
                    pos = status.get("position", {})
                    vs.save_memory(
                        f"玩家指令-{user_input[:30]}",
                        {
                            "input": user_input,
                            "output": output[:100],
                            "position": {
                                "x": round(pos.get("x", 0)),
                                "y": round(pos.get("y", 0)),
                                "z": round(pos.get("z", 0))
                            }
                        }
                    )
                except:
                    pass

        except Exception as e:
            error_msg = str(e)
            print(f"\n错误: {error_msg}")

            if "tool_call" in error_msg or "InvalidParameter" in error_msg:
                print("检测到对话历史损坏，自动重置会话...")
                config = {"configurable": {"thread_id": f"minecraft-session-{uuid.uuid4().hex[:8]}"}}