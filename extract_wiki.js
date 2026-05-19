const mcData = require('minecraft-data')('1.21.1');
const fs = require('fs');

const allData = [];

// 1. 方块数据
console.log('提取方块数据...');
const blocks = mcData.blocksArray;
for (const block of blocks) {
    allData.push({
        type: 'block',
        name: block.name,
        text: `方块: ${block.displayName || block.name}。ID: ${block.id}。硬度: ${block.hardness ?? '未知'}。可堆叠: ${block.stackSize || 64}。挖掘等级: ${block.material || '未知'}。发光: ${block.emitLight || 0}。`
    });
}
console.log(`  → ${blocks.length} 个方块`);

// 2. 物品数据
console.log('提取物品数据...');
const items = mcData.itemsArray;
for (const item of items) {
    allData.push({
        type: 'item',
        name: item.name,
        text: `物品: ${item.displayName || item.name}。ID: ${item.id}。可堆叠数量: ${item.stackSize || 64}。`
    });
}
console.log(`  → ${items.length} 个物品`);

// 3. 生物数据
console.log('提取生物数据...');
const entities = mcData.entitiesArray;
for (const entity of entities) {
    allData.push({
        type: 'entity',
        name: entity.name,
        text: `生物: ${entity.displayName || entity.name}。类型: ${entity.type || '未知'}。分类: ${entity.category || '未知'}。`
    });
}
console.log(`  → ${entities.length} 个生物`);

// 4. 合成配方
console.log('提取合成配方...');
const recipes = mcData.recipes;
let recipeCount = 0;
for (const [itemId, recipeList] of Object.entries(recipes)) {
    const itemInfo = mcData.items[itemId];
    const itemName = itemInfo ? (itemInfo.displayName || itemInfo.name) : itemId;

    for (const recipe of recipeList) {
        let ingredients = '';
        if (recipe.ingredients) {
            ingredients = recipe.ingredients
                .filter(i => i !== null)
                .map(i => {
                    const info = mcData.items[i] || mcData.items[String(i)];
                    return info ? info.displayName || info.name : String(i);
                }).join(', ');
        } else if (recipe.inShape) {
            const flat = recipe.inShape.flat().filter(i => i !== null);
            ingredients = [...new Set(flat.map(i => {
                const info = mcData.items[i] || mcData.items[String(i)];
                return info ? info.displayName || info.name : String(i);
            }))].join(', ');
        }

        allData.push({
            type: 'recipe',
            name: itemName,
            text: `合成 ${itemName} 需要: ${ingredients || '未知材料'}。`
        });
        recipeCount++;
    }
}
console.log(`  → ${recipeCount} 个配方`);

// 5. 生物群系
console.log('提取生物群系...');
const biomes = mcData.biomesArray;
for (const biome of biomes) {
    allData.push({
        type: 'biome',
        name: biome.name,
        text: `生物群系: ${biome.displayName || biome.name}。温度: ${biome.temperature ?? '未知'}。降水: ${biome.rainfall ?? '未知'}。`
    });
}
console.log(`  → ${biomes.length} 个生物群系`);

// 6. 食物数据
console.log('提取食物数据...');
const foods = mcData.foodsArray;
if (foods) {
    for (const food of foods) {
        const itemInfo = mcData.items[food.id];
        const name = itemInfo ? (itemInfo.displayName || itemInfo.name) : String(food.id);
        allData.push({
            type: 'food',
            name: name,
            text: `食物: ${name}。恢复饥饿值: ${food.foodPoints || '未知'}。饱和度: ${food.saturation || '未知'}。`
        });
    }
    console.log(`  → ${foods.length} 个食物`);
}

// 保存
fs.writeFileSync('wiki_data.json', JSON.stringify(allData, null, 2), 'utf-8');
console.log(`\n总共提取 ${allData.length} 条数据，已保存到 wiki_data.json`);