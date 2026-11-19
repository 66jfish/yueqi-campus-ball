-- 增量迁移 v1.3 -> v1.4（TiDB 兼容版：单条 ALTER 只做一个操作）
ALTER TABLE `t_registration`
    ADD COLUMN `skill_level` TINYINT NOT NULL DEFAULT 1
        COMMENT '报名时自评的该球类水平（必填）：1-新手 2-初级 3-中级 4-高级 5-大神';
