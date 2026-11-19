-- ============================================================================
--  演示数据（全自增版 · 可重复执行）
--  ----------------------------------------------------------------------------
--  为什么需要这一版：
--      原 sql/002_init_data.sql 用了显式 id（用户 1/2/3、球局 101/102），
--      如果库里已经存在占用了这些自增值的记录（例如你自己注册的账号），
--      执行时会报 Duplicate entry '1' for key 'PRIMARY'。
--
--  本版特点：
--      1. 所有 INSERT 都不写 id，全部交给 AUTO_INCREMENT
--      2. 用 student_no / title 作为业务键做「不存在才插入」，可安全重复执行
--      3. 插入后用 SELECT 回查真实 id 存进变量（@u1/@g1...），跨表引用不错位
--      4. 与当前表结构完全对齐：含 t_registration.skill_level（报名自评水平）、
--         t_checkin_record.checkin_operator_id、校区统一为 老校区/新校区
--      5. 不带任何显式手机号以外的隐私假数据，手机号仅用于登录演示
--
--  执行方式（服务器上）：
--      cd ~/yueqi-campus-ball
--      sudo docker exec -i yueqi-mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" campus_ball' \
--        < campus_ball/sql/tidb/002_init_data_autoinc.sql
-- ============================================================================

-- ---------------------------------------------------------------- 1. 演示账号
INSERT INTO `t_user`
    (`student_no`, `nickname`, `real_name`, `password_hash`, `phone`,
     `campus`, `college`, `grade`, `gender`,
     `credit_score`, `credit_level`, `total_game_count`, `absent_count`, `skill_level`)
SELECT '20230001', '球场小王子', '张三',
       '$2b$12$QmH/vbFcHZbAE9F4xmiDE.9GN2K6faj/e7e5FDjMWC1./lhrn4Eau', '13800000001',
       '老校区', '计算机学院', '2023', 1,
       102, 3, 1, 0, 3
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_user` WHERE `student_no` = '20230001');

INSERT INTO `t_user`
    (`student_no`, `nickname`, `real_name`, `password_hash`, `phone`,
     `campus`, `college`, `grade`, `gender`,
     `credit_score`, `credit_level`, `total_game_count`, `absent_count`, `skill_level`)
SELECT '20230002', '羽毛球爱好者', '李四',
       '$2b$12$QmH/vbFcHZbAE9F4xmiDE.9GN2K6faj/e7e5FDjMWC1./lhrn4Eau', '13800000002',
       '新校区', '外国语学院', '2023', 2,
       92, 3, 1, 0, 2
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_user` WHERE `student_no` = '20230002');

-- 鸽王本王：信誉分 55（<60 → 等级 1 黑名单），有 1 次缺席，且当前处于禁赛期
INSERT INTO `t_user`
    (`student_no`, `nickname`, `real_name`, `password_hash`, `phone`,
     `campus`, `college`, `grade`, `gender`,
     `credit_score`, `credit_level`, `total_game_count`, `absent_count`, `skill_level`)
SELECT '20230003', '鸽王本王', '王五',
       '$2b$12$QmH/vbFcHZbAE9F4xmiDE.9GN2K6faj/e7e5FDjMWC1./lhrn4Eau', '13800000003',
       '老校区', '体育学院', '2022', 1,
       55, 1, 1, 1, 2
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_user` WHERE `student_no` = '20230003');

-- 回查真实自增 id（跨表引用用）
SET @u1 := (SELECT `id` FROM `t_user` WHERE `student_no` = '20230001' LIMIT 1);
SET @u2 := (SELECT `id` FROM `t_user` WHERE `student_no` = '20230002' LIMIT 1);
SET @u3 := (SELECT `id` FROM `t_user` WHERE `student_no` = '20230003' LIMIT 1);

-- ---------------------------------------------------------------- 2. 演示球局
-- 球局一：报名中、未开始（用于演示浏览 / 报名 / 必填水平）
INSERT INTO `t_game`
    (`creator_id`, `sport_type`, `title`, `description`, `campus`, `venue_name`, `venue_address`,
     `start_time`, `end_time`, `signup_deadline`, `checkin_start_time`, `checkin_end_time`,
     `max_players`, `min_players`, `current_players`, `fee_type`,
     `skill_level_limit`, `gender_limit`, `min_credit_score`, `status`, `settle_status`)
SELECT @u1, 1, '周五晚老校区篮球局', '水平不限，重在参与，请自备球鞋与水', '老校区', '老校区体育馆 3 号场', '老校区体育馆一层',
       DATE_ADD(NOW(), INTERVAL 1 DAY), NOW() + INTERVAL 1 DAY + INTERVAL 2 HOUR,
       DATE_ADD(NOW(), INTERVAL 20 HOUR),
       NOW() + INTERVAL 23 HOUR + INTERVAL 30 MINUTE, NOW() + INTERVAL 1 DAY + INTERVAL 15 MINUTE,
       10, 4, 2, 0, 0, 0, 0, 1, 0
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_game` WHERE `title` = '周五晚老校区篮球局' AND `is_deleted` = 0);

-- 球局二：已结束且已结算（用于演示核销结果 / 缺席 / 小黑屋来源）
INSERT INTO `t_game`
    (`creator_id`, `sport_type`, `title`, `description`, `campus`, `venue_name`, `venue_address`,
     `start_time`, `end_time`, `signup_deadline`, `checkin_start_time`, `checkin_end_time`,
     `max_players`, `min_players`, `current_players`, `fee_type`, `fee_amount`,
     `skill_level_limit`, `gender_limit`, `min_credit_score`, `status`, `settle_status`, `settled_at`)
SELECT @u2, 3, '新校区羽毛球双打（已结束）', '已结算：到场 +2、缺席 -10', '新校区', '新校区风雨操场羽毛球场', '风雨操场一层',
       DATE_SUB(NOW(), INTERVAL 2 DAY), NOW() - INTERVAL 2 DAY - INTERVAL 2 HOUR,
       NOW() - INTERVAL 2 DAY - INTERVAL 6 HOUR,
       NOW() - INTERVAL 2 DAY - INTERVAL 1 HOUR, NOW() - INTERVAL 2 DAY - INTERVAL 30 MINUTE,
       4, 2, 2, 1, 8.00,
       2, 0, 0, 4, 1, NOW() - INTERVAL 2 DAY - INTERVAL 30 MINUTE
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_game` WHERE `title` = '新校区羽毛球双打（已结束）' AND `is_deleted` = 0);

SET @g1 := (SELECT `id` FROM `t_game` WHERE `title` = '周五晚老校区篮球局' ORDER BY `id` LIMIT 1);
SET @g2 := (SELECT `id` FROM `t_game` WHERE `title` = '新校区羽毛球双打（已结束）' ORDER BY `id` LIMIT 1);

-- 修正冗余人数（按实际报名数，避免和名单不一致）
UPDATE `t_game` SET `current_players` = 2 WHERE `id` IN (@g1, @g2);

-- ---------------------------------------------------------------- 3. 报名记录（含自评水平）
INSERT INTO `t_registration` (`game_id`, `user_id`, `status`, `is_waitlist`, `waitlist_order`, `signup_time`, `credit_snapshot`, `skill_level`)
SELECT @g1, @u1, 1, 0, 0, DATE_SUB(NOW(), INTERVAL 5 HOUR), 102, 3
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_registration` WHERE `game_id` = @g1 AND `user_id` = @u1);

INSERT INTO `t_registration` (`game_id`, `user_id`, `status`, `is_waitlist`, `waitlist_order`, `signup_time`, `credit_snapshot`, `skill_level`)
SELECT @g1, @u2, 1, 0, 0, DATE_SUB(NOW(), INTERVAL 4 HOUR), 92, 2
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_registration` WHERE `game_id` = @g1 AND `user_id` = @u2);

INSERT INTO `t_registration` (`game_id`, `user_id`, `status`, `is_waitlist`, `waitlist_order`, `signup_time`, `credit_snapshot`, `skill_level`)
SELECT @g2, @u1, 1, 0, 0, DATE_SUB(NOW(), INTERVAL 3 DAY), 100, 3
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_registration` WHERE `game_id` = @g2 AND `user_id` = @u1);

INSERT INTO `t_registration` (`game_id`, `user_id`, `status`, `is_waitlist`, `waitlist_order`, `signup_time`, `credit_snapshot`, `skill_level`)
SELECT @g2, @u3, 1, 0, 0, DATE_SUB(NOW(), INTERVAL 3 DAY), 65, 2
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_registration` WHERE `game_id` = @g2 AND `user_id` = @u3);

-- ---------------------------------------------------------------- 4. 签到记录（演示惰性结算账本）
-- 球局一：两人均未签到（settled=0，等核销触发结算）
INSERT INTO `t_checkin_record` (`game_id`, `user_id`, `checkin_status`, `checkin_type`, `checkin_time`, `credit_delta`, `settled`)
SELECT @g1, @u1, 0, NULL, NULL, 0, 0
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_checkin_record` WHERE `game_id` = @g1 AND `user_id` = @u1);

INSERT INTO `t_checkin_record` (`game_id`, `user_id`, `checkin_status`, `checkin_type`, `checkin_time`, `credit_delta`, `settled`)
SELECT @g1, @u2, 0, NULL, NULL, 0, 0
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_checkin_record` WHERE `game_id` = @g1 AND `user_id` = @u2);

-- 球局二（已结算）：@u1 正常签到 +2；@u3 缺席 -10（缺席来源 → 封禁依据）
INSERT INTO `t_checkin_record` (`game_id`, `user_id`, `checkin_status`, `checkin_type`, `checkin_time`,
                                `checkin_operator_id`, `credit_delta`, `settled`, `settled_at`, `remark`)
SELECT @g2, @u1, 1, 3, NOW() - INTERVAL 2 DAY - INTERVAL 45 MINUTE,
       @u2, 2, 1, NOW() - INTERVAL 2 DAY - INTERVAL 30 MINUTE, '组织者现场核销'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_checkin_record` WHERE `game_id` = @g2 AND `user_id` = @u1);

INSERT INTO `t_checkin_record` (`game_id`, `user_id`, `checkin_status`, `checkin_type`, `checkin_time`,
                                `absence_confirmed_by`, `absence_confirmed_at`, `credit_delta`, `settled`, `settled_at`)
SELECT @g2, @u3, 3, NULL, NULL,
       0, NOW() - INTERVAL 2 DAY - INTERVAL 30 MINUTE, -10, 1, NOW() - INTERVAL 2 DAY - INTERVAL 30 MINUTE
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_checkin_record` WHERE `game_id` = @g2 AND `user_id` = @u3);

-- ---------------------------------------------------------------- 5. 小黑屋（演示封禁中的账号）
-- 20230003：昨天被关进小黑屋，禁赛 3 天（当前仍在封禁中，可演示 403 与解禁倒计时）
INSERT INTO `t_blacklist`
    (`user_id`, `ban_start_time`, `ban_duration_days`, `ban_end_time`, `status`,
     `reason_type`, `reason`, `trigger_game_id`, `credit_score_at_ban`, `operator_id`)
SELECT @u3, DATE_SUB(NOW(), INTERVAL 1 DAY), 3, DATE_ADD(NOW(), INTERVAL 2 DAY), 1,
       1, '缺席球局（未签到且未请假）', @g2, 55, 0
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM `t_blacklist` WHERE `user_id` = @u3 AND `trigger_game_id` = @g2);

-- ---------------------------------------------------------------- 6. 校验
SELECT `id`, `student_no`, `nickname`, `credit_score`, `credit_level`, `absent_count`, `skill_level` FROM `t_user`;
SELECT `id`, `title`, `campus`, `status`, `settle_status`, `current_players` FROM `t_game`;
SELECT `game_id`, `user_id`, `status`, `skill_level` FROM `t_registration`;
SELECT `user_id`, `ban_start_time`, `ban_duration_days`, `ban_end_time`, `status` FROM `t_blacklist`;
