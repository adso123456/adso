# Minecraft Agent

基于 LangGraph + Mineflayer 的 Minecraft 智能体，支持自然语言指令操控游戏角色。

## 功能

- **自然语言指令** — 聊天框输入 `1砍树` 即可触发 AI 自动执行
- **20+ 工具** — 移动、挖掘、砍树、合成、放置、拾取、交易全自动
- **智能寻路** — A* 寻路 + 搭桥/搭梯脱困
- **RAG 知识增强** — 内置 Minecraft Wiki 中文知识库
- **断线重连** — 指数退避，最多 10 次
- **自动拾取 & 换工具** — 扫描掉落物，按目标自动切换最佳工具
- **网页仪表盘** — `http://localhost:8000/panel` 实时查看状态/背包/聊天
- **首次配置引导** — 首次启动自动打开网页引导填写 API Key

## 环境要求

| 工具 | 版本 | 说明 |
|------|------|------|
| Python | 3.10 ~ 3.12 | |
| Node.js | 18 ~ 22 LTS | 建议用 [nvm-windows](https://github.com/coreybutler/nvm-windows) 管理版本 |
| Minecraft | 1.20.1 / 1.21.1 (Java 版) | 需开启局域网/服务器模式 |
| 启动器 | [HMCL](https://hmcl.huangyuhui.net/download/) | 推荐使用 HMCL 启动器 |
| DashScope API | - | [阿里云百炼](https://dashscope.aliyun.com/) 免费额度 |

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/adso123456/adso.git && cd adso

# 2. 安装依赖
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
npm install

# 3. 启动
python launcher.py
```

首次启动会自动打开浏览器引导填写 API Key，完成后自动跳转到网页仪表盘。

## 使用

在游戏聊天框发消息：

| 类型 | 格式 | 示例 |
|------|------|------|
| 闲聊 | 直接输入 | `你好，你是谁？` |
| 指令 | 以 `1` 开头 | `1砍3棵树给我`、`1合成一把钻石镐`、`1去坐标 100 64 -200` |

> 机器人需在玩家加载区块内活动；卡住时 20 秒后自动触发脱困。

## 技术栈

| 层 | 技术 |
|------|------|
| AI 引擎 | Python · LangGraph · 通义千问 |
| 知识库 | ChromaDB · HuggingFace Embedding |
| 聊天路由 | FastAPI · uvicorn |
| 游戏机器人 | Node.js · Mineflayer · Express |
| 寻路 | mineflayer-pathfinder + 自定义脱困 |
| 游戏版本 | minecraft-data 1.21.1 |

## 项目结构

```
├── launcher.py                 # 无界面启动器（含首次配置引导）
├── service_manager.py          # 进程管理 & 守护
├── agent_graph.py              # LangGraph 智能体（核心）
├── chat_service.py             # FastAPI 聊天路由 + 网页仪表盘
├── vector_store.py             # ChromaDB 向量库
├── config.py                   # 配置管理
├── bot_server.js               # Mineflayer + Express API
├── smart_pathfinding.js        # 智能寻路
├── utils.js                    # 工具函数
├── .env.example                # 环境变量模板
└── requirements.txt            # Python 依赖
```

## License

MIT
