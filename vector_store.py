import os
import json
import time
import hashlib
from config import cfg


class MinecraftVectorStore:
    def __init__(self, persist_dir=None):
        # 使用配置文件中的 HF_ENDPOINT
        os.environ["HF_ENDPOINT"] = cfg.HF_ENDPOINT

        # 使用配置文件中的 Embedding 模型
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma

        self.embeddings = HuggingFaceEmbeddings(
            model_name=cfg.EMBEDDING_MODEL,
            model_kwargs={"device": cfg.EMBEDDING_DEVICE}
        )

        # 使用配置目录
        if persist_dir is None:
            persist_dir = cfg.VECTOR_DB_DIR

        self.wiki_store = Chroma(
            collection_name=cfg.COLLECTION_WIKI,
            embedding_function=self.embeddings,
            persist_directory=f"{persist_dir}/wiki"
        )
        self.skill_store = Chroma(
            collection_name=cfg.COLLECTION_SKILLS,
            embedding_function=self.embeddings,
            persist_directory=f"{persist_dir}/skills"
        )
        self.memory_store = Chroma(
            collection_name=cfg.COLLECTION_MEMORY,
            embedding_function=self.embeddings,
            persist_directory=f"{persist_dir}/memory"
        )

        # 版本文件，用来追踪知识库是否需要更新
        self.version_file = f"{persist_dir}/wiki_version.json"

    # ====== 知识库版本管理 ======

    def _get_wiki_version(self) -> str:
        """读取当前知识库版本"""
        if os.path.exists(self.version_file):
            try:
                with open(self.version_file, "r") as f:
                    data = json.load(f)
                    return data.get("version", "")
            except (json.JSONDecodeError, IOError) as e:
                print(f"[vector_store] 读取版本文件失败，将视为空: {e}")
        return ""

    def _save_wiki_version(self, version: str):
        """保存知识库版本，读-改-写避免覆盖其他 key"""
        os.makedirs(os.path.dirname(self.version_file), exist_ok=True)
        saved = {}
        if os.path.exists(self.version_file):
            try:
                with open(self.version_file, "r") as f:
                    saved = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"[vector_store] 读取版本文件失败，将覆盖: {e}")
        saved["version"] = version
        saved["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.version_file, "w") as f:
            json.dump(saved, f, ensure_ascii=False)

    def _calculate_data_hash(self, docs_data) -> str:
        """计算数据的哈希值，用于检测变化"""
        content = json.dumps(docs_data, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(content.encode()).hexdigest()

    # ====== 加载 Wiki（带自动更新） ======

    def load_wiki(self):
        from langchain_core.documents import Document

        docs_data = [
            {"text": "合成工作台：4个木板摆满2x2合成格", "cat": "crafting"},
            {"text": "合成木板：1个原木放入合成格，得到4个木板", "cat": "crafting"},
            {"text": "合成木棍：2个木板竖直排列", "cat": "crafting"},
            {"text": "合成木镐：3个木板横排加2个木棍竖排", "cat": "crafting"},
            {"text": "合成石镐：3个圆石横排加2个木棍竖排", "cat": "crafting"},
            {"text": "合成铁镐：3个铁锭横排加2个木棍竖排", "cat": "crafting"},
            {"text": "合成熔炉：8个圆石围一圈中间空", "cat": "crafting"},
            {"text": "合成火把：1个煤炭加1个木棍竖直排列", "cat": "crafting"},
            {"text": "合成箱子：8个木板围一圈中间空", "cat": "crafting"},
            {"text": "合成床：3个羊毛加3个木板", "cat": "crafting"},
            {"text": "合成门：6个木板排成3x2", "cat": "crafting"},
            {"text": "生存第一步：先砍树获取原木，合成木板和工作台", "cat": "survival"},
            {"text": "铁矿在Y=0到Y=64之间生成，Y=16最常见", "cat": "survival"},
            {"text": "钻石在Y=-64到Y=16之间生成，Y=-59最常见", "cat": "survival"},
            {"text": "煤矿在Y=0到Y=320之间生成，是最常见的矿石", "cat": "survival"},
            {"text": "入夜前必须建造庇护所或床，否则会刷怪", "cat": "survival"},
            {"text": "挖矿时带足火把，不要垂直向下挖", "cat": "survival"},
            {"text": "橡木原木英文名是oak_log，白桦原木是birch_log，云杉原木是spruce_log", "cat": "blocks"},
            {"text": "石头是stone，圆石是cobblestone，泥土是dirt", "cat": "blocks"},
            {"text": "铁矿石是iron_ore，深层铁矿是deepslate_iron_ore", "cat": "blocks"},
            {"text": "钻石矿是diamond_ore，深层钻石矿是deepslate_diamond_ore", "cat": "blocks"},
            {"text": "橡木木板是oak_planks，橡木台阶是oak_slab", "cat": "blocks"},
            {"text": "建造简单小屋：5x5地基用圆石，墙壁用木板4格高，屋顶用台阶，留一面开门", "cat": "building"},
        ]

        # 计算当前数据的哈希
        current_hash = self._calculate_data_hash(docs_data)
        saved_hash = self._get_wiki_version()

        # 导入外部知识库数据（独立版本检查，不受内置 hash 影响）
        self.import_json_data()

        # 如果哈希一样，说明数据没变，跳过
        if current_hash == saved_hash:
            count = len(self.wiki_store.get()["ids"])
            print(f"Wiki 知识库无变化，共 {count} 条记录")
            return

        # 数据有变化，只清除旧的 built_in 记录，不动外部导入的数据
        print("检测到内置 Wiki 知识有更新，正在重新加载...")
        existing = self.wiki_store.get()
        old_builtin_ids = []
        for i, meta in enumerate(existing.get("metadatas", [])):
            if meta and meta.get("source") == "built_in":
                old_builtin_ids.append(existing["ids"][i])
        if old_builtin_ids:
            self.wiki_store.delete(ids=old_builtin_ids)
            print(f"  已清除 {len(old_builtin_ids)} 条旧内置记录")

        docs = [
            Document(page_content=d["text"], metadata={"category": d["cat"], "source": "built_in"})
            for d in docs_data
        ]
        self.wiki_store.add_documents(docs)
        self._save_wiki_version(current_hash)
        print(f"  已加载 {len(docs)} 条内置知识")

    # ====== 导入外部数据（wiki_data.json） ======

    def import_json_data(self, json_path=None, force=False):
        """从 JSON 文件导入数据，支持增量更新"""
        from langchain_core.documents import Document

        if json_path is None:
            json_path = cfg.WIKI_DATA_FILE
        if not os.path.isabs(json_path):
            json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), json_path)

        if not os.path.exists(json_path):
            print(f"⚠ 文件不存在: {json_path}")
            return

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 计算文件哈希
        file_hash = self._calculate_data_hash(data)
        version_key = f"json_{os.path.basename(json_path)}"

        # 检查是否已导入过
        saved_versions = {}
        if os.path.exists(self.version_file):
            with open(self.version_file, "r") as f:
                saved_versions = json.load(f)

        if not force and saved_versions.get(version_key) == file_hash:
            print(f"{json_path} 数据无变化，跳过导入")
            return

        # 找出已有的 json 数据并删除
        existing = self.wiki_store.get()
        old_json_ids = []
        for i, meta in enumerate(existing.get("metadatas", [])):
            if meta and meta.get("source") == json_path:
                old_json_ids.append(existing["ids"][i])

        if old_json_ids:
            self.wiki_store.delete(ids=old_json_ids)
            print(f"  已清除 {len(old_json_ids)} 条旧 JSON 数据")

        # 导入新数据
        docs = []
        for item in data:
            text = item.get("text", "")
            if text and len(text) > 10:
                docs.append(Document(
                    page_content=text,
                    metadata={
                        "source": json_path,
                        "type": item.get("type", "unknown"),
                        "name": item.get("name", ""),
                    }
                ))

        if len(docs) == 0:
            print(f"⚠ {json_path} 无有效数据可导入")
            return

        # 分批写入
        total = len(docs)
        batch_size = 50
        for i in range(0, total, batch_size):
            batch = docs[i:i + batch_size]
            self.wiki_store.add_documents(batch)
            print(f"  导入中 {min(i + batch_size, total)}/{total}")

        # 保存版本
        saved_versions[version_key] = file_hash
        with open(self.version_file, "w") as f:
            json.dump(saved_versions, f)

        print(f"  已导入 {total} 条数据")

    # ====== 技能保存（不变） ======

    def save_skill(self, task: str, result: str, steps: list = None):
        from langchain_core.documents import Document
        content = f"任务: {task}\n结果: {result}"
        if steps:
            content += f"\n步骤: {json.dumps(steps, ensure_ascii=False)}"
        doc = Document(
            page_content=content,
            metadata={
                "task": task,
                "timestamp": str(int(time.time())),
            }
        )
        self.skill_store.add_documents([doc])

    # ====== 记忆保存（不变） ======

    def save_memory(self, event: str, details: dict):
        from langchain_core.documents import Document
        content = f"{event}: {json.dumps(details, ensure_ascii=False)}"
        doc = Document(
            page_content=content,
            metadata={
                "event": event,
                "timestamp": str(int(time.time()))
            }
        )
        self.memory_store.add_documents([doc])

    # ====== 检索（不变） ======

    def search_wiki(self, query: str, k: int = 3) -> str:
        results = self.wiki_store.similarity_search(query, k=k)
        if results:
            return "\n".join([doc.page_content for doc in results])
        return "未找到相关知识"

    def search_skills(self, query: str, k: int = 3) -> str:
        if len(self.skill_store.get()["ids"]) == 0:
            return "还没有学到任何技能"
        results = self.skill_store.similarity_search(query, k=k)
        if results:
            return "\n---\n".join([doc.page_content for doc in results])
        return "未找到相关技能"

    def search_memory(self, query: str, k: int = 3) -> str:
        if len(self.memory_store.get()["ids"]) == 0:
            return "还没有任何游戏记忆"
        results = self.memory_store.similarity_search(query, k=k)
        if results:
            return "\n".join([doc.page_content for doc in results])
        return "未找到相关记忆"

    # ====== 统计信息 ======

    def get_stats(self) -> dict:
        return {
            "wiki": len(self.wiki_store.get()["ids"]),
            "skills": len(self.skill_store.get()["ids"]),
            "memory": len(self.memory_store.get()["ids"]),
        }