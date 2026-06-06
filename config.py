"""
Minecraft Agent 中心化配置模块
使用方式: from config import cfg
"""

import os
from dotenv import load_dotenv

# 加载环境变量（自动查找 .env 文件）
load_dotenv()

# 立即设置 HuggingFace 镜像，必须在 import ML 库之前
if os.getenv("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT")


class Config:
    """应用配置类"""

    # ==========================================
    # 一、服务配置
    # ==========================================
    BOT_URL: str = os.getenv("BOT_URL", "http://localhost:3005")
    CHAT_SERVICE_HOST: str = os.getenv("CHAT_SERVICE_HOST", "0.0.0.0")
    CHAT_SERVICE_PORT: int = int(os.getenv("CHAT_SERVICE_PORT", "8000"))
    MC_SERVER_PORT: int = int(os.getenv("MC_SERVER_PORT", "25565"))

    # ==========================================
    # 二、向量知识库配置
    # ==========================================
    VECTOR_DB_DIR: str = os.getenv("VECTOR_DB_DIR", "./vector_db")
    HF_ENDPOINT: str = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

    # ==========================================
    # 三、模型配置
    # ==========================================
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    LLM_CHAT_MODEL: str = os.getenv("LLM_CHAT_MODEL", "deepseek-v4-flash")
    LLM_COMMAND_MODEL: str = os.getenv("LLM_COMMAND_MODEL", "deepseek-v4-pro")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "shibing624/text2vec-base-chinese")
    EMBEDDING_DEVICE: str = os.getenv("EMBEDDING_DEVICE", "cpu")

    # ==========================================
    # 四、持久化配置
    # ==========================================
    MEMORY_FILE: str = os.getenv("MEMORY_FILE", "chat_memory.json")
    MAX_MEMORY_HISTORY: int = int(os.getenv("MAX_MEMORY_HISTORY", "200"))

    # ==========================================
    # 五、向量库集合名称
    # ==========================================
    COLLECTION_WIKI: str = os.getenv("COLLECTION_WIKI", "minecraft_wiki")
    COLLECTION_SKILLS: str = os.getenv("COLLECTION_SKILLS", "learned_skills")
    COLLECTION_MEMORY: str = os.getenv("COLLECTION_MEMORY", "game_memory")

    # ==========================================
    # 五-B、向量库存储上限（防止长期膨胀）
    # ==========================================
    MAX_SKILLS: int = int(os.getenv("MAX_SKILLS", "500"))
    MAX_MEMORY: int = int(os.getenv("MAX_MEMORY", "1000"))

    # ==========================================
    # 六、Wiki 数据配置
    # ==========================================
    WIKI_DATA_FILE: str = os.getenv("WIKI_DATA_FILE", "wiki_data.json")

    # ==========================================
    # 七、开发/调试配置
    # ==========================================
    ENABLE_VECTOR_STORE: bool = os.getenv("ENABLE_VECTOR_STORE", "true").lower() == "true"


# 单例实例
cfg = Config()
