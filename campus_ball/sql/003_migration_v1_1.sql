-- ============================================================================
--  增量迁移脚本（v1.0 -> v1.1）
--  适用场景：数据库已按 001_schema.sql 建好，只需增量变更，不必重建
--  变更内容：
--    1. t_checkin_record 新增 checkin_operator_id —— 记录「谁核销的」，便于追溯
--    2. t_game 新增索引 idx_game_venue_time —— 支撑同场地同时段冲突校验
--  执行方式：
--    mysql -uroot -p campus_ball < sql/003_migration_v1_1.sql
--  注意：MySQL 不支持 ADD COLUMN IF NOT EXISTS，重复执行会报 1060/1061，
--       可用下面的存储过程方式做幂等处理（见文件末尾的可选写法）。
-- ============================================================================

USE `campus_ball`;

SET NAMES utf8mb4;

-- ----------------------------------------------------------------------------
-- 1. 签到记录表：新增核销操作人字段
-- ----------------------------------------------------------------------------
ALTER TABLE `t_checkin_record`
    ADD COLUMN `checkin_operator_id` BIGINT UNSIGNED DEFAULT NULL
        COMMENT '核销/补签操作人用户ID（发起人核销时记录发起人ID；本人签到为空）'
        AFTER `checkin_time`;

-- ----------------------------------------------------------------------------
-- 2. 球局表：新增「场地 + 开球时间」联合索引（场地冲突校验走此索引）
-- ----------------------------------------------------------------------------
ALTER TABLE `t_game`
    ADD INDEX `idx_game_venue_time` (`venue_name`, `start_time`)
        COMMENT '同场地同时段冲突校验';

-- ----------------------------------------------------------------------------
-- 3. 校验变更结果
-- ----------------------------------------------------------------------------
-- SHOW INDEX FROM t_game WHERE Key_name = 'idx_game_venue_time';
-- SHOW FULL COLUMNS FROM t_checkin_record LIKE 'checkin_operator_id';


-- ============================================================================
-- 可选：幂等写法（重复执行不报错）
-- ============================================================================
-- DROP PROCEDURE IF EXISTS add_column_if_absent;
-- DELIMITER $$
-- CREATE PROCEDURE add_column_if_absent()
-- BEGIN
--     IF NOT EXISTS (
--         SELECT 1 FROM information_schema.COLUMNS
--         WHERE TABLE_SCHEMA = DATABASE()
--           AND TABLE_NAME = 't_checkin_record'
--           AND COLUMN_NAME = 'checkin_operator_id'
--     ) THEN
--         ALTER TABLE `t_checkin_record`
--             ADD COLUMN `checkin_operator_id` BIGINT UNSIGNED DEFAULT NULL
--                 COMMENT '核销/补签操作人用户ID' AFTER `checkin_time`;
--     END IF;
--
--     IF NOT EXISTS (
--         SELECT 1 FROM information_schema.STATISTICS
--         WHERE TABLE_SCHEMA = DATABASE()
--           AND TABLE_NAME = 't_game'
--           AND INDEX_NAME = 'idx_game_venue_time'
--     ) THEN
--         ALTER TABLE `t_game`
--             ADD INDEX `idx_game_venue_time` (`venue_name`, `start_time`)
--                 COMMENT '同场地同时段冲突校验';
--     END IF;
-- END$$
-- DELIMITER ;
-- CALL add_column_if_absent();
-- DROP PROCEDURE add_column_if_absent;
