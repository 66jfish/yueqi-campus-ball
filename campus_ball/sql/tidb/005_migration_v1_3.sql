-- ============================================================================
--  TiDB Cloud Serverless 专用版本（由 sql/005_migration_v1_3.sql 自动转换生成）
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
ALTER TABLE `t_user` ADD COLUMN `ai_score` INT DEFAULT NULL
        COMMENT 'AI画像评估分（0-150，画像算法输出；供个人主页展示与球局匹配参考）';
ALTER TABLE `t_user` ADD COLUMN `ai_profile_source` VARCHAR(16) DEFAULT NULL
        COMMENT '画像来源：deepseek（大模型）/ rule（本地加权规则降级）';
ALTER TABLE `t_user` ADD COLUMN `ai_profile_dirty` TINYINT NOT NULL DEFAULT 0
        COMMENT '待重算标记：1=签到/缺席/退出结算后需要重算画像（后台任务或读取时惰性重算）';
ALTER TABLE `t_user` ADD COLUMN `ai_profile_trigger` VARCHAR(32) DEFAULT NULL
        COMMENT '最近一次触发重算的原因：checkin/absent/exit/manual/cache_expired';
ALTER TABLE `t_user` ADD COLUMN `ai_profile_version` INT NOT NULL DEFAULT 0
        COMMENT '画像版本号：每次重算 +1，便于缓存与审计';
ALTER TABLE `t_user`
    ADD INDEX `idx_user_ai_profile_dirty` (`ai_profile_dirty`, `updated_at`)
        COMMENT '后台重算待刷新画像的用户';
