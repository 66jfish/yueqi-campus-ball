-- ============================================================================
--  增量迁移脚本（v1.3 -> v1.4）：报名表新增「该球类自评水平」
--  执行方式：
--      # ① 先备份（务必执行，出问题可一键回滚）
--      mysqldump -h127.0.0.1 -uroot -p --single-transaction --routines --triggers \
--        campus_ball > ~/backup_campus_ball_$(date +%Y%m%d_%H%M).sql
--      # ② 再执行本文件
--      docker exec -i yueqi-mysql mysql -uroot -p'<你的root密码>' campus_ball < sql/006_migration_v1_4.sql
--
--  变更内容：
--      t_registration 新增 skill_level：报名时自评的该球类水平（1-新手 2-初级 3-中级 4-高级 5-大神）
--      存量数据统一回填为 1（新手），因为老数据没有采集过该字段
--
--  兼容性：TiDB 不支持一条 ALTER 多个操作，本文件只含一个操作，MySQL / TiDB 均可直接执行
-- ============================================================================

-- ① 备份命令（在 shell 里执行，不是 SQL）：
--    mysqldump -h127.0.0.1 -uroot -p --single-transaction campus_ball > ~/backup_campus_ball.sql

-- ② 加字段（NOT NULL + DEFAULT 1：存量行自动回填，不需要额外 UPDATE）
ALTER TABLE `t_registration`
    ADD COLUMN `skill_level` TINYINT NOT NULL DEFAULT 1
        COMMENT '报名时自评的该球类水平（必填）：1-新手 2-初级 3-中级 4-高级 5-大神';

-- ③ 校验
-- SHOW FULL COLUMNS FROM t_registration LIKE 'skill_level';
-- SELECT skill_level, COUNT(*) FROM t_registration GROUP BY skill_level;
