-- ============================================================================
--  增量迁移脚本（v1.1 -> v1.2）：小黑屋失信惩罚模块
--  执行方式：mysql -uroot -p campus_ball < sql/004_migration_v1_2.sql
--  变更内容：
--    1. t_user.credit_score 重命名为 reputation_score（信誉分，缺席 -10）
--       注：接口层同时返回 credit_score 兼容字段，前端无需立即改造
--    2. t_blacklist 新增顺延相关字段：ban_extend_count / ban_original_end_time / ban_last_extend_at
--       用于「连续缺席不叠加封禁」：只顺延原记录，不新建记录
-- ============================================================================

USE `campus_ball`;

SET NAMES utf8mb4;

-- ----------------------------------------------------------------------------
-- 1. 用户表：信誉分字段重命名
--    MySQL 8.0+ 支持 RENAME COLUMN（5.7 请用 CHANGE 写法，见文件末尾注释）
-- ----------------------------------------------------------------------------
ALTER TABLE `t_user`
    CHANGE COLUMN `credit_score` `reputation_score` INT NOT NULL DEFAULT 100
        COMMENT '信誉分（初始100）。惰性结算：仅在签到/核销、判定缺席时更新；缺席一次 -10 分';

-- 索引同步重命名（如不存在该索引可跳过本句）
ALTER TABLE `t_user`
    RENAME INDEX `idx_user_credit_score` TO `idx_user_reputation_score`;

-- ----------------------------------------------------------------------------
-- 2. 小黑屋表：新增顺延字段
-- ----------------------------------------------------------------------------
ALTER TABLE `t_blacklist`
    ADD COLUMN `ban_extend_count` INT NOT NULL DEFAULT 0
        COMMENT '顺延次数：封禁期内再次缺席时累加（不新建记录，避免叠加封禁）'
        AFTER `released_at`,
    ADD COLUMN `ban_original_end_time` DATETIME DEFAULT NULL
        COMMENT '首次解禁时间（顺延前的初始值，用于还原最初的3天窗口）'
        AFTER `ban_extend_count`,
    ADD COLUMN `ban_last_extend_at` DATETIME DEFAULT NULL
        COMMENT '最近一次顺延时间'
        AFTER `ban_original_end_time`;

-- ----------------------------------------------------------------------------
-- 3. 历史数据兜底：已被判定缺席但未进小黑屋的用户，按新规则补一条封禁记录
--    （可选执行；若你的库里历史缺席数据不需要补罚，跳过本段即可）
-- ----------------------------------------------------------------------------
-- INSERT INTO t_blacklist
--     (user_id, ban_start_time, ban_duration_days, ban_end_time, status, reason_type, reason, credit_score_at_ban, operator_id)
-- SELECT r.user_id,
--        r.absence_confirmed_at,
--        3,
--        DATE_ADD(r.absence_confirmed_at, INTERVAL 3 DAY),
--        0,                                      -- 历史记录直接标记为已解封留痕
--        1,
--        CONCAT('历史缺席补录：球局 ', r.game_id),
--        u.reputation_score,
--        0
-- FROM t_checkin_record r
-- JOIN t_user u ON u.id = r.user_id
-- WHERE r.checkin_status = 3
--   AND r.absence_confirmed_at IS NOT NULL
--   AND NOT EXISTS (
--       SELECT 1 FROM t_blacklist b
--       WHERE b.user_id = r.user_id AND b.trigger_game_id = r.game_id
--   );

-- ----------------------------------------------------------------------------
-- 4. 校验
-- ----------------------------------------------------------------------------
-- SHOW FULL COLUMNS FROM t_user LIKE 'reputation_score';
-- SHOW FULL COLUMNS FROM t_blacklist LIKE 'ban_extend_count';


-- ============================================================================
-- 附：MySQL 5.7 写法（不支持 RENAME INDEX / RENAME COLUMN 时使用）
-- ============================================================================
-- ALTER TABLE `t_user` CHANGE `credit_score` `reputation_score` INT NOT NULL DEFAULT 100 COMMENT '信誉分';
-- ALTER TABLE `t_user` DROP INDEX `idx_user_credit_score`;
-- ALTER TABLE `t_user` ADD INDEX `idx_user_reputation_score` (`reputation_score`);
