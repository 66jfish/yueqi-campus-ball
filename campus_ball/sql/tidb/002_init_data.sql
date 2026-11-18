-- ============================================================================
--  TiDB Cloud Serverless 专用版本（由 sql/002_init_data.sql 自动转换生成）
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
INSERT INTO `t_user` (`id`, `student_no`, `nickname`, `real_name`, `password_hash`, `phone`,
                      `campus`, `college`, `grade`, `gender`,
                      `credit_score`, `credit_level`, `total_game_count`, `absent_count`, `skill_level`)
VALUES (1, '20230001', '球场小王子', '张三',
        '$2b$12$QmH/vbFcHZbAE9F4xmiDE.9GN2K6faj/e7e5FDjMWC1./lhrn4Eau',
        '13800000001', '东校区', '计算机学院', '2023', 1, 100, 3, 0, 0, 3),
       (2, '20230002', '羽毛球爱好者', '李四',
        '$2b$12$QmH/vbFcHZbAE9F4xmiDE.9GN2K6faj/e7e5FDjMWC1./lhrn4Eau',
        '13800000002', '东校区', '外国语学院', '2023', 2, 92, 3, 1, 1, 2),
       (3, '20230003', '鸽王本王', '王五',
        '$2b$12$QmH/vbFcHZbAE9F4xmiDE.9GN2K6faj/e7e5FDjMWC1./lhrn4Eau',
        '13800000003', '西校区', '体育学院', '2022', 1, 55, 1, 2, 3, 4);
INSERT INTO `t_game` (`id`, `creator_id`, `sport_type`, `title`, `description`, `campus`, `venue_name`,
                      `start_time`, `end_time`, `signup_deadline`, `checkin_start_time`, `checkin_end_time`,
                      `max_players`, `min_players`, `current_players`, `fee_type`, `status`, `settle_status`)
VALUES (101, 1, 1, '周五晚东区篮球局', '水平不限，重在参与，请自备球鞋', '东校区', '东区体育馆3号场',
        '2026-11-20 19:00:00', '2026-11-20 21:00:00', '2026-11-20 17:00:00',
        '2026-11-20 18:30:00', '2026-11-20 19:15:00', 10, 4, 2, 0, 1, 0),
       (102, 2, 3, '羽毛球双打（已结束）', '已结束，等待缺席判定', '东校区', '风雨操场羽毛球场',
        '2026-11-14 15:00:00', '2026-11-14 17:00:00', '2026-11-14 12:00:00',
        '2026-11-14 14:30:00', '2026-11-14 15:15:00', 4, 2, 3, 1, 4, 0);
INSERT INTO `t_registration` (`game_id`, `user_id`, `status`, `is_waitlist`, `waitlist_order`, `credit_snapshot`)
VALUES (101, 1, 1, 0, 0, 100),
       (101, 2, 1, 0, 0, 92),
       (102, 1, 1, 0, 0, 100),
       (102, 2, 1, 0, 0, 92),
       (102, 3, 1, 0, 0, 55);
INSERT INTO `t_checkin_record` (`game_id`, `user_id`, `checkin_status`, `checkin_type`, `checkin_time`,
                                `credit_delta`, `settled`, `settled_at`)
VALUES (101, 1, 1, 1, '2026-11-20 18:40:00', 0, 0, NULL),
       (101, 2, 1, 1, '2026-11-20 18:45:00', 0, 0, NULL),
       (102, 1, 1, 2, '2026-11-14 14:45:00', 2, 1, '2026-11-14 17:00:00'),
       (102, 2, 0, NULL, NULL, 0, 0, NULL),
       (102, 3, 0, NULL, NULL, 0, 0, NULL);
INSERT INTO `t_blacklist` (`user_id`, `ban_start_time`, `ban_duration_days`, `ban_end_time`, `status`,
                           `reason_type`, `reason`, `trigger_game_id`, `credit_score_at_ban`, `operator_id`)
VALUES (3, '2026-11-01 10:00:00', 3, '2026-11-04 10:00:00', 1, 1, '连续两次缺席未到', 100, 55, 0),
       (3, '2026-11-16 20:00:00', 3, '2026-11-19 20:00:00', 1, 1, '再次缺席球局', 102, 55, 0);
