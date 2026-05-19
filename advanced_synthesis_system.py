"""
Minecraft 合成链系统
基于现有代码扩展的完整合成路径计算系统
"""

from collections import defaultdict, deque
import json
from typing import Dict, List, Set, Tuple, Optional


class AdvancedSynthesisSystem:
    """高级合成系统，支持完整合成链计算"""

    def __init__(self):
        """初始化合成系统"""
        # 存储配方数据
        self.recipes = {}  # {item: {ingredients: amount}}
        self.reverse_recipes = {}  # {ingredient: [{result_item: amount}]}

        # 预定义合成配方
        self._load_default_recipes()

    def _load_default_recipes(self):
        """加载默认合成配方"""
        # 原材料配方
        self.add_recipe("wooden_planks", {"oak_log": 1})
        self.add_recipe("stick", {"wooden_planks": 2})
        self.add_recipe("cobblestone", {"stone": 1})
        self.add_recipe("torch", {"stick": 1, "coal": 1})
        self.add_recipe("crafting_table", {"wooden_planks": 4})
        self.add_recipe("furnace", {"cobblestone": 8})
        self.add_recipe("oak_door", {"wooden_planks": 6})
        self.add_recipe("chest", {"wooden_planks": 8})
        self.add_recipe("leather", {"cow": 1})
        self.add_recipe("leather_helmet", {"leather": 5})
        self.add_recipe("iron_ingot", {"iron_ore": 1})
        self.add_recipe("iron_sword", {"iron_ingot": 2, "stick": 1})
        self.add_recipe("iron_pickaxe", {"iron_ingot": 3, "stick": 2})
        self.add_recipe("iron_shovel", {"iron_ingot": 1, "stick": 2})
        self.add_recipe("iron_axe", {"iron_ingot": 3, "stick": 2})
        self.add_recipe("iron_hoe", {"iron_ingot": 2, "stick": 2})
        self.add_recipe("wooden_pickaxe", {"wooden_planks": 3, "stick": 2})
        self.add_recipe("stone_pickaxe", {"cobblestone": 3, "stick": 2})
        self.add_recipe("bow", {"string": 3, "stick": 3})
        self.add_recipe("arrow", {"flint": 1, "stick": 1, "feather": 1})
        self.add_recipe("bread", {"wheat": 3})
        self.add_recipe("cake", {"egg": 1, "sugar": 2, "wheat": 3, "milk": 3})

        # 更复杂的合成配方
        self.add_recipe("ender_chest", {"obsidian": 8, "ender_eye": 1})
        self.add_recipe("enchanting_table", {"bookshelf": 1, "obsidian": 4, "diamond": 2})
        self.add_recipe("beacon", {"glass": 5, "obsidian": 5, "diamond": 1})
        self.add_recipe("bed", {"wool": 3, "planks": 3})

        # 工作台合成
        self.add_recipe("anvil", {"iron_ingot": 3, "iron_block": 4})
        self.add_recipe("dispenser", {"cobblestone": 7, "redstone": 1, "bow": 1})
        self.add_recipe("dropper", {"cobblestone": 7, "redstone": 1})
        self.add_recipe("hopper", {"iron_ingot": 5, "chest": 1})
        self.add_recipe("item_frame", {"leather": 1, "stick": 8})
        self.add_recipe("painting", {"stick": 8, "wool": 1})
        self.add_recipe("torch", {"coal": 1, "stick": 1})

    def add_recipe(self, result_item: str, ingredients: Dict[str, int]) -> None:
        """
        添加合成配方

        Args:
            result_item: 结果物品名称
            ingredients: 配方材料字典 {材料名: 数量}
        """
        self.recipes[result_item] = ingredients
        # 更新反向配方
        for ingredient, amount in ingredients.items():
            if ingredient not in self.reverse_recipes:
                self.reverse_recipes[ingredient] = []
            self.reverse_recipes[ingredient].append({result_item: amount})

    def get_synthesis_path(self, target_item: str, inventory: Optional[Dict[str, int]] = None) -> Tuple[List[Dict], bool]:
        """
        获取合成路径

        Args:
            target_item: 目标物品
            inventory: 当前库存 {物品名: 数量}

        Returns:
            tuple: (合成路径列表, 是否可合成)
        """
        if inventory is None:
            inventory = {}

        # 如果目标物品已经在库存中
        if target_item in inventory and inventory[target_item] > 0:
            return [], True

        # 如果目标物品没有配方
        if target_item not in self.recipes:
            return [], False

        # 使用广度优先搜索寻找最短合成路径
        queue = deque([(target_item, 0)])  # (物品, 层数)
        visited = {target_item}
        path_info = {target_item: {"parent": None, "recipe": None, "amount_needed": 1}}

        # 先查找直接需要的材料
        needed_items = self._find_needed_items(target_item, inventory)

        # BFS 寻找合成路径
        while queue:
            current_item, depth = queue.popleft()

            # 如果找到了所有必需的物品
            if self._all_needed_met(needed_items, inventory):
                break

            # 如果物品不在配方中
            if current_item not in self.recipes:
                continue

            recipe = self.recipes[current_item]

            # 检查是否可以通过已有物品合成
            can_make = True
            for ingredient, required_amount in recipe.items():
                # 如果材料在库存中且足够
                if ingredient in inventory and inventory[ingredient] >= required_amount:
                    continue
                elif ingredient in self.recipes:
                    # 如果材料需要进一步合成
                    if ingredient not in visited:
                        visited.add(ingredient)
                        queue.append((ingredient, depth + 1))
                        path_info[ingredient] = {"parent": current_item, "recipe": recipe, "amount_needed": required_amount}
                else:
                    # 材料不存在
                    can_make = False

        # 构建合成路径
        path = self._build_path(target_item, path_info, inventory)
        return path, True

    def _find_needed_items(self, target_item: str, inventory: Dict[str, int]) -> Dict[str, int]:
        """找出所有需要的材料（包括间接材料）"""
        needed = {}

        def dfs(item: str, needed_amount: int):
            if item not in self.recipes:
                # 原材料，添加到所需清单
                needed[item] = needed.get(item, 0) + needed_amount
                return

            recipe = self.recipes[item]
            for ingredient, amount in recipe.items():
                # 计算需要的原材料数量
                dfs(ingredient, amount * needed_amount)

        dfs(target_item, 1)
        return needed

    def _all_needed_met(self, needed_items: Dict[str, int], inventory: Dict[str, int]) -> bool:
        """检查是否所有需要的物品都已满足"""
        for item, amount in needed_items.items():
            if item in inventory:
                if inventory[item] < amount:
                    return False
            else:
                return False
        return True

    def _build_path(self, target_item: str, path_info: Dict, inventory: Dict[str, int]) -> List[Dict]:
        """构建合成路径"""
        path = []
        current_item = target_item

        # 从目标物品开始向上追溯
        while current_item is not None:
            info = path_info.get(current_item, {})
            parent = info.get("parent")

            if parent is not None and "recipe" in info:
                # 这是一个合成步骤
                path.append({
                    "item": current_item,
                    "from": parent,
                    "recipe": info["recipe"],
                    "amount_needed": info.get("amount_needed", 1)
                })

            current_item = parent

        # 反转路径，使它从原材料到目标物品
        path.reverse()
        return path

    def get_material_requirements(self, target_item: str, quantity: int = 1) -> Dict[str, int]:
        """
        获取制作指定数量目标物品所需的所有原材料

        Args:
            target_item: 目标物品
            quantity: 需要的数量

        Returns:
            所需原材料及数量的字典
        """
        materials = defaultdict(int)

        def calculate_materials(item: str, amount: int):
            if item not in self.recipes:
                # 原材料
                materials[item] += amount
                return

            recipe = self.recipes[item]
            for ingredient, ingredient_amount in recipe.items():
                calculate_materials(ingredient, ingredient_amount * amount)

        calculate_materials(target_item, quantity)
        return dict(materials)

    def get_available_synthesis_options(self, inventory: Dict[str, int]) -> Dict[str, List[Dict]]:
        """
        获取基于当前库存可用的合成选项

        Args:
            inventory: 当前库存

        Returns:
            可以合成的物品及其配方列表
        """
        options = {}

        # 遍历所有配方，检查是否可以合成
        for item, recipe in self.recipes.items():
            can_make = True
            missing_items = []

            # 检查是否可以合成
            for ingredient, amount in recipe.items():
                if ingredient not in inventory or inventory[ingredient] < amount:
                    can_make = False
                    missing_items.append(f"{ingredient} x{amount}")

            if can_make:
                if item not in options:
                    options[item] = []
                options[item].append({
                    "recipe": recipe,
                    "missing": missing_items
                })

        return options

    def calculate_synthesis_cost(self, target_item: str, inventory: Dict[str, int]) -> Dict:
        """
        计算合成指定物品的成本分析

        Args:
            target_item: 目标物品
            inventory: 当前库存

        Returns:
            成本分析结果
        """
        materials = self.get_material_requirements(target_item)
        cost_analysis = {
            "target_item": target_item,
            "required_materials": materials,
            "missing_materials": {},
            "total_missing": 0
        }

        # 分析哪些材料缺失
        for material, needed_amount in materials.items():
            if material in inventory:
                available = inventory[material]
                if available >= needed_amount:
                    continue
                else:
                    cost_analysis["missing_materials"][material] = {
                        "needed": needed_amount,
                        "available": available,
                        "missing": needed_amount - available
                    }
                    cost_analysis["total_missing"] += needed_amount - available
            else:
                cost_analysis["missing_materials"][material] = {
                    "needed": needed_amount,
                    "available": 0,
                    "missing": needed_amount
                }
                cost_analysis["total_missing"] += needed_amount

        return cost_analysis

    def print_synthesis_path(self, target_item: str, inventory: Optional[Dict[str, int]] = None) -> None:
        """
        打印合成路径

        Args:
            target_item: 目标物品
            inventory: 当前库存
        """
        if inventory is None:
            inventory = {}

        print(f"\n合成 {target_item} 的完整路径:")
        print("=" * 60)

        # 显示成本分析
        cost_analysis = self.calculate_synthesis_cost(target_item, inventory)
        print("成本分析:")
        print(f"  目标物品: {cost_analysis['target_item']}")
        print(f"  总共需要材料: {cost_analysis['total_missing']} 项")

        if cost_analysis["missing_materials"]:
            print("  缺失材料:")
            for material, details in cost_analysis["missing_materials"].items():
                print(f"    - {material}: 需要{details['needed']}, "
                      f"拥有{details['available']}, 缺少{details['missing']}")
        else:
            print("  所有材料都已具备!")

        # 获取合成路径
        path, can_make = self.get_synthesis_path(target_item, inventory)

        if not can_make:
            print(f"  无法合成 {target_item} - 没有相应的配方")
            return

        if not path:
            print(f"  目标物品 {target_item} 已在库存中")
            return

        # 显示原材料需求
        materials = self.get_material_requirements(target_item)
        print(f"\n所需原材料:")
        for material, amount in sorted(materials.items()):
            print(f"  - {material}: {amount}")

        print(f"\n合成步骤:")
        for i, step in enumerate(path, 1):
            recipe_str = ", ".join([f"{item} x{amount}" for item, amount in step["recipe"].items()])
            print(f"  {i}. 制作 {step['item']} 需要: {recipe_str}")

        print("=" * 60)

    def suggest_optimal_path(self, target_item: str, inventory: Dict[str, int]) -> str:
        """
        建议最优合成路径

        Args:
            target_item: 目标物品
            inventory: 当前库存

        Returns:
            建议字符串
        """
        # 检查是否可以合成
        cost_analysis = self.calculate_synthesis_cost(target_item, inventory)

        if cost_analysis["total_missing"] == 0:
            return f"✅ 直接可合成 {target_item}"

        # 如果有缺失材料，建议按依赖关系排序
        path, _ = self.get_synthesis_path(target_item, inventory)

        if not path:
            return f"需要先制作材料，建议制作以下物品: {list(cost_analysis['missing_materials'].keys())}"

        # 生成建议路径
        suggestions = []
        suggestions.append(f"为合成 {target_item}，建议按以下顺序操作:")

        # 按照路径顺序添加建议
        for i, step in enumerate(path, 1):
            recipe_str = ", ".join([f"{item} x{amount}" for item, amount in step["recipe"].items()])
            suggestions.append(f"  {i}. 先制作 {step['item']} (配方: {recipe_str})")

        # 添加缺失材料建议
        missing = [item for item in cost_analysis["missing_materials"]]
        if missing:
            suggestions.append(f"  ⚠️  还需要: {', '.join(missing)}")

        return "\n".join(suggestions)


# 示例使用
if __name__ == "__main__":
    # 创建高级合成系统
    synthesis_system = AdvancedSynthesisSystem()

    print("Minecraft 高级合成系统演示")
    print("=" * 60)

    # 测试不同的合成场景
    test_inventory = {
        "oak_log": 5,
        "coal": 3,
        "stick": 2,
        "cobblestone": 10,
        "leather": 8,
        "iron_ore": 2,
        "wooden_planks": 4,
        "iron_ingot": 1
    }

    print("当前库存:", test_inventory)
    print()

    # 测试合成火把
    synthesis_system.print_synthesis_path("torch", test_inventory)
    print()

    # 测试合成铁剑
    synthesis_system.print_synthesis_path("iron_sword", test_inventory)
    print()

    # 测试合成工作台
    synthesis_system.print_synthesis_path("crafting_table", test_inventory)
    print()

    # 测试建议路径
    print("优化建议:")
    print(synthesis_system.suggest_optimal_path("iron_sword", test_inventory))
    print()

    # 测试可用合成选项
    print("可用合成选项:")
    options = synthesis_system.get_available_synthesis_options(test_inventory)
    for item, recipes in options.items():
        print(f"  - {item}: 可直接合成")
    print()

    # 显示成本分析
    print("详细成本分析:")
    cost_analysis = synthesis_system.calculate_synthesis_cost("iron_pickaxe", test_inventory)
    print(json.dumps(cost_analysis, indent=2, ensure_ascii=False))