-- ============================================================================
--  增量迁移脚本（v1.2 -> v1.3）：AI 信誉画像模块
--  执行方式：mysql -uroot -p campus_ball < sql/005_migration_v1_3.sql
--  变更内容：t_user 新增画像相关字段
--      ai_score              AI 画像评估分（0-150），个人主页展示 + 球局匹配参考
--      ai_profile_source     画像来源：deepseek / rule
--      ai_profile_dirty      待重算标记（签到/缺席/退出结算时置 1，惰性重算）
--      ai_profile_trigger    最近一次重算原因
--      ai_profile_version    画像版本号（每次重算 +1，用于缓存与审计）
-- ============================================================================

USE `campus_ball`;

SET NAMES utf8mb4;

ALTER TABLE `t_user`
    ADD COLUMN `ai_score` INT DEFAULT NULL
        COMMENT 'AI画像评估分（0-150，画像算法输出；供个人主页展示与球局匹配参考）'
        AFTER `ai_profile`,
    ADD COLUMN `ai_profile_source` VARCHAR(16) DEFAULT NULL
        COMMENT '画像来源：deepseek（大模型）/ rule（本地加权规则降级）'
        AFTER `ai_profile_updated_at`,
    ADD COLUMN `ai_profile_dirty` TINYINT NOT NULL DEFAULT 0
        COMMENT '待重算标记：1=签到/缺席/退出结算后需要重算画像（后台任务或读取时惰性重算）'
        AFTER `ai_profile_source`,
    ADD COLUMN `ai_profile_trigger` VARCHAR(32) DEFAULT NULL
        COMMENT '最近一次触发重算的原因：checkin/absent/exit/manual/cache_expired'
        AFTER `ai_profile_dirty`,
    ADD COLUMN `ai_profile_version` INT NOT NULL DEFAULT 0
        COMMENT '画像版本号：每次重算 +1，便于缓存与审计'
        AFTER `ai_profile_trigger`;

-- 待重算标记的扫描索引（后台任务按 dirty=1 扫描）
ALTER TABLE `t_user`
    ADD INDEX `idx_user_ai_profile_dirty` (`ai_profile_dirty`, `updated_at`)
        COMMENT '后台重算待刷新画像的用户';

-- 校验
-- SHOW FULL COLUMNS FROM t_user LIKE 'ai_score';
-- SHOW FULL COLUMNS FROM t_user LIKE 'ai_profile%';
