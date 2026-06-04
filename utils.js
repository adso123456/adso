/**
 * 共享工具函数 — bot_server.js 和 smart_pathfinding.js 共用
 */

const pathfinder = require('mineflayer-pathfinder');

/**
 * 获取寻路移动配置（统一版本，参数传入 bot）
 * 借鉴自 minecraft-mcp-server: 每次调用新建 Movements 实例，避免状态污染
 */
function getMovements(bot) {
    const { Movements } = pathfinder;
    const moves = new Movements(bot);
    moves.canDig = true;
    moves.allow1by1towers = true;
    moves.maxDropDown = 4;
    return moves;
}

module.exports = { getMovements };
