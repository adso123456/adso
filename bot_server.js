const mineflayer = require('mineflayer');
const express = require('express');
const pathfinder = require('mineflayer-pathfinder');
const { Vec3 } = require('vec3');

// ========== 自动重连配置 ==========
const RECONNECT_CONFIG = {
    enabled: true,
    maxRetries: 10,          // 最大重试次数
    baseDelay: 3000,         // 基础延迟 3秒
    maxDelay: 60000,         // 最大延迟 60秒
    backoffMultiplier: 2,    // 每次延迟翻倍
};

let reconnectState = {
    retryCount: 0,
    lastPort: 25565,
    lastUsername: 'AIBot',
    isReconnecting: false,
    reconnectTimer: null,
};

// ========== 自动拾取配置 ==========

const autoPickupState = {
    enabled: true,
    pickupRadius: 10,      // 拾取范围
    checkInterval: null,    // 定时检查器
    isPickingUp: false,     // 是否正在拾取
    cooldownMs: 2000,       // 检查间隔
    lastPickupTime: 0,
};

function startAutoPickup() {
    if (autoPickupState.checkInterval) return;

    autoPickupState.checkInterval = setInterval(async () => {
        if (!bot || !autoPickupState.enabled || autoPickupState.isPickingUp) return;

        // 如果正在寻路中，不打断
        if (bot.pathfinder.isMoving()) return;

        await pickupNearbyItems();
    }, autoPickupState.cooldownMs);

    console.log('✓ 自动拾取已启动');
}

function stopAutoPickup() {
    if (autoPickupState.checkInterval) {
        clearInterval(autoPickupState.checkInterval);
        autoPickupState.checkInterval = null;
    }
}

// 记录重要游戏事件到 Python 服务
async function reportEvent(event, details) {
    try {
        await fetch('http://localhost:8000/bot_event', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ event, details })
        });
    } catch (e) {
        // Python 服务没启动就忽略
    }
}

async function pickupNearbyItems(maxItems = 10) {
    if (!bot || autoPickupState.isPickingUp) return 0;

    autoPickupState.isPickingUp = true;
    let collected = 0;

    try {
        // 找附近所有掉落物实体
        const items = Object.values(bot.entities).filter(entity => {
            if (entity.name !== 'item') return false;
            const dist = entity.position.distanceTo(bot.entity.position);
            return dist <= autoPickupState.pickupRadius;
        });

        if (items.length === 0) {
            autoPickupState.isPickingUp = false;
            return 0;
        }

        // 按距离排序，先捡近的
        items.sort((a, b) => {
            return a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position);
        });

        // 最多捡 maxItems 个
        const toCollect = items.slice(0, maxItems);

        for (const item of toCollect) {
            // 检查实体是否还存在
            if (!bot.entities[item.id]) continue;

            const dist = item.position.distanceTo(bot.entity.position);

            if (dist <= 2.5) {
                // 很近的直接等它被吸过来
                await new Promise(r => setTimeout(r, 300));
                collected++;
            } else {
                // 需要走过去捡
                try {
                    const { goals } = pathfinder;
                    bot.pathfinder.setMovements(getMovements());

                    const timeout = new Promise((_, reject) =>
                        setTimeout(() => reject('拾取超时'), 5000)
                    );
                    const navigate = bot.pathfinder.goto(
                        new goals.GoalNear(item.position.x, item.position.y, item.position.z, 1)
                    );

                    await Promise.race([navigate, timeout]);
                    await new Promise(r => setTimeout(r, 300));
                    collected++;
                } catch (e) {
                    // 走不到就跳过这个物品
                    continue;
                }
            }
        }

        if (collected > 0) {
            console.log(`[拾取] 捡起了 ${collected} 个掉落物`);
        }

    } catch (e) {
        console.error('[拾取] 错误:', e.message);
    } finally {
        autoPickupState.isPickingUp = false;
    }

    return collected;
}

// ========== 自动装备最佳工具 ==========

// 工具等级排序（越后面越好）
const TOOL_TIERS = ['wooden', 'stone', 'iron', 'golden', 'diamond', 'netherite'];

// 方块类型 → 最佳工具类型的映射
const BLOCK_TOOL_MAP = {
    // 用斧头的
    axe: ['log', 'wood', 'plank', 'fence', 'gate', 'sign', 'door', 'trapdoor',
          'chest', 'barrel', 'crafting_table', 'bookshelf', 'ladder', 'bamboo',
          'mushroom_block', 'pumpkin', 'melon'],
    // 用镐子的
    pickaxe: ['stone', 'cobblestone', 'ore', 'deepslate', 'granite', 'diorite',
              'andesite', 'obsidian', 'netherrack', 'basalt', 'blackstone',
              'brick', 'terracotta', 'concrete', 'prismarine', 'purpur',
              'furnace', 'anvil', 'iron_block', 'gold_block', 'diamond_block',
              'emerald_block', 'rail', 'lantern', 'chain', 'iron_door',
              'iron_bars', 'brewing_stand', 'cauldron', 'hopper'],
    // 用铲子的
    shovel: ['dirt', 'grass_block', 'sand', 'gravel', 'clay', 'soul_sand',
             'soul_soil', 'mycelium', 'podzol', 'mud', 'snow', 'snow_block',
             'farmland', 'dirt_path', 'rooted_dirt'],
    // 用锄头的
    hoe: ['hay_block', 'target', 'dried_kelp_block', 'sponge', 'wet_sponge',
          'nether_wart_block', 'warped_wart_block', 'shroomlight',
          'moss_block', 'sculk', 'leaves'],
    // 用剑的（主要是战斗，但也能快速破坏这些）
    sword: ['cobweb', 'bamboo'],
};

function getToolTypeForBlock(blockName) {
    // 根据方块名判断需要哪种工具
    for (const [toolType, keywords] of Object.entries(BLOCK_TOOL_MAP)) {
        for (const keyword of keywords) {
            if (blockName.includes(keyword)) {
                return toolType;
            }
        }
    }
    return null; // 不需要特定工具，用手就行
}

function getToolTier(itemName) {
    // 获取工具的等级，返回数字越大越好
    for (let i = 0; i < TOOL_TIERS.length; i++) {
        if (itemName.startsWith(TOOL_TIERS[i])) {
            return i;
        }
    }
    return -1;
}

function findBestTool(toolType) {
    // 在背包里找指定类型的最佳工具
    if (!bot) return null;

    const items = bot.inventory.items();
    let bestItem = null;
    let bestTier = -1;

    for (const item of items) {
        // 检查是否是对应类型的工具
        if (item.name.includes(toolType)) {
            const tier = getToolTier(item.name);
            if (tier > bestTier) {
                bestTier = tier;
                bestItem = item;
            }
        }
    }

    return bestItem;
}

async function equipBestToolForBlock(blockName) {
    // 根据方块类型自动装备最佳工具
    if (!bot) return null;

    const toolType = getToolTypeForBlock(blockName);
    if (!toolType) return null; // 不需要工具

    const bestTool = findBestTool(toolType);
    if (!bestTool) return null; // 背包里没有对应工具

    // 检查当前手持是否已经是最佳工具
    const heldItem = bot.heldItem;
    if (heldItem && heldItem.name === bestTool.name) {
        return bestTool; // 已经拿着了
    }

    try {
        await bot.equip(bestTool, 'hand');
        console.log(`[装备] 自动切换到 ${bestTool.name}`);
        return bestTool;
    } catch (e) {
        console.error(`[装备] 切换失败: ${e.message}`);
        return null;
    }
}

// 战斗时自动装备最佳武器
async function equipBestWeapon() {
    if (!bot) return null;

    const items = bot.inventory.items();
    let bestWeapon = null;
    let bestScore = -1;

    // 武器优先级：剑 > 斧 > 其他
    const weaponScores = {
        'netherite_sword': 100, 'diamond_sword': 90, 'iron_sword': 80,
        'golden_sword': 70, 'stone_sword': 60, 'wooden_sword': 50,
        'netherite_axe': 95, 'diamond_axe': 85, 'iron_axe': 75,
        'golden_axe': 65, 'stone_axe': 55, 'wooden_axe': 45,
        'trident': 92,
    };

    for (const item of items) {
        const score = weaponScores[item.name] || 0;
        if (score > bestScore) {
            bestScore = score;
            bestWeapon = item;
        }
    }

    if (bestWeapon && bestScore > 0) {
        const heldItem = bot.heldItem;
        if (heldItem && heldItem.name === bestWeapon.name) return bestWeapon;

        try {
            await bot.equip(bestWeapon, 'hand');
            console.log(`[装备] 自动切换武器 ${bestWeapon.name}`);
            return bestWeapon;
        } catch (e) {
            return null;
        }
    }
    return null;
}

// 正确导入插件
let pvp, collectBlock, autoEat;
try {
    pvp = require('mineflayer-pvp').pvp;
} catch (e) {
    console.warn('mineflayer-pvp 未安装或加载失败');
    pvp = null;
}

try {
    collectBlock = require('mineflayer-collectblock').plugin;
} catch (e) {
    console.warn('mineflayer-collectblock 未安装或加载失败');
    collectBlock = null;
}

try {
    autoEat = require('mineflayer-auto-eat').plugin;
} catch (e) {
    console.warn('mineflayer-auto-eat 未安装或加载失败');
    autoEat = null;
}

const app = express();
app.use(express.json());

let bot = null;
let isAutoReplyEnabled = false;
let lastChatMessages = [];

// ========== 创建 Bot ==========

function createBot(username = 'AIBot', port = 25565) {
    // 清理旧连接
    if (reconnectState.reconnectTimer) {
        clearTimeout(reconnectState.reconnectTimer);
        reconnectState.reconnectTimer = null;
    }

    if (bot) {
        try {
            bot.removeAllListeners();
            bot.quit();
        } catch (e) {}
        bot = null;
    }

    // 记住连接参数
    reconnectState.lastPort = port;
    reconnectState.lastUsername = username;

    console.log(`[连接] 正在连接到 localhost:${port}，用户名: ${username}`);

    bot = mineflayer.createBot({
        host: 'localhost',
        port: port,
        username: username,
        auth: 'offline'
    });

    // 加载插件
    bot.loadPlugin(pathfinder.pathfinder);

    if (collectBlock && typeof collectBlock === 'function') {
        try {
            bot.loadPlugin(collectBlock);
            console.log('✓ CollectBlock 插件已加载');
        } catch (e) {}
    }

    // ===== 连接成功 =====
    bot.on('login', () => {
        console.log(`✓ Bot 已登录: ${bot.username}`);
        console.log(`  位置: ${bot.entity.position.x.toFixed(2)}, ${bot.entity.position.y.toFixed(2)}, ${bot.entity.position.z.toFixed(2)}`);
        // 连接成功，重置重试计数
        reconnectState.retryCount = 0;
        reconnectState.isReconnecting = false;
    });

    bot.on('spawn', () => {
        console.log('✓ Bot 已生成在世界中');
        startAutoPickup();
    });

    // Bot 死亡
    bot.on('death', () => {
        console.log('☠ Bot 死亡');
        reportEvent('death', {
            position: bot.entity.position,
            message: 'Bot死亡了'
        });
    });

    // 生命值变化（受伤时记录）
    bot.on('health', () => {
        if (bot.health < 8) {
            reportEvent('low_health', {
                health: bot.health,
                food: bot.food,
                position: bot.entity.position,
                message: `生命值过低: ${bot.health}`
            });
        }
    });

    // 下雨
    bot.on('rain', () => {
        reportEvent('weather', {
            raining: bot.isRaining,
            position: bot.entity.position
        });
    });

    // ===== 监听聊天 =====
    bot.on('chat', async (username, message) => {
        if (username === bot.username) return;

        console.log(`[聊天] ${username}: ${message}`);

        lastChatMessages.push({
            username: username,
            message: message,
            timestamp: Date.now()
        });
        if (lastChatMessages.length > 50) lastChatMessages.shift();

        try {
            const response = await fetch('http://localhost:8000/game_chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: username,
                    message: message,
                    bot_name: bot.username
                })
            });

            const data = await response.json();

            if (data.reply && data.reply.trim()) {
                setTimeout(() => {
                    if (!bot) {
                        console.log('[警告] 机器人已断开连接，无法发送回复');
                        return;
                    }
                    try {
                        bot.chat(data.reply);
                        console.log(`[回复] ${bot.username}: ${data.reply}`);
                    } catch (chatError) {
                        console.error('[聊天错误] 发送聊天消息失败:', chatError.message);
                    }
                }, 800 + Math.random() * 1200);
            }
        } catch (error) {
            if (error.code !== 'ECONNREFUSED') {
                console.error('聊天处理失败:', error.message);
            }
        }
    });

    // ===== 被踢出 =====
    bot.on('kicked', (reason) => {
        let reasonText = reason;
        try {
            const parsed = JSON.parse(reason);
            reasonText = parsed.text || parsed.translate || reason;
        } catch (e) {}

        console.log(`⚠ Bot 被踢出: ${reasonText}`);

        // 被踢出也尝试重连（除非是被ban）
        if (reasonText.includes('banned')) {
            console.log('✗ 被封禁，不再重连');
            return;
        }
        scheduleReconnect('kicked');
    });

    // ===== 连接错误 =====
    bot.on('error', (err) => {
        console.error(`❌ Bot 错误: ${err.message}`);
        // 不在这里重连，等 end 事件
    });

    // ===== 连接断开 =====
    bot.on('end', (reason) => {
        console.log(`⚠ Bot 连接断开: ${reason || '未知原因'}`);
        stopAutoPickup();
        bot = null;
        scheduleReconnect(reason || 'disconnected');
    });

    return bot;
}


// ========== 自动重连调度 ==========

function scheduleReconnect(reason) {
    if (!RECONNECT_CONFIG.enabled) {
        console.log('[重连] 自动重连已禁用');
        return;
    }

    if (reconnectState.isReconnecting) {
        console.log('[重连] 已在重连中，跳过');
        return;
    }

    if (reconnectState.retryCount >= RECONNECT_CONFIG.maxRetries) {
        console.log(`✗ 已达最大重试次数 (${RECONNECT_CONFIG.maxRetries})，停止重连`);
        console.log('  可以通过 POST /connect 手动重新连接');
        reconnectState.retryCount = 0;
        return;
    }

    reconnectState.isReconnecting = true;
    reconnectState.retryCount++;

    // 指数退避计算延迟
    const delay = Math.min(
        RECONNECT_CONFIG.baseDelay * Math.pow(RECONNECT_CONFIG.backoffMultiplier, reconnectState.retryCount - 1),
        RECONNECT_CONFIG.maxDelay
    );

    console.log(`[重连] 第 ${reconnectState.retryCount}/${RECONNECT_CONFIG.maxRetries} 次重试，${(delay / 1000).toFixed(1)}秒后重连...`);
    console.log(`  原因: ${reason}`);
    console.log(`  延迟策略: ${RECONNECT_CONFIG.baseDelay}ms × ${RECONNECT_CONFIG.backoffMultiplier}^${reconnectState.retryCount - 1} = ${delay}ms`);

    reconnectState.reconnectTimer = setTimeout(() => {
        reconnectState.isReconnecting = false;
        console.log(`[重连] 正在尝试重新连接...`);

        try {
            createBot(reconnectState.lastUsername, reconnectState.lastPort);
        } catch (e) {
            console.error(`[重连] 重连失败: ${e.message}`);
            scheduleReconnect('reconnect_failed');
        }
    }, delay);
}
// 公共寻路配置
function getMovements() {
    const { Movements } = pathfinder;
    const moves = new Movements(bot);
    moves.canDig = true;
    moves.allow1by1towers = true;
    moves.maxDropDown = 4;
    return moves;
}
// 清理周围挡路的竹子和植物
// ========== 清障系统（带冷却和缓存） ==========

const clearObstaclesState = {
    lastClearTime: 0,
    lastClearPos: null,
    cooldownMs: 5000,        // 冷却时间 5秒
    minDistanceToReClear: 8, // 移动超过8格才重新清理
    isClearing: false,
};

async function clearNearbyObstacles(radius = 3, force = false) {
    if (!bot) return;

    const now = Date.now();
    const pos = bot.entity.position;

    // 如果正在清理，跳过
    if (clearObstaclesState.isClearing) {
        return;
    }

    // 非强制模式下，检查冷却和距离
    if (!force) {
        const timeSinceLastClear = now - clearObstaclesState.lastClearTime;

        // 冷却时间内跳过
        if (timeSinceLastClear < clearObstaclesState.cooldownMs) {
            return;
        }

        // 位置没怎么变也跳过
        if (clearObstaclesState.lastClearPos) {
            const dist = pos.distanceTo(clearObstaclesState.lastClearPos);
            if (dist < clearObstaclesState.minDistanceToReClear) {
                return;
            }
        }
    }

    clearObstaclesState.isClearing = true;
    clearObstaclesState.lastClearTime = now;
    clearObstaclesState.lastClearPos = pos.clone();

    const clearNames = ['bamboo', 'sugar_cane', 'tall_grass', 'large_fern', 'tall_seagrass'];
    let cleared = 0;

    try {
        for (let x = -radius; x <= radius; x++) {
            for (let z = -radius; z <= radius; z++) {
                for (let y = -1; y <= 3; y++) {
                    const block = bot.blockAt(new Vec3(
                        Math.floor(pos.x) + x,
                        Math.floor(pos.y) + y,
                        Math.floor(pos.z) + z
                    ));
                    if (block && clearNames.includes(block.name)) {
                        try {
                            await bot.dig(block);
                            cleared++;
                        } catch (e) {}
                    }
                }
            }
        }
    } finally {
        clearObstaclesState.isClearing = false;
    }

    if (cleared > 0) {
        console.log(`[清障] 清理了 ${cleared} 个障碍物`);
    }
}
// ===== 处理接收到的聊天消息 =====

async function handleIncomingChat(username, message) {
    try {
        const response = await fetch('http://localhost:8000/chat_reply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username: username,
                message: message,
                bot_name: bot.username
            })
        });

        const data = await response.json();
        
        if (data.reply && data.reply.trim()) {
            setTimeout(() => {
                if (!bot) return;
                bot.chat(data.reply);
                console.log(`[自动回复] ${bot.username}: ${data.reply}`);
            }, 1000 + Math.random() * 2000);
        }
    } catch (error) {
        console.error('自动回复失败:', error);
    }
}

// ========== API 路由 ==========

// 连接 Bot
app.post('/connect', (req, res) => {
    try {
        // 如果已经连接且在线，不重复连接
        if (bot && bot.entity) {
            return res.json({ status: 'already_connected', username: bot.username });
        }

        const port = req.body.port || 25565;
        reconnectState.retryCount = 0;
        reconnectState.isReconnecting = false;
        if (reconnectState.reconnectTimer) {
            clearTimeout(reconnectState.reconnectTimer);
            reconnectState.reconnectTimer = null;
        }
        createBot('AIBot', port);
        res.json({ status: 'connecting', port: port });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// 查看重连状态
app.get('/reconnect_status', (req, res) => {
    res.json({
        enabled: RECONNECT_CONFIG.enabled,
        retryCount: reconnectState.retryCount,
        maxRetries: RECONNECT_CONFIG.maxRetries,
        isReconnecting: reconnectState.isReconnecting,
        botConnected: bot !== null
    });
});

// 手动开关自动重连
app.post('/reconnect_toggle', (req, res) => {
    RECONNECT_CONFIG.enabled = !RECONNECT_CONFIG.enabled;

    if (!RECONNECT_CONFIG.enabled && reconnectState.reconnectTimer) {
        clearTimeout(reconnectState.reconnectTimer);
        reconnectState.reconnectTimer = null;
        reconnectState.isReconnecting = false;
    }

    res.json({
        enabled: RECONNECT_CONFIG.enabled,
        message: RECONNECT_CONFIG.enabled ? '自动重连已开启' : '自动重连已关闭'
    });
});

// 手动停止重连
app.post('/reconnect_stop', (req, res) => {
    if (reconnectState.reconnectTimer) {
        clearTimeout(reconnectState.reconnectTimer);
        reconnectState.reconnectTimer = null;
    }
    reconnectState.isReconnecting = false;
    reconnectState.retryCount = 0;
    res.json({ status: 'stopped', message: '已停止自动重连' });
});


// 获取状态
app.get('/status', (req, res) => {
    if (!bot || !bot.entity) {
        return res.json({ connected: false, message: 'Bot 未就绪' });
    }

    res.json({
        connected: true,
        username: bot.username,
        position: bot.entity.position,
        health: bot.health,
        food: bot.food,
        inventory: bot.inventory.items().map(item => ({
            name: item.name,
            count: item.count
        }))
    });
});

// 移动
app.post('/goto', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    const { x, y, z } = req.body;
    
    try {
        // 先清理周围挡路的竹子
        await clearNearbyObstacles(5, true);

        const { goals } = pathfinder;
        bot.pathfinder.setMovements(getMovements());

        // 设置超时，防止卡死
        const timeout = new Promise((_, reject) =>
            setTimeout(() => reject(new Error('寻路超时')), 30000)
        );

        const navigate = bot.pathfinder.goto(new goals.GoalNear(x, y, z, 2));

        await Promise.race([navigate, timeout]);
        res.json({ status: 'arrived', position: bot.entity.position });
    } catch (e) {
        // 寻路失败时，尝试tp（如果有权限）
        console.error('寻路失败:', e.message);

        // 停止当前寻路
        bot.pathfinder.setGoal(null);

        res.json({
            status: 'path_failed',
            error: e.message,
            position: bot.entity.position,
            suggestion: '可以用 /tp 命令直接传送'
        });
    }
});

// 发送聊天消息
app.post('/chat', (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const { message } = req.body;

    try {
        if (!bot.connected) {
            return res.status(400).json({ error: '机器人未连接' });
        }
        bot.chat(message);
        res.json({ status: 'sent', message: message });
    } catch (error) {
        console.error('发送聊天消息失败:', error.message);
        res.status(500).json({ error: '发送失败: ' + error.message });
    }
});

// 执行命令
app.post('/command', (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    const { command } = req.body;

    // 只允许 /tp 命令
    const allowedCommands = ['/tp'];
    const isAllowed = allowedCommands.some(cmd => command.trim().startsWith(cmd));

    if (!isAllowed) {
        return res.json({
            error: `禁止执行该命令，只允许: ${allowedCommands.join(', ')}`,
            blocked: command
        });
    }

    bot.chat(command);
    res.json({ status: 'executed', command: command });
});

// 查找方块
app.post('/find_block', (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    const { name, distance = 64 } = req.body;
    const block = bot.findBlock({
        matching: bot.registry.blocksByName[name]?.id,
        maxDistance: distance
    });
    
    if (block) {
        res.json({ found: true, position: block.position });
    } else {
        res.json({ found: false, message: `未找到 ${name}` });
    }
});

// 砍树
app.post('/chop_tree', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    try {
        // 先清理周围
        await clearNearbyObstacles(5, true);

        const logNames = ['oak_log', 'birch_log', 'spruce_log', 'jungle_log',
                         'acacia_log', 'dark_oak_log', 'mangrove_log', 'cherry_log'];

        let targetBlock = null;

        for (const logName of logNames) {
            const blockId = bot.registry.blocksByName[logName]?.id;
            if (blockId) {
                const found = bot.findBlock({
                    matching: blockId,
                    maxDistance: 32
                });
                if (found) {
                    targetBlock = found;
                    break;
                }
            }
        }

        if (!targetBlock) {
            return res.json({ status: 'no_tree_found', message: '附近没有找到树' });
        }

        // 寻路到树旁边（带超时）
        const { goals } = pathfinder;
        bot.pathfinder.setMovements(getMovements());

        try {
            const timeout = new Promise((_, reject) =>
                setTimeout(() => reject(new Error('寻路超时')), 20000)
            );
            const navigate = bot.pathfinder.goto(
                new goals.GoalNear(targetBlock.position.x, targetBlock.position.y, targetBlock.position.z, 2)
            );
            await Promise.race([navigate, timeout]);
        } catch (e) {
            // 如果走不到，再清理一次然后重试
            await clearNearbyObstacles(5, true);
            try {
                await bot.pathfinder.goto(
                    new goals.GoalNear(targetBlock.position.x, targetBlock.position.y, targetBlock.position.z, 3)
                );
            } catch (e2) {
                return res.json({ status: 'cannot_reach', error: '无法到达树的位置' });
            }
        }

        // 砍树
        let blocksChopped = 0;
        for (let y = targetBlock.position.y; y <= targetBlock.position.y + 10; y++) {
            const block = bot.blockAt(new Vec3(
                targetBlock.position.x,
                y,
                targetBlock.position.z
            ));

            if (!block || !logNames.includes(block.name)) break;

            try {
                await equipBestToolForBlock(block.name);
                await bot.dig(block);
                blocksChopped++;
                await new Promise(resolve => setTimeout(resolve, 200));
            } catch (e) {
                break;
            }
        }

        // 等掉落物落地然后收集
       await new Promise(r => setTimeout(r, 1500));
        // 主动捡起来
        const picked = await pickupNearbyItems(20);
        console.log(`[砍树] 砍了 ${blocksChopped} 个原木，捡起 ${picked} 个掉落物`);

        res.json({
            status: 'done',
            blocks_chopped: blocksChopped,
            message: `砍了 ${blocksChopped} 个原木`
        });

    } catch (e) {
        console.error('砍树错误:', e);
        bot.pathfinder.setGoal(null);
        res.status(500).json({ error: e.message });
    }
});

 // 获取装备
app.get('/equipment', (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const items = bot.inventory.items();

    // 分类整理工具
    const tools = {};
    const toolTypes = ['pickaxe', 'axe', 'shovel', 'hoe', 'sword'];

    for (const type of toolTypes) {
        const matching = items.filter(i => i.name.includes(type));
        if (matching.length > 0) {
            tools[type] = matching.map(i => ({
                name: i.name,
                durability: i.maxDurability ? `${i.maxDurability - (i.durabilityUsed || 0)}/${i.maxDurability}` : 'N/A',
                count: i.count
            }));
        }
    }

    res.json({
        held_item: bot.heldItem ? bot.heldItem.name : 'empty',
        armor: {
            head: bot.inventory.slots[5]?.name || 'empty',
            chest: bot.inventory.slots[6]?.name || 'empty',
            legs: bot.inventory.slots[7]?.name || 'empty',
            feet: bot.inventory.slots[8]?.name || 'empty',
        },
        tools: tools,
        total_items: items.length
    });
});

// 手动装备指定物品
app.post('/equip', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const { name, destination = 'hand' } = req.body;

    try {
        const item = bot.inventory.items().find(i => i.name === name);
        if (!item) {
            return res.json({ error: `背包里没有 ${name}` });
        }

        await bot.equip(item, destination);
        res.json({ status: 'done', equipped: name, destination: destination });
    } catch (e) {
        res.json({ error: e.message });
    }
});

// 收集物品
app.post('/collect', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    try {
        const items = bot.findBlocks({
            matching: block => block.name.includes('item'),
            maxDistance: 8
        });
        
        if (items.length === 0) {
            return res.json({ status: 'no_items' });
        }
        
        for (const item of items) {
            await bot.collectBlock.collect(bot.blockAt(item));
        }
        
        res.json({ status: 'done', collected: items.length });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// 走到玩家身边（增强版智能寻路）
app.post('/goto_player', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    try {
        await clearNearbyObstacles(5, true);

        const player = bot.nearestEntity(entity => {
            return entity.type === 'player' && entity.username !== bot.username;
        });

        if (!player) {
            return res.json({ status: 'no_player_found' });
        }

        // 使用智能寻路系统
        const smartPathfinding = require('./smart_pathfinding.js');
        const result = await smartPathfinding.smartGotoPlayer(bot);

        res.json({
            status: 'arrived',
            player: player.username,
            method: result.method || 'normal'
        });
    } catch (e) {
        bot.pathfinder.setGoal(null);
        res.json({ status: 'path_failed', error: e.message });
    }
});

// 丢弃物品
app.post('/drop_item', (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    const { name } = req.body;
    const item = bot.inventory.items().find(i => i.name === name);
    
    if (!item) {
        return res.json({ status: 'not_found', item: name });
    }
    
    bot.tossStack(item);
    res.json({ status: 'dropped', item: name, count: item.count });
});

// 挖掘方块
app.post('/dig', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    const { x, y, z } = req.body;
    
    try {
        const block = bot.blockAt(new Vec3(x, y, z));
        if (!block || block.name === 'air') {
            return res.json({ error: '该位置没有方块' });
        }

        // 自动装备最佳工具
        const tool = await equipBestToolForBlock(block.name);

        const blockName = block.name;
        await bot.dig(block);

        // 挖完后自动拾取
        await new Promise(r => setTimeout(r, 800));
        await pickupNearbyItems(5);

        res.json({
            status: 'done',
            block: blockName,
            tool_used: tool ? tool.name : 'hand'
        });
    } catch (e) {
        res.json({ error: e.message });
    }
});

// 手动触发拾取
app.post('/pickup', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const radius = req.body.radius || autoPickupState.pickupRadius;
    const oldRadius = autoPickupState.pickupRadius;
    autoPickupState.pickupRadius = radius;

    const count = await pickupNearbyItems(20);
    autoPickupState.pickupRadius = oldRadius;

    res.json({ status: 'done', collected: count });
});

// 查看/修改自动拾取配置
app.get('/pickup_config', (req, res) => {
    // 统计附近掉落物数量
    let nearbyItems = 0;
    if (bot) {
        nearbyItems = Object.values(bot.entities).filter(e => {
            return e.name === 'item' &&
                   e.position.distanceTo(bot.entity.position) <= autoPickupState.pickupRadius;
        }).length;
    }

    res.json({
        enabled: autoPickupState.enabled,
        pickupRadius: autoPickupState.pickupRadius,
        cooldownMs: autoPickupState.cooldownMs,
        isPickingUp: autoPickupState.isPickingUp,
        nearbyItems: nearbyItems
    });
});

app.post('/pickup_config', (req, res) => {
    if (req.body.enabled !== undefined) {
        autoPickupState.enabled = req.body.enabled;
        if (autoPickupState.enabled) {
            startAutoPickup();
        } else {
            stopAutoPickup();
        }
    }
    if (req.body.radius !== undefined) {
        autoPickupState.pickupRadius = req.body.radius;
    }
    if (req.body.cooldownMs !== undefined) {
        autoPickupState.cooldownMs = req.body.cooldownMs;
        // 重启定时器
        stopAutoPickup();
        if (autoPickupState.enabled) startAutoPickup();
    }

    res.json({
        enabled: autoPickupState.enabled,
        pickupRadius: autoPickupState.pickupRadius,
        cooldownMs: autoPickupState.cooldownMs
    });
});

// 获取周围方块
app.get('/nearby', (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    const blocks = [];
    const pos = bot.entity.position;
    
    for (let x = -3; x <= 3; x++) {
        for (let y = -2; y <= 2; y++) {
            for (let z = -3; z <= 3; z++) {
                const block = bot.blockAt(pos.offset(x, y, z));
                if (block && block.name !== 'air') {
                    blocks.push({
                        name: block.name,
                        position: { x: block.position.x, y: block.position.y, z: block.position.z }
                    });
                }
            }
        }
    }
    
    res.json({ blocks: blocks });
});
// 合成物品
app.post('/craft', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const { name, count = 1 } = req.body;

    try {
        // 查找配方
        const item = bot.registry.itemsByName[name];
        if (!item) {
            return res.json({ error: `未知物品: ${name}` });
        }

        const recipes = bot.recipesFor(item.id);
        if (!recipes || recipes.length === 0) {
            return res.json({ error: `没有找到 ${name} 的合成配方，可能需要工作台` });
        }

        // 尝试合成
        await bot.craft(recipes[0], count);
        res.json({
            status: 'done',
            item: name,
            count: count,
            message: `成功合成了 ${count} 个 ${name}`
        });
    } catch (e) {
        res.json({ error: `合成失败: ${e.message}` });
    }
});

// 使用工作台合成（需要先走到工作台旁边）
app.post('/craft_at_table', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const { name, count = 1 } = req.body;

    try {
        const item = bot.registry.itemsByName[name];
        if (!item) {
            return res.json({ error: `未知物品: ${name}` });
        }

        // 找附近的工作台
        const tableId = bot.registry.blocksByName['crafting_table']?.id;
        const table = bot.findBlock({ matching: tableId, maxDistance: 4 });

        if (!table) {
            return res.json({ error: '附近没有工作台，请先放置一个' });
        }

        const recipes = bot.recipesFor(item.id, null, null, table);
        if (!recipes || recipes.length === 0) {
            return res.json({ error: `没有找到 ${name} 的合成配方，或材料不足` });
        }

        await bot.craft(recipes[0], count, table);
        res.json({
            status: 'done',
            item: name,
            count: count,
            message: `在工作台成功合成了 ${count} 个 ${name}`
        });
    } catch (e) {
        res.json({ error: `合成失败: ${e.message}` });
    }
});

// 砍多棵树并把木头给玩家
app.post('/chop_and_deliver', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const { count = 1, player_name } = req.body;

    try {
        await clearNearbyObstacles(5, true);

        const logNames = ['oak_log', 'birch_log', 'spruce_log', 'jungle_log',
                         'acacia_log', 'dark_oak_log', 'mangrove_log', 'cherry_log'];
        let totalChopped = 0;

        // 砍指定数量的树
        for (let t = 0; t < count; t++) {
            let targetBlock = null;
            for (const logName of logNames) {
                const blockId = bot.registry.blocksByName[logName]?.id;
                if (blockId) {
                    const found = bot.findBlock({ matching: blockId, maxDistance: 32 });
                    if (found) { targetBlock = found; break; }
                }
            }

            if (!targetBlock) break;

            // 清理并走过去
            await clearNearbyObstacles(5, true);
            const { goals } = pathfinder;
            bot.pathfinder.setMovements(getMovements());

            try {
                const timeout = new Promise((_, reject) => setTimeout(() => reject('超时'), 20000));
                const nav = bot.pathfinder.goto(new goals.GoalNear(
                    targetBlock.position.x, targetBlock.position.y, targetBlock.position.z, 2
                ));
                await Promise.race([nav, timeout]);
            } catch (e) {
                await clearNearbyObstacles(5, true);
                try {
                    await bot.pathfinder.goto(new goals.GoalNear(
                        targetBlock.position.x, targetBlock.position.y, targetBlock.position.z, 3
                    ));
                } catch (e2) {
                    continue; // 走不到就跳过这棵树
                }
            }

            // 砍树
            for (let y = targetBlock.position.y; y <= targetBlock.position.y + 10; y++) {
                const block = bot.blockAt(new Vec3(targetBlock.position.x, y, targetBlock.position.z));
                if (!block || !logNames.includes(block.name)) break;
                try {
                    await equipBestToolForBlock(block.name);
                    await bot.dig(block);
                    totalChopped++;
                    await new Promise(r => setTimeout(r, 200));
                } catch (e) { break; }
            }

            // 等掉落物并拾取
            await new Promise(r => setTimeout(r, 1500));
            // 主动捡起来
            const picked = await pickupNearbyItems(20);
            console.log(`[砍树交付] 第${t + 1}棵树，捡起 ${picked} 个掉落物`);
        }

        // 走到玩家身边
        const player = bot.nearestEntity(e => e.type === 'player' && e.username !== bot.username);
        if (player) {
            bot.pathfinder.setMovements(getMovements());
            try {
                await clearNearbyObstacles(5, true);
                const { goals } = pathfinder;
                await bot.pathfinder.goto(new goals.GoalNear(
                    player.position.x, player.position.y, player.position.z, 2
                ));
            } catch (e) {}

            // 丢出所有原木
            const inventory = bot.inventory.items();
            for (const item of inventory) {
                if (logNames.some(name => item.name === name)) {
                    try {
                        await bot.tossStack(item);
                        await new Promise(r => setTimeout(r, 300));
                    } catch (e) {}
                }
            }
        }

        res.json({
            status: 'done',
            logs_chopped: totalChopped,
            message: `砍了 ${totalChopped} 个原木并已丢给玩家`
        });

    } catch (e) {
        console.error('砍树交付错误:', e);
        bot.pathfinder.setGoal(null);
        res.json({ error: e.message });
    }
});

// 查看/调整清障配置
app.get('/clear_config', (req, res) => {
    res.json({
        cooldownMs: clearObstaclesState.cooldownMs,
        minDistance: clearObstaclesState.minDistanceToReClear,
        isClearing: clearObstaclesState.isClearing,
        lastClearTime: clearObstaclesState.lastClearTime
    });
});

app.post('/clear_config', (req, res) => {
    if (req.body.cooldownMs !== undefined) {
        clearObstaclesState.cooldownMs = req.body.cooldownMs;
    }
    if (req.body.minDistance !== undefined) {
        clearObstaclesState.minDistanceToReClear = req.body.minDistance;
    }
    res.json({
        cooldownMs: clearObstaclesState.cooldownMs,
        minDistance: clearObstaclesState.minDistanceToReClear
    });
});


// 放置方块
app.post('/place_block', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });
    
    const { x, y, z, name } = req.body;
    
    try {
        // 检查背包里有没有这个物品
        const item = bot.inventory.items().find(i => i.name === name);
        if (!item) {
            return res.json({ error: `背包里没有 ${name}` });
        }

        // 先走到放置位置附近
        const { goals } = pathfinder;
        bot.pathfinder.setMovements(getMovements());
        try {
            await bot.pathfinder.goto(new goals.GoalNear(x, y, z, 3));
        } catch (e) {
            // 走不到也继续尝试放置
        }

        // 找目标坐标下方的方块作为参考面
        const refBlock = bot.blockAt(new Vec3(x, y - 1, z));
        if (!refBlock || refBlock.name === 'air') {
            // 如果下面也是空气，找周围任意实体方块
            const directions = [
                new Vec3(x, y - 1, z),
                new Vec3(x + 1, y, z),
                new Vec3(x - 1, y, z),
                new Vec3(x, y, z + 1),
                new Vec3(x, y, z - 1),
            ];

            let found = null;
            for (const dir of directions) {
                const block = bot.blockAt(dir);
                if (block && block.name !== 'air') {
                    found = block;
                    break;
                }
            }

            if (!found) {
                return res.json({ error: '放置位置附近没有可依附的方块' });
            }

            await bot.equip(item, 'hand');
            // 计算放置方向
            const faceVec = new Vec3(x - found.position.x, y - found.position.y, z - found.position.z);
            await bot.placeBlock(found, faceVec);
        } else {
            await bot.equip(item, 'hand');
            await bot.placeBlock(refBlock, new Vec3(0, 1, 0));
        }

        res.json({ status: 'done', block: name, position: { x, y, z } });
    } catch (e) {
        res.json({ error: `放置失败: ${e.message}` });
    }
});

// 在自己脚边放方块（最可靠的放置方式）
app.post('/place_here', async (req, res) => {
    if (!bot) return res.status(400).json({ error: '未连接' });

    const { name } = req.body;

    try {
        const item = bot.inventory.items().find(i => i.name === name);
        if (!item) {
            return res.json({ error: `背包里没有 ${name}` });
        }

        const pos = bot.entity.position;
        // 在bot前方一格的地面上放置
        const yaw = bot.entity.yaw;
        const placeX = Math.floor(pos.x - Math.sin(yaw));
        const placeZ = Math.floor(pos.z + Math.cos(yaw));
        const placeY = Math.floor(pos.y - 1);

        const groundBlock = bot.blockAt(new Vec3(placeX, placeY, placeZ));
        if (!groundBlock || groundBlock.name === 'air') {
            // 如果前方没地面，就放在自己脚下
            const belowBlock = bot.blockAt(new Vec3(Math.floor(pos.x), Math.floor(pos.y) - 1, Math.floor(pos.z)));
            if (!belowBlock || belowBlock.name === 'air') {
                return res.json({ error: '脚下没有地面，无法放置' });
            }
            await bot.equip(item, 'hand');
            await bot.placeBlock(belowBlock, new Vec3(0, 1, 0));
            res.json({ status: 'done', block: name, position: belowBlock.position });
        } else {
            await bot.equip(item, 'hand');
            await bot.placeBlock(groundBlock, new Vec3(0, 1, 0));
            res.json({ status: 'done', block: name, position: { x: placeX, y: placeY + 1, z: placeZ } });
        }
    } catch (e) {
        res.json({ error: `放置失败: ${e.message}` });
    }
});
// ===== 新增：控制自动回复 =====

// 启用/禁用自动回复
app.post('/toggle_auto_reply', (req, res) => {
    isAutoReplyEnabled = !isAutoReplyEnabled;
    res.json({ 
        status: isAutoReplyEnabled ? 'enabled' : 'disabled',
        auto_reply: isAutoReplyEnabled 
    });
});

// 获取最近的聊天消息
app.get('/recent_chats', (req, res) => {
    const limit = parseInt(req.query.limit) || 10;
    res.json({
        messages: lastChatMessages.slice(-limit),
        auto_reply_enabled: isAutoReplyEnabled
    });
});

// 手动触发对某条消息的回复（用于测试）
app.post('/reply_to_chat', async (req, res) => {
    const { username, message } = req.body;
    
    if (!bot) {
        return res.status(400).json({ error: '未连接' });
    }
    
    try {
        await handleIncomingChat(username, message);
        res.json({ status: 'processing' });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// 启动服务器
const PORT = 3001;
app.listen(PORT, () => {
    console.log(`Minecraft Bot API 运行在 http://localhost:${PORT}`);
});