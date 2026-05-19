/**
 * 智能寻路到玩家身边 - 支持搭桥和爬升
 * 当普通寻路失败时，尝试使用方块搭建路径
 */

const { Vec3 } = require('vec3');

// 检查是否在坑里（被困在无法正常寻路的地方）
function isStuckInHole(bot) {
    const pos = bot.entity.position;
    const groundBlock = bot.blockAt(pos.offset(0, -1, 0));

    // 检查周围是否有足够的空间
    const surroundingBlocks = [
        bot.blockAt(pos.offset(1, 0, 0)),   // 东
        bot.blockAt(pos.offset(-1, 0, 0)),  // 西
        bot.blockAt(pos.offset(0, 0, 1)),   // 南
        bot.blockAt(pos.offset(0, 0, -1)),  // 北
    ];

    // 如果脚下是固体方块，但周围都被固体方块包围，则可能被困
    const isSurrounded = surroundingBlocks.every(block =>
        block && (block.boundingBox === 'block' || block.name !== 'air')
    );

    return isSurrounded && groundBlock && groundBlock.boundingBox === 'block';
}

// 检查是否在深坑中（Y坐标明显低于周围地面）
function isInDeepHole(bot) {
    const pos = bot.entity.position;
    const groundLevel = getGroundLevel(bot, pos);
    const surroundingGroundLevels = getSurroundingGroundLevels(bot, pos);

    // 计算周围地面的平均高度
    const avgGroundLevel = surroundingGroundLevels.length > 0
        ? surroundingGroundLevels.reduce((sum, level) => sum + level, 0) / surroundingGroundLevels.length
        : groundLevel;

    // 机器人当前位置比脚下地面和周围地面的平均值都低一定格数，才认为是深坑
    const depthFromBelow = groundLevel - Math.floor(pos.y);  // 从脚下地面算起的深度
    const depthFromAround = avgGroundLevel - Math.floor(pos.y);  // 从周围平均地面算起的深度

    // 只有当两个条件都满足时才认为是深坑
    return depthFromBelow > 5 && depthFromAround > 3;
}

// 获取周围区域的地面高度样本
function getSurroundingGroundLevels(bot, position, radius = 5) {
    const levels = [];
    const centerX = Math.floor(position.x);
    const centerZ = Math.floor(position.z);
    const centerY = Math.floor(position.y);

    for (let x = centerX - radius; x <= centerX + radius; x++) {
        for (let z = centerZ - radius; z <= centerZ + radius; z++) {
            // 只采样接近中心点的区域，避免过于偏离
            const distance = Math.sqrt(Math.pow(x - centerX, 2) + Math.pow(z - centerZ, 2));
            if (distance <= radius) {
                // 从当前位置高度开始向下搜索地面
                for (let y = Math.min(255, centerY + 10); y >= Math.max(0, centerY - 20); y--) {
                    const block = bot.blockAt(new Vec3(x, y, z));
                    if (block && block.boundingBox === 'block' && block.name !== 'air') {
                        levels.push(y + 1); // 固体方块的顶部作为地面
                        break;
                    }
                }
            }
        }
    }

    return levels;
}

// 获取当前位置的地面高度
function getGroundLevel(bot, position) {
    // 直接获取机器人正下方的第一个固体方块
    const posX = Math.floor(position.x);
    const posZ = Math.floor(position.z);

    // 从机器人脚下开始向下搜索
    let y = Math.floor(position.y) - 1;
    while (y >= 0) {
        const block = bot.blockAt(new Vec3(posX, y, posZ));
        if (block && block.boundingBox === 'block' && block.name !== 'air') {
            // 返回固体方块的顶部高度（y+1）
            return y + 1;
        }
        y--;
    }

    // 没找到地面，返回当前位置
    return Math.floor(position.y);
}

// 寻找合适的搭建材料（固体方块）
function findBuildingMaterial(bot) {
    const solidBlocks = [
        'dirt', 'stone', 'cobblestone', 'sandstone', 'wooden_planks',
        'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks',
        'acacia_planks', 'dark_oak_planks', 'mangrove_planks', 'cherry_planks',
        'bricks', 'netherrack', 'nether_bricks', 'end_stone', 'sand', 'gravel'
    ];

    const items = bot.inventory.items();
    for (const item of items) {
        if (solidBlocks.includes(item.name)) {
            return item;
        }
    }

    return null;
}

// 计算从当前位置到目标位置的直线路径上的可搭建点
async function calculateBuildPath(bot, targetPos) {
    const startPos = bot.entity.position;
    const path = [];

    // 计算方向向量
    const dx = targetPos.x - startPos.x;
    const dy = targetPos.y - startPos.y;
    const dz = targetPos.z - startPos.z;

    const distance = Math.sqrt(dx*dx + dy*dy + dz*dz);
    const steps = Math.max(1, Math.floor(distance));

    // 逐点计算路径
    for (let i = 1; i <= steps; i++) {
        const ratio = i / steps;
        const x = Math.floor(startPos.x + dx * ratio);
        const y = Math.floor(startPos.y + dy * ratio);
        const z = Math.floor(startPos.z + dz * ratio);

        const blockPos = new Vec3(x, y, z);
        const block = bot.blockAt(blockPos);

        // 如果该位置是空气，可以放置方块
        if (!block || block.name === 'air') {
            path.push(blockPos);
        }
    }

    return path;
}

// 搭建垂直梯子（向上爬升）
async function buildLadder(bot, targetHeight) {
    console.log('[智能寻路] 开始建梯子...');

    const material = findBuildingMaterial(bot);
    if (!material) {
        throw new Error('没有可用的搭建材料');
    }

    await bot.equip(material, 'hand');

    const pos = bot.entity.position;
    const currentY = Math.floor(pos.y);

    // 从当前位置向上建造到目标高度
    for (let y = currentY + 1; y <= targetHeight; y++) {
        try {
            const blockPos = new Vec3(Math.floor(pos.x), y, Math.floor(pos.z));
            const blockBelow = bot.blockAt(blockPos.offset(0, -1, 0));

            if (blockBelow && blockBelow.boundingBox === 'block') {
                await bot.placeBlock(blockBelow, new Vec3(0, 1, 0));
                console.log(`[智能寻路] 在 (${blockPos.x}, ${y}, ${blockPos.z}) 放置方块`);
                await new Promise(resolve => setTimeout(resolve, 300));
            }
        } catch (e) {
            console.log(`[智能寻路] 在高度 ${y} 放置方块失败: ${e.message}`);
        }
    }

    return true;
}

// 搭建水平桥梁
async function buildBridge(bot, targetPos) {
    console.log('[智能寻路] 开始建桥...');

    const material = findBuildingMaterial(bot);
    if (!material) {
        throw new Error('没有可用的搭建材料');
    }

    await bot.equip(material, 'hand');

    const startPos = bot.entity.position;
    const direction = new Vec3(
        Math.sign(targetPos.x - startPos.x),
        0,
        Math.sign(targetPos.z - startPos.z)
    );

    const distance = Math.max(
        Math.abs(targetPos.x - startPos.x),
        Math.abs(targetPos.z - startPos.z)
    );

    // 沿着方向建造桥梁
    for (let i = 1; i <= distance; i++) {
        try {
            const x = Math.floor(startPos.x + direction.x * i);
            const z = Math.floor(startPos.z + direction.z * i);
            const y = Math.floor(startPos.y - 1); // 放在脚下

            const blockPos = new Vec3(x, y, z);
            const blockBelow = bot.blockAt(blockPos.offset(0, -1, 0));

            if (blockBelow && blockBelow.boundingBox === 'block') {
                await bot.placeBlock(blockBelow, new Vec3(0, 1, 0));
                console.log(`[智能寻路] 在 (${x}, ${y + 1}, ${z}) 放置方块`);
                await new Promise(resolve => setTimeout(resolve, 300));
            }
        } catch (e) {
            console.log(`[智能寻路] 建桥失败 at step ${i}: ${e.message}`);
        }
    }

    return true;
}

// 搭建方块路径
async function buildPathToTarget(bot, targetPos) {
    console.log('[智能寻路] 检测到可能被困，尝试搭建路径...');

    // 寻找搭建材料
    const material = findBuildingMaterial(bot);
    if (!material) {
        throw new Error('没有可用的搭建材料');
    }

    // 装备材料
    await bot.equip(material, 'hand');

    // 计算搭建路径
    const buildPositions = await calculateBuildPath(bot, targetPos);

    if (buildPositions.length === 0) {
        throw new Error('无法计算搭建路径');
    }

    console.log(`[智能寻路] 准备搭建 ${buildPositions.length} 个方块`);

    // 逐个放置方块
    for (const pos of buildPositions) {
        try {
            // 寻找相邻的固体方块作为放置参考
            const adjacentPositions = [
                pos.offset(0, -1, 0),  // 下方
                pos.offset(0, 1, 0),   // 上方
                pos.offset(1, 0, 0),   // 东方
                pos.offset(-1, 0, 0),  // 西方
                pos.offset(0, 0, 1),   // 南方
                pos.offset(0, 0, -1),  // 北方
            ];

            let referenceBlock = null;
            let faceVector = null;

            for (const adjPos of adjacentPositions) {
                const adjBlock = bot.blockAt(adjPos);
                if (adjBlock && adjBlock.boundingBox === 'block' && adjBlock.name !== 'air') {
                    referenceBlock = adjBlock;
                    faceVector = pos.minus(adjPos);
                    break;
                }
            }

            if (referenceBlock && faceVector) {
                await bot.placeBlock(referenceBlock, faceVector);
                console.log(`[智能寻路] 在 (${pos.x}, ${pos.y}, ${pos.z}) 放置方块`);
                await new Promise(resolve => setTimeout(resolve, 300)); // 短暂延迟
            }
        } catch (e) {
            console.log(`[智能寻路] 放置方块失败 (${pos.x}, ${pos.y}, ${pos.z}): ${e.message}`);
            // 继续尝试下一个位置
        }
    }

    return true;
}

// 获取寻路配置（需要传入bot）
function getMovements(bot) {
    const { Movements } = require('mineflayer-pathfinder');
    const moves = new Movements(bot);
    moves.canDig = true;
    moves.allow1by1towers = true;
    moves.maxDropDown = 4;
    return moves;
}

// 增强版走到玩家身边功能
async function smartGotoPlayer(bot) {
    // 重新获取pathfinder模块，避免可能的作用域问题
    const { pathfinder, goals } = require('mineflayer-pathfinder');

    // 获取最近的玩家
    const player = bot.nearestEntity(entity => {
        return entity.type === 'player' && entity.username !== bot.username;
    });

    if (!player) {
        throw new Error('附近没有玩家');
    }

    const targetPos = player.position;
    const startPos = bot.entity.position;

    console.log(`[智能寻路] 从 (${startPos.x.toFixed(1)}, ${startPos.y.toFixed(1)}, ${startPos.z.toFixed(1)}) 移动到玩家位置 (${targetPos.x.toFixed(1)}, ${targetPos.y.toFixed(1)}, ${targetPos.z.toFixed(1)})`);

    // 首先尝试正常寻路
    try {
        bot.pathfinder.setMovements(getMovements(bot));

        const timeout = new Promise((_, reject) =>
            setTimeout(() => reject(new Error('寻路超时')), 20000)
        );

        const navigate = bot.pathfinder.goto(new goals.GoalNear(targetPos.x, targetPos.y, targetPos.z, 2));

        await Promise.race([navigate, timeout]);
        console.log('[智能寻路] 正常寻路成功');
        return { status: 'success', method: 'normal' };
    } catch (normalPathError) {
        console.log('[智能寻路] 正常寻路失败，尝试智能解决方案...');

        // 检查各种困境情况
        const isStuck = isStuckInHole(bot);
        const isDeepHole = isInDeepHole(bot);

        console.log(`[诊断] 困境检测 - 被困: ${isStuck}, 深坑: ${isDeepHole}, 当前Y=${startPos.y}, 地面Y=${getGroundLevel(bot, startPos)}`);

        // 如果被困在深坑中，先建梯子
        if (isDeepHole) {
            try {
                console.log('[智能寻路] 检测到深坑，开始建梯子...');
                const groundLevel = getGroundLevel(bot, startPos);
                await buildLadder(bot, groundLevel);

                // 建完梯子后再尝试寻路
                bot.pathfinder.setMovements(getMovements(bot));
                const ladderPath = bot.pathfinder.goto(new goals.GoalNear(targetPos.x, targetPos.y, targetPos.z, 2));
                await Promise.race([ladderPath, timeout]);

                console.log('[智能寻路] 建梯子后寻路成功');
                return { status: 'success', method: 'build_ladder' };
            } catch (ladderError) {
                console.log(`[智能寻路] 建梯子失败: ${ladderError.message}`);
            }
        }

        // 如果被困，尝试搭建路径
        if (isStuck) {
            try {
                // 尝试搭建路径
                await buildPathToTarget(bot, targetPos);

                // 搭建完成后再次尝试寻路
                bot.pathfinder.setMovements(getMovements(bot));
                const secondAttempt = bot.pathfinder.goto(new goals.GoalNear(targetPos.x, targetPos.y, targetPos.z, 2));
                await Promise.race([secondAttempt, timeout]);

                console.log('[智能寻路] 搭建路径后寻路成功');
                return { status: 'success', method: 'build_path' };
            } catch (buildError) {
                console.log(`[智能寻路] 搭建路径失败: ${buildError.message}`);
            }
        }

        // 如果在同一水平面但有障碍，尝试建桥
        const horizontalDistance = Math.sqrt(
            Math.pow(targetPos.x - startPos.x, 2) +
            Math.pow(targetPos.z - startPos.z, 2)
        );

        const heightDifference = Math.abs(targetPos.y - startPos.y);

        if (horizontalDistance > 3 && heightDifference < 2) {
            try {
                console.log('[智能寻路] 检测到需要建桥，开始建造...');
                await buildBridge(bot, targetPos);

                // 建桥完成后再次尝试寻路
                bot.pathfinder.setMovements(getMovements(bot));
                const bridgePath = bot.pathfinder.goto(new goals.GoalNear(targetPos.x, targetPos.y, targetPos.z, 2));
                await Promise.race([bridgePath, timeout]);

                console.log('[智能寻路] 建桥后寻路成功');
                return { status: 'success', method: 'build_bridge' };
            } catch (bridgeError) {
                console.log(`[智能寻路] 建桥失败: ${bridgeError.message}`);
            }
        }

        // 如果所有方法都失败，抛出原始错误
        throw normalPathError;
    }
}

// 获取周围区域的地面高度样本
function getSurroundingGroundLevels(bot, position, radius = 5) {
    const levels = [];
    const centerX = Math.floor(position.x);
    const centerZ = Math.floor(position.z);
    const centerY = Math.floor(position.y);

    for (let x = centerX - radius; x <= centerX + radius; x++) {
        for (let z = centerZ - radius; z <= centerZ + radius; z++) {
            // 只采样接近中心点的区域，避免过于偏离
            const distance = Math.sqrt(Math.pow(x - centerX, 2) + Math.pow(z - centerZ, 2));
            if (distance <= radius) {
                // 从当前位置高度开始向下搜索地面
                for (let y = Math.min(255, centerY + 10); y >= Math.max(0, centerY - 20); y--) {
                    const block = bot.blockAt(new Vec3(x, y, z));
                    if (block && block.boundingBox === 'block' && block.name !== 'air') {
                        levels.push(y + 1); // 固体方块的顶部作为地面
                        break;
                    }
                }
            }
        }
    }

    return levels;
}

// 导出智能寻路函数
module.exports = {
    smartGotoPlayer,
    isStuckInHole,
    isInDeepHole,
    findBuildingMaterial,
    buildPathToTarget,
    buildLadder,
    buildBridge,
    getGroundLevel,
    getSurroundingGroundLevels,
    getMovements
};