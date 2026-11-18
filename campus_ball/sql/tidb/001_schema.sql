-- ============================================================================
--  TiDB Cloud Serverless 专用版本（由 sql/001_schema.sql 自动转换生成）
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
DROP TABLE IF EXISTS `t_user`;
CREATE TABLE `t_user`
(
    `id`                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '用户ID，主键',
    `student_no`           VARCHAR(32)     NOT NULL COMMENT '学号，校内唯一标识（登录账号之一）',
    `nickname`             VARCHAR(32)     NOT NULL COMMENT '昵称，球局中展示的名字',
    `real_name`            VARCHAR(32)              DEFAULT NULL COMMENT '真实姓名（实名认证用，仅管理端可见）',
    `password_hash`        VARCHAR(160)    NOT NULL COMMENT '密码哈希（PBKDF2-SHA256，格式：算法$迭代$盐$哈希，绝不存明文）',
    `phone`                VARCHAR(20)              DEFAULT NULL COMMENT '手机号（可作为登录账号 / 接收球局通知）',
    `email`                VARCHAR(64)              DEFAULT NULL COMMENT '邮箱（可选，用于找回密码）',
    `avatar_url`           VARCHAR(255)             DEFAULT NULL COMMENT '头像图片URL',
    `campus`               VARCHAR(64)              DEFAULT NULL COMMENT '所在校区，如：东校区',
    `college`              VARCHAR(64)              DEFAULT NULL COMMENT '学院，如：计算机学院',
    `grade`                VARCHAR(16)              DEFAULT NULL COMMENT '年级，如：2023',
    `gender`               TINYINT         NOT NULL DEFAULT 0 COMMENT '性别：0-未知 1-男 2-女（用于球局性别限制校验）',
    `reputation_score`     INT             NOT NULL DEFAULT 100 COMMENT '信誉分（初始100）。惰性结算：仅在签到/核销、判定缺席时更新，平时只读不计算；缺席一次 -10 分',
    `credit_level`         TINYINT         NOT NULL DEFAULT 3 COMMENT '信誉等级：1-黑名单 2-观察 3-正常 4-优秀 5-金牌（结算时按分数区间刷新，便于列表排序）',
    `credit_settled_at`    DATETIME                 DEFAULT NULL COMMENT '信誉分最近一次结算时间（惰性结算水位线，便于排查分数为何未变）',
    `total_game_count`     INT             NOT NULL DEFAULT 0 COMMENT '累计参与球局数（结算时累加，AI信誉画像输入特征）',
    `absent_count`         INT             NOT NULL DEFAULT 0 COMMENT '累计缺席/迟到次数（失信次数，AI画像与自动封禁依据）',
    `skill_level`          TINYINT         NOT NULL DEFAULT 1 COMMENT '球技水平：1-新手 2-初级 3-中级 4-高级 5-大神',
    `ai_profile`           JSON                     DEFAULT NULL COMMENT 'AI信誉画像结果（含画像分/标签/风险等级/明细；DeepSeek输出或本地加权规则版）',
    `ai_score`             INT                      DEFAULT NULL COMMENT 'AI画像评估分（0-150，画像算法输出；供个人主页展示与球局匹配参考）',
    `ai_profile_updated_at` DATETIME                DEFAULT NULL COMMENT 'AI信誉画像最近生成时间（用于24小时缓存判断）',
    `ai_profile_source`    VARCHAR(16)              DEFAULT NULL COMMENT '画像来源：deepseek（大模型）/ rule（本地加权规则降级）',
    `ai_profile_dirty`     TINYINT         NOT NULL DEFAULT 0 COMMENT '待重算标记：1=签到/缺席/退出结算后需要重算画像（后台任务或读取时惰性重算）',
    `ai_profile_trigger`   VARCHAR(32)              DEFAULT NULL COMMENT '最近一次触发重算的原因：checkin/absent/exit/manual/cache_expired',
    `ai_profile_version`   INT             NOT NULL DEFAULT 0 COMMENT '画像版本号：每次重算 +1，便于缓存与审计',
    `status`               TINYINT         NOT NULL DEFAULT 1 COMMENT '账号状态：0-禁用 1-正常',
    `last_login_at`        DATETIME                 DEFAULT NULL COMMENT '最近登录时间',
    `created_at`           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（注册时间）',
    `updated_at`           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `is_deleted`           TINYINT         NOT NULL DEFAULT 0 COMMENT '逻辑删除标记：0-未删除 1-已删除',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_user_student_no` (`student_no`) COMMENT '学号唯一',
    UNIQUE KEY `uk_user_phone` (`phone`) COMMENT '手机号唯一（NULL 不受唯一约束限制）',
    KEY `idx_user_reputation_score` (`reputation_score`) COMMENT '按信誉分筛选/排序',
    KEY `idx_user_ai_profile_dirty` (`ai_profile_dirty`, `updated_at`) COMMENT '后台重算待刷新画像的用户',
    KEY `idx_user_status` (`status`) COMMENT '按账号状态筛选'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci COMMENT ='用户表：账号、校内属性、信誉分（惰性结算）与 AI 画像';
DROP TABLE IF EXISTS `t_game`;
CREATE TABLE `t_game`
(
    `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '球局ID，主键',
    `creator_id`         BIGINT UNSIGNED NOT NULL COMMENT '发起人用户ID（关联 t_user.id）',
    `sport_type`         TINYINT         NOT NULL DEFAULT 1 COMMENT '运动类型：1-篮球 2-足球 3-羽毛球 4-网球 5-排球 6-乒乓球',
    `title`              VARCHAR(64)     NOT NULL COMMENT '球局标题，如：周五晚东区篮球局',
    `description`        TEXT                     DEFAULT NULL COMMENT '球局说明（水平要求、装备要求、注意事项等）',
    `campus`             VARCHAR(64)              DEFAULT NULL COMMENT '所在校区',
    `venue_name`         VARCHAR(64)              DEFAULT NULL COMMENT '场馆/球场名称',
    `venue_address`      VARCHAR(128)             DEFAULT NULL COMMENT '详细地址（定位打卡用）',
    `start_time`         DATETIME        NOT NULL COMMENT '开球时间',
    `end_time`           DATETIME        NOT NULL COMMENT '结束时间（结束后可触发缺席判定与惰性结算）',
    `signup_deadline`    DATETIME                 DEFAULT NULL COMMENT '报名截止时间',
    `checkin_start_time` DATETIME                 DEFAULT NULL COMMENT '签到开始时间（一般为开球前30分钟）',
    `checkin_end_time`   DATETIME                 DEFAULT NULL COMMENT '签到截止时间（超过此时刻签到记为迟到；结束后仍未签到判为缺席）',
    `max_players`        SMALLINT        NOT NULL DEFAULT 10 COMMENT '最大人数（含发起人），满员后报名进入候补',
    `min_players`        SMALLINT        NOT NULL DEFAULT 2 COMMENT '最少成局人数，低于该人数可流局',
    `current_players`    SMALLINT        NOT NULL DEFAULT 0 COMMENT '当前正式报名人数（冗余字段，报名/取消/补位时同步维护，避免列表页 COUNT）',
    `fee_type`           TINYINT         NOT NULL DEFAULT 0 COMMENT '费用类型：0-免费 1-AA制',
    `fee_amount`         DECIMAL(10, 2)           DEFAULT NULL COMMENT '人均费用（元），fee_type=1 时有效',
    `skill_level_limit`  TINYINT         NOT NULL DEFAULT 0 COMMENT '最低球技要求：0-不限 1-新手 2-初级 3-中级 4-高级 5-大神',
    `gender_limit`       TINYINT         NOT NULL DEFAULT 0 COMMENT '性别限制：0-不限 1-仅男生 2-仅女生',
    `min_credit_score`   INT             NOT NULL DEFAULT 0 COMMENT '报名最低信誉分要求：0-不限（用于过滤低信誉用户）',
    `status`             TINYINT         NOT NULL DEFAULT 0 COMMENT '球局状态：0-草稿 1-报名中 2-报名截止 3-进行中 4-已结束 5-已取消',
    `settle_status`      TINYINT         NOT NULL DEFAULT 0 COMMENT '结算状态（惰性结算用）：0-待结算 1-已结算 2-部分结算，防止同一球局重复结算',
    `settled_at`         DATETIME                 DEFAULT NULL COMMENT '本条球局完成结算的时间',
    `cancel_reason`      VARCHAR(255)             DEFAULT NULL COMMENT '取消/流局原因',
    `created_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    `is_deleted`         TINYINT         NOT NULL DEFAULT 0 COMMENT '逻辑删除标记：0-未删除 1-已删除',
    PRIMARY KEY (`id`),
    KEY `idx_game_creator` (`creator_id`) COMMENT '按发起人查询"我发起的球局"',
    KEY `idx_game_sport_start` (`sport_type`, `start_time`) COMMENT '按运动类型 + 时间筛选',
    KEY `idx_game_status_start` (`status`, `start_time`) COMMENT '首页列表：报名中 + 即将开始',
    KEY `idx_game_settle_status` (`settle_status`) COMMENT '扫描待结算球局',
    KEY `idx_game_venue_time` (`venue_name`, `start_time`) COMMENT '同场地同时段冲突校验'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci COMMENT ='球局表：约球主表，含签到窗口与结算标记';
DROP TABLE IF EXISTS `t_registration`;
CREATE TABLE `t_registration`
(
    `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '报名记录ID，主键',
    `game_id`         BIGINT UNSIGNED NOT NULL COMMENT '球局ID（关联 t_game.id）',
    `user_id`         BIGINT UNSIGNED NOT NULL COMMENT '报名用户ID（关联 t_user.id）',
    `status`          TINYINT         NOT NULL DEFAULT 1 COMMENT '报名状态：1-已报名 2-已取消 3-候补中 4-被移出（取消不物理删除，便于失信追溯）',
    `is_waitlist`     TINYINT         NOT NULL DEFAULT 0 COMMENT '是否候补：0-正式名额 1-候补队列',
    `waitlist_order`  INT             NOT NULL DEFAULT 0 COMMENT '候补顺序号，越小越先补位（正式报名时为0）',
    `signup_time`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '报名时间',
    `cancel_time`     DATETIME                 DEFAULT NULL COMMENT '取消报名时间',
    `cancel_reason`   VARCHAR(255)             DEFAULT NULL COMMENT '取消报名原因',
    `credit_snapshot` INT                      DEFAULT NULL COMMENT '报名时的信誉分快照（AI画像/事后追责参考）',
    `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_reg_game_user` (`game_id`, `user_id`) COMMENT '同一球局同一用户仅一条报名记录',
    KEY `idx_reg_game_status` (`game_id`, `status`) COMMENT '球局报名名单查询',
    KEY `idx_reg_user_status` (`user_id`, `status`) COMMENT '我的球局列表查询'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci COMMENT ='报名表：正式报名 + 候补队列';
DROP TABLE IF EXISTS `t_checkin_record`;
CREATE TABLE `t_checkin_record`
(
    `id`                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '签到记录ID，主键',
    `game_id`               BIGINT UNSIGNED NOT NULL COMMENT '球局ID（关联 t_game.id）',
    `registration_id`       BIGINT UNSIGNED          DEFAULT NULL COMMENT '关联报名记录ID（关联 t_registration.id）',
    `user_id`               BIGINT UNSIGNED NOT NULL COMMENT '用户ID（关联 t_user.id）',
    `checkin_status`        TINYINT         NOT NULL DEFAULT 0 COMMENT '签到状态：0-未签到 1-正常签到 2-迟到 3-缺席 4-已请假',
    `checkin_type`          TINYINT                  DEFAULT NULL COMMENT '签到方式：1-扫码 2-定位打卡 3-发起人核销/人工补签',
    `checkin_time`          DATETIME                 DEFAULT NULL COMMENT '实际签到时间',
    `checkin_operator_id`   BIGINT UNSIGNED          DEFAULT NULL COMMENT '核销/补签操作人用户ID（发起人核销时记录发起人ID；本人签到为空）',
    `location_lat`          DECIMAL(10, 7)           DEFAULT NULL COMMENT '签到纬度（用于校验是否在球场附近，防代签）',
    `location_lng`          DECIMAL(10, 7)           DEFAULT NULL COMMENT '签到经度（用于校验是否在球场附近，防代签）',
    `absence_confirmed_by`  BIGINT UNSIGNED          DEFAULT NULL COMMENT '缺席判定人用户ID（发起人或系统，系统判定填0）',
    `absence_confirmed_at`  DATETIME                 DEFAULT NULL COMMENT '缺席判定时间（★惰性结算触发时机 B）',
    `credit_delta`          INT             NOT NULL DEFAULT 0 COMMENT '本次记录折算的信誉分变动（结算时写入，如 +2 / -3 / -10）',
    `settled`               TINYINT         NOT NULL DEFAULT 0 COMMENT '惰性结算标记：0-待结算 1-已结算（签到或判定缺席时才置1，保证不重复结算）',
    `settled_at`            DATETIME                 DEFAULT NULL COMMENT '该记录被结算的时间',
    `remark`                VARCHAR(255)             DEFAULT NULL COMMENT '备注（请假原因、人工补签说明等）',
    `created_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（报名时预生成）',
    `updated_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    UNIQUE KEY `uk_checkin_game_user` (`game_id`, `user_id`) COMMENT '同一球局同一用户仅一条签到记录',
    KEY `idx_checkin_settle` (`settled`, `checkin_status`) COMMENT '★惰性结算核心索引：快速捞出待结算记录',
    KEY `idx_checkin_user_status` (`user_id`, `checkin_status`) COMMENT '统计用户签到/缺席次数'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci COMMENT ='签到记录表：签到/请假/缺席事实 + 惰性结算账本（settled 标记）';
DROP TABLE IF EXISTS `t_blacklist`;
CREATE TABLE `t_blacklist`
(
    `id`                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '小黑屋记录ID，主键',
    `user_id`             BIGINT UNSIGNED NOT NULL COMMENT '被禁赛用户ID（关联 t_user.id）',
    `ban_start_time`      DATETIME        NOT NULL COMMENT '★封禁开始时间',
    `ban_duration_days`   SMALLINT        NOT NULL DEFAULT 3 COMMENT '★封禁时长（天），校园规则默认3天',
    `ban_end_time`        DATETIME        NOT NULL COMMENT '★解封时间 = 封禁开始时间 + 封禁时长，由服务层写入；判定条件为 status=1 AND ban_end_time > NOW()，到期即自动失效',
    `status`              TINYINT         NOT NULL DEFAULT 1 COMMENT '封禁状态：0-已解封 1-封禁中（查询侧以 ban_end_time 惰性判定，本字段仅用于留痕）',
    `released_at`         DATETIME                 DEFAULT NULL COMMENT '实际解封时间',
    `ban_extend_count`    INT             NOT NULL DEFAULT 0 COMMENT '顺延次数：封禁期内再次缺席时累加（不新建记录，避免叠加封禁）',
    `ban_original_end_time` DATETIME               DEFAULT NULL COMMENT '首次解禁时间（顺延前的初始值，用于还原最初的3天窗口）',
    `ban_last_extend_at`  DATETIME                 DEFAULT NULL COMMENT '最近一次顺延时间',
    `release_type`        TINYINT                  DEFAULT NULL COMMENT '解封方式：1-到期自动解封 2-管理员手动解封 3-申诉通过',
    `reason_type`         TINYINT         NOT NULL DEFAULT 1 COMMENT '封禁原因类型：1-缺席未到 2-多次迟到累计 3-信誉分过低 4-管理员人工封禁',
    `reason`              VARCHAR(255)             DEFAULT NULL COMMENT '封禁详细原因说明',
    `trigger_game_id`     BIGINT UNSIGNED          DEFAULT NULL COMMENT '触发封禁的球局ID（人工封禁时为空）',
    `credit_score_at_ban` INT                      DEFAULT NULL COMMENT '封禁时的信誉分快照（申诉复核用）',
    `operator_id`         BIGINT UNSIGNED          DEFAULT NULL COMMENT '操作人用户ID（系统自动封禁填0）',
    `remark`              VARCHAR(255)             DEFAULT NULL COMMENT '备注（解封说明、申诉结论等）',
    `created_at`          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at`          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    KEY `idx_ban_user_status_end` (`user_id`, `status`, `ban_end_time`) COMMENT '★中间件高频查询：该用户是否处于禁赛期',
    KEY `idx_ban_end_time` (`ban_end_time`) COMMENT '后台任务扫描到期记录'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci COMMENT ='失信小黑屋表：封禁起始时间+时长+到期自动解封，黑名单中间件统一拦截依据';
