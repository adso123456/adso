from vector_store import MinecraftVectorStore

if __name__ == "__main__":
    vs = MinecraftVectorStore()

    # 加载内置知识（自动检测更新）
    vs.load_wiki()

    # 导入 JSON 数据（自动检测更新）
    vs.import_json_data("wiki_data.json")

    # 如果想强制重新导入，用：
    # vs.import_json_data("wiki_data.json", force=True)

    # 打印统计
    stats = vs.get_stats()
    print(f"\n知识库统计:")
    print(f"  Wiki: {stats['wiki']} 条")
    print(f"  技能: {stats['skills']} 条")
    print(f"  记忆: {stats['memory']} 条")