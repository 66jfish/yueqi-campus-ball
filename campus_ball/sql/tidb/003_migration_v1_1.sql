-- ============================================================================
--  TiDB Cloud Serverless 专用版本（由 sql/003_migration_v1_1.sql 自动转换生成）
--  与 MySQL 版的差异（均为 TiDB 语法限制，业务语义完全一致）：
--    1. 去掉 CREATE DATABASE / USE：TiDB Cloud 的 database 在控制台创建，
--       SQL 里不再切库（连接串已指定库名）
--    2. 一条 ALTER TABLE 只做一个操作：TiDB 不支持 multi schema change，
--       多个 ADD COLUMN 必须拆成多条语句
--    3. 去掉列位置子句 AFTER / FIRST：TiDB 对位置子句支持有限，且不影响业务
--    4. RENAME INDEX → DROP INDEX + ADD INDEX
--    5. 去掉 DELIMITER 存储过程块（TiDB 客户端不支持 DELIMITER）
--  执行方式：TiDB Cloud 控制台 SQL Editor 粘贴执行，或用 mysql 客户端连接后 source
-- ============================================================================

SET NAMES utf8mb4;
ALTER TABLE `t_checkin_record`
    ADD COLUMN `checkin_operator_id` BIGINT UNSIGNED DEFAULT NULL
        COMMENT '核销/补签操作人用户ID（发起人核销时记录发起人ID；本人签到为空）';
ALTER TABLE `t_game`
    ADD INDEX `idx_game_venue_time` (`venue_name`, `start_time`)
        COMMENT '同场地同时段冲突校验';
