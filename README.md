# Minecraft Agent

基于 **LangGraph + Mineflayer** 的 Minecraft 智能体，支持自然语言指令、RAG 知识增强、多模型协作和智能寻路。

<details>
<summary>🏗️ 系统架构（点击展开）</summary>

```
                   Minecraft 玩家
                        │
                        ▼
              ┌─────────────────┐
              │ Minecraft 服务器  │  (:25565)
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ Node.js 机器人   │  Mineflayer + Express API (:3001)
              │ bot_server.js   │──→ 执行移动/挖掘/合成/放置等操作
              └───────┬─────────┘
                      │ HTTP
                      ▼
              ┌─────────────────┐
              │ Python 聊天服务  │  FastAPI (:8000)
              │ chat_service.py │──→ 区分闲聊(轻模型)/指令(强模型)
              └───────┬─────────┘
                      │
                      ▼
              ┌─────────────────┐
              │ LangGraph 智能体 │  ChatTongyi (通义千问)
              │ agent_graph.py  │──→ 多步推理 + 工具调用
              └───────┬─────────┘
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ Wiki 知识 │ │ 技能记忆  │ │ 游戏记忆  │
   │ 向量库   │ │ 向量库   │ │ 向量库   │
   └──────────┘ └──────────┘ └──────────┘
         └────────────┼────────────┘
                      │
              ┌───────┴─────────┐
              │    ChromaDB     │  文本向量化储存
              │ vector_store.py │  HuggingFace Embedding
              └─────────────────┘
```
</details>

## 功能特性

- **自然语言指令** — 在游戏聊天框输入 `1砍树` 即可触发 AI 自动执行
- **多模型协作** — 闲聊用轻量模型 (qwen-turbo)，复杂指令用强模型 (qwen-plus)
- **RAG 知识增强** — 内置 Minecraft Wiki 中文知识库，LLM 推理前自动注入相关知识
- **20+ 工具** — 移动、挖掘、砍树、合成、放置、拾取、交易等全自动执行
- **智能寻路** — 标准 A* 寻路失败后自动搭桥/搭梯脱困
- **自动拾取** — 周期性扫描附近掉落物并捡取
- **自动换工具** — 根据挖掘目标自动装备最佳工具
- **断线重连** — 指数退避重连机制，最多 10 次
- **多轮对话记忆** — 聊天历史持久化，上下文连续对话

## 技术栈

| 层级 | 技术 |
|------|------|
| AI 引擎 | Python · LangGraph · ChatTongyi (通义千问) |
| 知识库 | ChromaDB · HuggingFace Embedding (text2vec-base-chinese) |
| 聊天路由 | Python · FastAPI · uvicorn |
| 游戏机器人 | Node.js · Mineflayer · Express |
| 寻路 | mineflayer-pathfinder (A*) + 自定义脱困策略 |
| 游戏数据 | minecraft-data (1.21.1) |

## 环境要求

- **Python** 3.10+
- **Node.js** 18+
- **Minecraft Java 版** 1.21.1（需开启局域网/服务器模式）
- **DashScope API Key**（[阿里云百炼平台](https://dashscope.aliyun.com/) 免费额度）

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/adso123456/adso.git
cd adso
```

### 2. 安装 Python 依赖

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 安装 Node.js 依赖

```bash
npm install
```

### 4. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少需要配置：

```env
DASHSCOPE_API_KEY=你的通义千问API密钥
```

> 其他配置（端口、模型选择等）保持默认即可。

### 5. 导入知识库（首次使用）

```bash
# 先提取 Minecraft 游戏数据（可选，约 2-3 分钟）
node extract_wiki.js

# 导入到向量库
python import_wiki_data.py
```

## 启动

### 一键启动（推荐）

```bash
python launcher.py
```

自动启动所有服务并打开浏览器控制台。

### 手动分别启动

```bash
# 终端 1: 启动 Minecraft 机器人
node bot_server.js

# 终端 2: 启动 AI 聊天服务
python chat_service.py

# 终端 3: 启动 Web 控制台
python web_ui.py
# → 浏览器打开 http://localhost:7860
```

## 使用

进入 Minecraft 游戏后，在聊天框发送消息：

### 闲聊模式

```
你好，你是谁？
今天天气怎么样？
```

机器人会用轻量模型回复（限制 60 字以内）。

### 指令模式

以 `1` 开头触发 AI 指令执行：

| 指令示例 | 效果 |
|----------|------|
| `1砍3棵树给我` | 自动找树、砍伐、回到你身边并投掷原木 |
| `1合成一把钻石镐` | 检查材料、寻找工作台、合成钻石镐 |
| `1去坐标 100 64 -200` | 移动到指定坐标 |
| `1在脚下放一个火把` | 自动放置方块 |
| `1附近有没有钻石矿` | 搜索附近方块并汇报 |
| `1帮我挖掉面前的方块` | 挖掘指定位置的方块 |

### 踩坑提示

- 机器人的活动范围需要在玩家加载区块内（Minecraft 的渲染距离限制）
- 如果机器人卡住，等 20 秒后会自动触发脱困策略（搭桥/搭梯）
- 合成复杂物品（如钻石装备）需要确保原材料在背包里

## 项目结构

```
minecraft-agent/
├── launcher.py                 # 一键启动器
├── web_ui.py                   # Gradio Web 可视化控制台
├── agent_graph.py              # LangGraph 智能体（核心 AI 大脑）
├── chat_service.py             # FastAPI 聊天路由服务
├── vector_store.py             # ChromaDB 向量知识库封装
├── advanced_synthesis_system.py # 多步合成链计算器
├── config.py                   # 统一配置管理
├── import_wiki_data.py         # Wiki 数据导入脚本
├── bot_server.js               # Mineflayer 机器人 + Express REST API
├── smart_pathfinding.js        # 智能寻路（搭桥/搭梯脱困）
├── extract_wiki.js             # Minecraft 游戏数据提取
├── package.json                # Node.js 依赖
├── requirements.txt            # Python 依赖
├── .env.example                # 环境变量模板
├── .gitignore
└── SKILL.md                    # Claude Code 技能卡片
```

## License

MIT
