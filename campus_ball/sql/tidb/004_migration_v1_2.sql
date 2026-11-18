-- ============================================================================
--  TiDB Cloud Serverless 专用版本（由 sql/004_migration_v1_2.sql 自动转换生成）
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
ALTER TABLE `t_user`
    CHANGE COLUMN `credit_score` `reputation_score` INT NOT NULL DEFAULT 100
        COMMENT '信誉分（初始100）。惰性结算：仅在签到/核销、判定缺席时更新；缺席一次 -10 分';
-- 原语句：ALTER TABLE `t_user` RENAME INDEX idx_user_credit_score TO idx_user_reputation_score（TiDB 建议改为下面两步）;
ALTER TABLE `t_user` DROP INDEX `idx_user_credit_score`;
ALTER TABLE `t_user` ADD INDEX `idx_user_reputation_score` (reputation_score);
ALTER TABLE `t_blacklist` ADD COLUMN `ban_extend_count` INT NOT NULL DEFAULT 0
        COMMENT '顺延次数：封禁期内再次缺席时累加（不新建记录，避免叠加封禁）';
ALTER TABLE `t_blacklist` ADD COLUMN `ban_original_end_time` DATETIME DEFAULT NULL
        COMMENT '首次解禁时间（顺延前的初始值，用于还原最初的3天窗口）';
ALTER TABLE `t_blacklist` ADD COLUMN `ban_last_extend_at` DATETIME DEFAULT NULL
        COMMENT '最近一次顺延时间';
