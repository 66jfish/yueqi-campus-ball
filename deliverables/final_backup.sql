-- MySQL dump 10.13  Distrib 8.0.46, for Linux (x86_64)
--
-- Host: localhost    Database: campus_ball
-- ------------------------------------------------------
-- Server version	8.0.46

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `t_blacklist`
--

DROP TABLE IF EXISTS `t_blacklist`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_blacklist` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '小黑屋记录ID，主键',
  `user_id` bigint unsigned NOT NULL COMMENT '被禁赛用户ID（关联 t_user.id）',
  `ban_start_time` datetime NOT NULL COMMENT '★封禁开始时间',
  `ban_duration_days` smallint NOT NULL DEFAULT '3' COMMENT '★封禁时长（天），校园规则默认3天',
  `ban_end_time` datetime NOT NULL COMMENT '★解封时间 = 封禁开始时间 + 封禁时长，由服务层写入；判定条件为 status=1 AND ban_end_time > NOW()，到期即自动失效',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '封禁状态：0-已解封 1-封禁中（查询侧以 ban_end_time 惰性判定，本字段仅用于留痕）',
  `released_at` datetime DEFAULT NULL COMMENT '实际解封时间',
  `ban_extend_count` int NOT NULL DEFAULT '0' COMMENT '顺延次数：封禁期内再次缺席时累加（不新建记录，避免叠加封禁）',
  `ban_original_end_time` datetime DEFAULT NULL COMMENT '首次解禁时间（顺延前的初始值，用于还原最初的3天窗口）',
  `ban_last_extend_at` datetime DEFAULT NULL COMMENT '最近一次顺延时间',
  `release_type` tinyint DEFAULT NULL COMMENT '解封方式：1-到期自动解封 2-管理员手动解封 3-申诉通过',
  `reason_type` tinyint NOT NULL DEFAULT '1' COMMENT '封禁原因类型：1-缺席未到 2-多次迟到累计 3-信誉分过低 4-管理员人工封禁',
  `reason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '封禁详细原因说明',
  `trigger_game_id` bigint unsigned DEFAULT NULL COMMENT '触发封禁的球局ID（人工封禁时为空）',
  `credit_score_at_ban` int DEFAULT NULL COMMENT '封禁时的信誉分快照（申诉复核用）',
  `operator_id` bigint unsigned DEFAULT NULL COMMENT '操作人用户ID（系统自动封禁填0）',
  `remark` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '备注（解封说明、申诉结论等）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_ban_user_status_end` (`user_id`,`status`,`ban_end_time`) COMMENT '★中间件高频查询：该用户是否处于禁赛期',
  KEY `idx_ban_end_time` (`ban_end_time`) COMMENT '后台任务扫描到期记录'
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='失信小黑屋表：封禁起始时间+时长+到期自动解封，黑名单中间件统一拦截依据';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `t_blacklist`
--

LOCK TABLES `t_blacklist` WRITE;
/*!40000 ALTER TABLE `t_blacklist` DISABLE KEYS */;
INSERT INTO `t_blacklist` VALUES (1,6,'2026-11-19 14:08:37',3,'2026-11-22 14:08:37',1,NULL,0,NULL,NULL,NULL,1,'缺席球局（未签到且未请假），球局ID=1',1,90,6,NULL,'2026-11-19 14:08:36','2026-11-19 14:08:36'),(2,7,'2026-11-19 14:08:37',3,'2026-11-22 14:08:37',1,NULL,0,NULL,NULL,NULL,1,'缺席球局（未签到且未请假），球局ID=1',1,90,6,NULL,'2026-11-19 14:08:36','2026-11-19 14:08:36'),(3,11,'2026-11-19 14:19:44',3,'2026-11-22 14:19:44',1,NULL,0,NULL,NULL,NULL,1,'缺席球局（未签到且未请假），球局ID=2',2,90,10,NULL,'2026-11-19 14:19:43','2026-11-19 14:19:43');
/*!40000 ALTER TABLE `t_blacklist` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `t_checkin_record`
--

DROP TABLE IF EXISTS `t_checkin_record`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_checkin_record` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '签到记录ID，主键',
  `game_id` bigint unsigned NOT NULL COMMENT '球局ID（关联 t_game.id）',
  `registration_id` bigint unsigned DEFAULT NULL COMMENT '关联报名记录ID（关联 t_registration.id）',
  `user_id` bigint unsigned NOT NULL COMMENT '用户ID（关联 t_user.id）',
  `checkin_status` tinyint NOT NULL DEFAULT '0' COMMENT '签到状态：0-未签到 1-正常签到 2-迟到 3-缺席 4-已请假',
  `checkin_type` tinyint DEFAULT NULL COMMENT '签到方式：1-扫码 2-定位打卡 3-发起人核销/人工补签',
  `checkin_time` datetime DEFAULT NULL COMMENT '实际签到时间',
  `checkin_operator_id` bigint unsigned DEFAULT NULL COMMENT '核销/补签操作人用户ID（发起人核销时记录发起人ID；本人签到为空）',
  `location_lat` decimal(10,7) DEFAULT NULL COMMENT '签到纬度（用于校验是否在球场附近，防代签）',
  `location_lng` decimal(10,7) DEFAULT NULL COMMENT '签到经度（用于校验是否在球场附近，防代签）',
  `absence_confirmed_by` bigint unsigned DEFAULT NULL COMMENT '缺席判定人用户ID（发起人或系统，系统判定填0）',
  `absence_confirmed_at` datetime DEFAULT NULL COMMENT '缺席判定时间（★惰性结算触发时机 B）',
  `credit_delta` int NOT NULL DEFAULT '0' COMMENT '本次记录折算的信誉分变动（结算时写入，如 +2 / -3 / -10）',
  `settled` tinyint NOT NULL DEFAULT '0' COMMENT '惰性结算标记：0-待结算 1-已结算（签到或判定缺席时才置1，保证不重复结算）',
  `settled_at` datetime DEFAULT NULL COMMENT '该记录被结算的时间',
  `remark` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '备注（请假原因、人工补签说明等）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（报名时预生成）',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_checkin_game_user` (`game_id`,`user_id`) COMMENT '同一球局同一用户仅一条签到记录',
  KEY `idx_checkin_settle` (`settled`,`checkin_status`) COMMENT '★惰性结算核心索引：快速捞出待结算记录',
  KEY `idx_checkin_user_status` (`user_id`,`checkin_status`) COMMENT '统计用户签到/缺席次数'
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='签到记录表：签到/请假/缺席事实 + 惰性结算账本（settled 标记）';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `t_checkin_record`
--

LOCK TABLES `t_checkin_record` WRITE;
/*!40000 ALTER TABLE `t_checkin_record` DISABLE KEYS */;
INSERT INTO `t_checkin_record` VALUES (1,1,NULL,6,3,NULL,NULL,NULL,NULL,NULL,6,'2026-11-19 14:08:37',-10,1,'2026-11-19 14:08:37',NULL,'2026-11-19 14:08:09','2026-11-19 14:08:36'),(2,1,NULL,7,3,NULL,NULL,NULL,NULL,NULL,6,'2026-11-19 14:08:37',-10,1,'2026-11-19 14:08:37',NULL,'2026-11-19 14:08:16','2026-11-19 14:08:36'),(3,1,NULL,8,1,3,'2026-11-19 14:08:30',6,NULL,NULL,NULL,NULL,2,1,'2026-11-19 14:08:30',NULL,'2026-11-19 14:08:23','2026-11-19 14:08:29'),(4,2,NULL,10,1,3,'2026-11-19 14:19:44',10,NULL,NULL,NULL,NULL,2,1,'2026-11-19 14:19:44',NULL,'2026-11-19 14:19:43','2026-11-19 14:19:43'),(5,2,NULL,11,3,NULL,NULL,NULL,NULL,NULL,10,'2026-11-19 14:19:44',-10,1,'2026-11-19 14:19:44',NULL,'2026-11-19 14:19:43','2026-11-19 14:19:43');
/*!40000 ALTER TABLE `t_checkin_record` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `t_game`
--

DROP TABLE IF EXISTS `t_game`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_game` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '球局ID，主键',
  `creator_id` bigint unsigned NOT NULL COMMENT '发起人用户ID（关联 t_user.id）',
  `sport_type` tinyint NOT NULL DEFAULT '1' COMMENT '运动类型：1-篮球 2-足球 3-羽毛球 4-网球 5-排球 6-乒乓球',
  `title` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '球局标题，如：周五晚东区篮球局',
  `description` text COLLATE utf8mb4_unicode_ci COMMENT '球局说明（水平要求、装备要求、注意事项等）',
  `campus` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所在校区',
  `venue_name` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '场馆/球场名称',
  `venue_address` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '详细地址（定位打卡用）',
  `start_time` datetime NOT NULL COMMENT '开球时间',
  `end_time` datetime NOT NULL COMMENT '结束时间（结束后可触发缺席判定与惰性结算）',
  `signup_deadline` datetime DEFAULT NULL COMMENT '报名截止时间',
  `checkin_start_time` datetime DEFAULT NULL COMMENT '签到开始时间（一般为开球前30分钟）',
  `checkin_end_time` datetime DEFAULT NULL COMMENT '签到截止时间（超过此时刻签到记为迟到；结束后仍未签到判为缺席）',
  `max_players` smallint NOT NULL DEFAULT '10' COMMENT '最大人数（含发起人），满员后报名进入候补',
  `min_players` smallint NOT NULL DEFAULT '2' COMMENT '最少成局人数，低于该人数可流局',
  `current_players` smallint NOT NULL DEFAULT '0' COMMENT '当前正式报名人数（冗余字段，报名/取消/补位时同步维护，避免列表页 COUNT）',
  `fee_type` tinyint NOT NULL DEFAULT '0' COMMENT '费用类型：0-免费 1-AA制',
  `fee_amount` decimal(10,2) DEFAULT NULL COMMENT '人均费用（元），fee_type=1 时有效',
  `skill_level_limit` tinyint NOT NULL DEFAULT '0' COMMENT '最低球技要求：0-不限 1-新手 2-初级 3-中级 4-高级 5-大神',
  `gender_limit` tinyint NOT NULL DEFAULT '0' COMMENT '性别限制：0-不限 1-仅男生 2-仅女生',
  `min_credit_score` int NOT NULL DEFAULT '0' COMMENT '报名最低信誉分要求：0-不限（用于过滤低信誉用户）',
  `status` tinyint NOT NULL DEFAULT '0' COMMENT '球局状态：0-草稿 1-报名中 2-报名截止 3-进行中 4-已结束 5-已取消',
  `settle_status` tinyint NOT NULL DEFAULT '0' COMMENT '结算状态（惰性结算用）：0-待结算 1-已结算 2-部分结算，防止同一球局重复结算',
  `settled_at` datetime DEFAULT NULL COMMENT '本条球局完成结算的时间',
  `cancel_reason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '取消/流局原因',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint NOT NULL DEFAULT '0' COMMENT '逻辑删除标记：0-未删除 1-已删除',
  PRIMARY KEY (`id`),
  KEY `idx_game_creator` (`creator_id`) COMMENT '按发起人查询"我发起的球局"',
  KEY `idx_game_sport_start` (`sport_type`,`start_time`) COMMENT '按运动类型 + 时间筛选',
  KEY `idx_game_status_start` (`status`,`start_time`) COMMENT '首页列表：报名中 + 即将开始',
  KEY `idx_game_settle_status` (`settle_status`) COMMENT '扫描待结算球局',
  KEY `idx_game_venue_time` (`venue_name`,`start_time`) COMMENT '同场地同时段冲突校验'
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='球局表：约球主表，含签到窗口与结算标记';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `t_game`
--

LOCK TABLES `t_game` WRITE;
/*!40000 ALTER TABLE `t_game` DISABLE KEYS */;
INSERT INTO `t_game` VALUES (1,6,3,'月球羽毛球双打 443418',NULL,'新校区','新校区风雨操场 1 号场',NULL,'2026-11-19 14:15:00','2026-11-19 16:07:00',NULL,'2026-11-19 13:45:00','2026-11-19 14:30:00',6,2,3,0,NULL,2,0,0,4,1,'2026-11-19 14:08:37',NULL,'2026-11-19 14:08:09','2026-11-19 14:08:36',0),(2,10,3,'封禁链路验证 181133',NULL,'新校区','新校区风雨操场 2 号场',NULL,'2026-11-19 14:27:00','2026-11-19 16:19:00',NULL,'2026-11-19 13:57:00','2026-11-19 14:42:00',6,2,2,0,NULL,2,0,0,4,1,'2026-11-19 14:19:44',NULL,'2026-11-19 14:19:43','2026-11-19 14:19:43',0);
/*!40000 ALTER TABLE `t_game` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `t_registration`
--

DROP TABLE IF EXISTS `t_registration`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_registration` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '报名记录ID，主键',
  `game_id` bigint unsigned NOT NULL COMMENT '球局ID（关联 t_game.id）',
  `user_id` bigint unsigned NOT NULL COMMENT '报名用户ID（关联 t_user.id）',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '报名状态：1-已报名 2-已取消 3-候补中 4-被移出（取消不物理删除，便于失信追溯）',
  `is_waitlist` tinyint NOT NULL DEFAULT '0' COMMENT '是否候补：0-正式名额 1-候补队列',
  `waitlist_order` int NOT NULL DEFAULT '0' COMMENT '候补顺序号，越小越先补位（正式报名时为0）',
  `signup_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '报名时间',
  `cancel_time` datetime DEFAULT NULL COMMENT '取消报名时间',
  `cancel_reason` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '取消报名原因',
  `credit_snapshot` int DEFAULT NULL COMMENT '报名时的信誉分快照（AI画像/事后追责参考）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `skill_level` tinyint NOT NULL DEFAULT '1' COMMENT 'æŠ¥åæ—¶è‡ªè¯„çš„è¯¥çƒç±»æ°´å¹³ï¼ˆå¿…å¡«ï¼‰ï¼š1-æ–°æ‰‹ 2-åˆçº§ 3-ä¸­çº§ 4-é«˜çº§ 5-å¤§ç¥ž',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_reg_game_user` (`game_id`,`user_id`) COMMENT '同一球局同一用户仅一条报名记录',
  KEY `idx_reg_game_status` (`game_id`,`status`) COMMENT '球局报名名单查询',
  KEY `idx_reg_user_status` (`user_id`,`status`) COMMENT '我的球局列表查询'
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='报名表：正式报名 + 候补队列';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `t_registration`
--

LOCK TABLES `t_registration` WRITE;
/*!40000 ALTER TABLE `t_registration` DISABLE KEYS */;
INSERT INTO `t_registration` VALUES (1,1,6,1,0,0,'2026-11-19 14:08:10',NULL,NULL,100,'2026-11-19 14:08:09','2026-11-19 14:08:09',1),(2,1,7,1,0,0,'2026-11-19 14:08:17',NULL,NULL,100,'2026-11-19 14:08:16','2026-11-19 14:08:16',4),(3,1,8,1,0,0,'2026-11-19 14:08:23',NULL,NULL,100,'2026-11-19 14:08:23','2026-11-19 14:08:23',2),(4,2,10,1,0,0,'2026-11-19 14:19:43',NULL,NULL,100,'2026-11-19 14:19:43','2026-11-19 14:19:43',1),(5,2,11,1,0,0,'2026-11-19 14:19:43',NULL,NULL,100,'2026-11-19 14:19:43','2026-11-19 14:19:43',3);
/*!40000 ALTER TABLE `t_registration` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `t_user`
--

DROP TABLE IF EXISTS `t_user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `t_user` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '用户ID，主键',
  `student_no` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '学号，校内唯一标识（登录账号之一）',
  `nickname` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '昵称，球局中展示的名字',
  `real_name` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '真实姓名（实名认证用，仅管理端可见）',
  `password_hash` varchar(160) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '密码哈希（PBKDF2-SHA256，格式：算法$迭代$盐$哈希，绝不存明文）',
  `phone` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '手机号（可作为登录账号 / 接收球局通知）',
  `email` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '邮箱（可选，用于找回密码）',
  `avatar_url` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '头像图片URL',
  `campus` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '所在校区，如：东校区',
  `college` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '学院，如：计算机学院',
  `grade` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '年级，如：2023',
  `gender` tinyint NOT NULL DEFAULT '0' COMMENT '性别：0-未知 1-男 2-女（用于球局性别限制校验）',
  `reputation_score` int NOT NULL DEFAULT '100' COMMENT '信誉分（初始100）。惰性结算：仅在签到/核销、判定缺席时更新，平时只读不计算；缺席一次 -10 分',
  `credit_level` tinyint NOT NULL DEFAULT '3' COMMENT '信誉等级：1-黑名单 2-观察 3-正常 4-优秀 5-金牌（结算时按分数区间刷新，便于列表排序）',
  `credit_settled_at` datetime DEFAULT NULL COMMENT '信誉分最近一次结算时间（惰性结算水位线，便于排查分数为何未变）',
  `total_game_count` int NOT NULL DEFAULT '0' COMMENT '累计参与球局数（结算时累加，AI信誉画像输入特征）',
  `absent_count` int NOT NULL DEFAULT '0' COMMENT '累计缺席/迟到次数（失信次数，AI画像与自动封禁依据）',
  `skill_level` tinyint NOT NULL DEFAULT '1' COMMENT '球技水平：1-新手 2-初级 3-中级 4-高级 5-大神',
  `ai_profile` json DEFAULT NULL COMMENT 'AI信誉画像结果（含画像分/标签/风险等级/明细；DeepSeek输出或本地加权规则版）',
  `ai_score` int DEFAULT NULL COMMENT 'AI画像评估分（0-150，画像算法输出；供个人主页展示与球局匹配参考）',
  `ai_profile_updated_at` datetime DEFAULT NULL COMMENT 'AI信誉画像最近生成时间（用于24小时缓存判断）',
  `ai_profile_source` varchar(16) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '画像来源：deepseek（大模型）/ rule（本地加权规则降级）',
  `ai_profile_dirty` tinyint NOT NULL DEFAULT '0' COMMENT '待重算标记：1=签到/缺席/退出结算后需要重算画像（后台任务或读取时惰性重算）',
  `ai_profile_trigger` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '最近一次触发重算的原因：checkin/absent/exit/manual/cache_expired',
  `ai_profile_version` int NOT NULL DEFAULT '0' COMMENT '画像版本号：每次重算 +1，便于缓存与审计',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '账号状态：0-禁用 1-正常',
  `last_login_at` datetime DEFAULT NULL COMMENT '最近登录时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间（注册时间）',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `is_deleted` tinyint NOT NULL DEFAULT '0' COMMENT '逻辑删除标记：0-未删除 1-已删除',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_student_no` (`student_no`) COMMENT '学号唯一',
  UNIQUE KEY `uk_user_phone` (`phone`) COMMENT '手机号唯一（NULL 不受唯一约束限制）',
  KEY `idx_user_reputation_score` (`reputation_score`) COMMENT '按信誉分筛选/排序',
  KEY `idx_user_ai_profile_dirty` (`ai_profile_dirty`,`updated_at`) COMMENT '后台重算待刷新画像的用户',
  KEY `idx_user_status` (`status`) COMMENT '按账号状态筛选'
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表：账号、校内属性、信誉分（惰性结算）与 AI 画像';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `t_user`
--

LOCK TABLES `t_user` WRITE;
/*!40000 ALTER TABLE `t_user` DISABLE KEYS */;
INSERT INTO `t_user` VALUES (1,'C293517','月球发起人',NULL,'$2b$12$lQSFfjAmabZsqb5BTJ07mOKYR.ff1qQ7gATooe294G//.JVpeG8FC',NULL,NULL,NULL,'老校区','','',1,100,3,NULL,0,0,1,'{\"tags\": [\"从未缺席\", \"新人球友\"], \"score\": 100, \"source\": \"rule\", \"summary\": \"月球发起人：累计到场 0 次、迟到 0 次、缺席 0 次、退出 0 次（其中临期退出 0 次），守约率 100%。\", \"trigger\": \"manual\", \"ai_score\": null, \"degraded\": true, \"features\": {\"user_id\": 1, \"nickname\": \"月球发起人\", \"keep_rate\": 1.0, \"late_rate\": 0.0, \"late_count\": 0, \"absent_rate\": 0.0, \"cancel_rate\": 0.0, \"leave_count\": 0, \"skill_level\": 1, \"absent_count\": 0, \"signup_total\": 0, \"checked_count\": 0, \"settled_total\": 0, \"reputation_score\": 100, \"cancel_late_count\": 0, \"cancel_early_count\": 0, \"game_created_count\": 0}, \"ai_adjust\": 0, \"breakdown\": [{\"item\": \"按时签到\", \"count\": 0, \"weight\": 2, \"subtotal\": 0}, {\"item\": \"迟到签到\", \"count\": 0, \"weight\": -3, \"subtotal\": 0}, {\"item\": \"已请假\", \"count\": 0, \"weight\": 0, \"subtotal\": 0}, {\"item\": \"无故缺席\", \"count\": 0, \"weight\": -10, \"subtotal\": 0}, {\"item\": \"主动退出\", \"count\": 0, \"weight\": -2, \"subtotal\": 0}, {\"item\": \"临近开球退出(≤2h)\", \"count\": 0, \"weight\": -4, \"subtotal\": 0}], \"score_gap\": 0, \"risk_level\": \"low\", \"rule_score\": 100, \"suggestions\": [\"多参与球局可以提升画像准确度，也更容易被组织者接纳。\"], \"credit_level\": 3, \"generated_at\": \"2026-11-19T13:48:21.786047\", \"reputation_score\": 100, \"credit_level_text\": \"正常\"}',100,'2026-11-19 13:48:22','rule',0,'manual',1,1,'2026-11-19 13:49:50','2026-11-19 13:48:21','2026-11-19 13:49:50',0),(2,'P5067489','带手机号用户',NULL,'$2b$12$edCrxW09UqDgU7/lgWp16e.nzaEarEpcbsJd8dTylB3M2z1t5S7gi','138****0000',NULL,NULL,'老校区',NULL,NULL,0,100,3,NULL,0,0,1,NULL,NULL,NULL,NULL,0,NULL,0,1,'2026-11-19 13:51:31','2026-11-19 13:51:30','2026-11-19 13:51:30',0),(3,'N5068340','无手机号验证',NULL,'$2b$12$ApIfR9jRntahDiDq2gXEgOphyq546wMe2mRPfgiGZVrjGUZpwlE9O',NULL,NULL,NULL,'老校区',NULL,NULL,0,100,3,NULL,0,0,1,NULL,NULL,NULL,NULL,0,NULL,0,1,NULL,'2026-11-19 14:05:41','2026-11-19 14:05:41',0),(4,'a380289','到场的小齐刘海',NULL,'$2b$12$PydcQSz2tYfIzea3ufBH6ejrMd7gtd8wgoYvinEQW6nZ0vypyihYK','1383802892',NULL,NULL,'老校区',NULL,NULL,0,100,3,NULL,0,0,1,NULL,NULL,NULL,NULL,0,NULL,0,1,'2026-11-19 14:06:31','2026-11-19 14:06:30','2026-11-19 14:06:31',0),(5,'b380289','放鸽子的小橘',NULL,'$2b$12$dv3.bHgJl5VCd3ppK5h7j.LPsUbIoSqpWjeIAZTjhLwfzTAD6T8tS','1383802893',NULL,NULL,'老校区',NULL,NULL,0,100,3,NULL,0,0,1,NULL,NULL,NULL,NULL,0,NULL,0,1,'2026-11-19 14:06:32','2026-11-19 14:06:31','2026-11-19 14:06:32',0),(6,'c443418c','月球发起人',NULL,'$2b$12$vrznU2IWkTpSjRDHYCkos.JiEt4N4FbcfLLnuDi.dotvNrvndeqC6','1384434181',NULL,NULL,'老校区',NULL,NULL,0,90,3,'2026-11-19 14:08:37',0,1,1,'{\"tags\": [\"频繁放鸽子\", \"新人球友\"], \"score\": 90, \"source\": \"rule\", \"summary\": \"月球发起人：累计到场 0 次、迟到 0 次、缺席 1 次、退出 0 次（其中临期退出 0 次），守约率 0%。\", \"trigger\": \"absent\", \"ai_score\": null, \"degraded\": true, \"features\": {\"user_id\": 6, \"nickname\": \"月球发起人\", \"keep_rate\": 0.0, \"late_rate\": 0.0, \"late_count\": 0, \"absent_rate\": 1.0, \"cancel_rate\": 0.0, \"leave_count\": 0, \"skill_level\": 1, \"absent_count\": 1, \"signup_total\": 1, \"checked_count\": 0, \"settled_total\": 1, \"reputation_score\": 90, \"cancel_late_count\": 0, \"cancel_early_count\": 0, \"game_created_count\": 1}, \"ai_adjust\": 0, \"breakdown\": [{\"item\": \"按时签到\", \"count\": 0, \"weight\": 2, \"subtotal\": 0}, {\"item\": \"迟到签到\", \"count\": 0, \"weight\": -3, \"subtotal\": 0}, {\"item\": \"已请假\", \"count\": 0, \"weight\": 0, \"subtotal\": 0}, {\"item\": \"无故缺席\", \"count\": 1, \"weight\": -10, \"subtotal\": -10}, {\"item\": \"主动退出\", \"count\": 0, \"weight\": -2, \"subtotal\": 0}, {\"item\": \"临近开球退出(≤2h)\", \"count\": 0, \"weight\": -4, \"subtotal\": 0}], \"score_gap\": 0, \"risk_level\": \"medium\", \"rule_score\": 90, \"suggestions\": [\"报名后请按时到场；确实来不了请提前请假，避免扣除信誉分并被禁赛。\", \"多参与球局可以提升画像准确度，也更容易被组织者接纳。\"], \"credit_level\": 3, \"generated_at\": \"2026-11-19T14:08:36.557112\", \"reputation_score\": 90, \"credit_level_text\": \"正常\"}',90,'2026-11-19 14:08:37','rule',0,'absent',2,1,'2026-11-19 14:07:35','2026-11-19 14:07:34','2026-11-19 14:08:36',0),(7,'a443418a','到场的小齐刘海',NULL,'$2b$12$zQLsWQPegeLpvEpIp30zYeAhdV3GXmWBwqsKQnQ1j.urK8yleEZXi','1384434182',NULL,NULL,'老校区',NULL,NULL,0,90,3,'2026-11-19 14:08:37',0,1,1,'{\"tags\": [\"频繁放鸽子\", \"新人球友\"], \"score\": 90, \"source\": \"rule\", \"summary\": \"到场的小齐刘海：累计到场 0 次、迟到 0 次、缺席 1 次、退出 0 次（其中临期退出 0 次），守约率 0%。\", \"trigger\": \"absent\", \"ai_score\": null, \"degraded\": true, \"features\": {\"user_id\": 7, \"nickname\": \"到场的小齐刘海\", \"keep_rate\": 0.0, \"late_rate\": 0.0, \"late_count\": 0, \"absent_rate\": 1.0, \"cancel_rate\": 0.0, \"leave_count\": 0, \"skill_level\": 1, \"absent_count\": 1, \"signup_total\": 1, \"checked_count\": 0, \"settled_total\": 1, \"reputation_score\": 90, \"cancel_late_count\": 0, \"cancel_early_count\": 0, \"game_created_count\": 0}, \"ai_adjust\": 0, \"breakdown\": [{\"item\": \"按时签到\", \"count\": 0, \"weight\": 2, \"subtotal\": 0}, {\"item\": \"迟到签到\", \"count\": 0, \"weight\": -3, \"subtotal\": 0}, {\"item\": \"已请假\", \"count\": 0, \"weight\": 0, \"subtotal\": 0}, {\"item\": \"无故缺席\", \"count\": 1, \"weight\": -10, \"subtotal\": -10}, {\"item\": \"主动退出\", \"count\": 0, \"weight\": -2, \"subtotal\": 0}, {\"item\": \"临近开球退出(≤2h)\", \"count\": 0, \"weight\": -4, \"subtotal\": 0}], \"score_gap\": 0, \"risk_level\": \"medium\", \"rule_score\": 90, \"suggestions\": [\"报名后请按时到场；确实来不了请提前请假，避免扣除信誉分并被禁赛。\", \"多参与球局可以提升画像准确度，也更容易被组织者接纳。\"], \"credit_level\": 3, \"generated_at\": \"2026-11-19T14:08:36.563179\", \"reputation_score\": 90, \"credit_level_text\": \"正常\"}',90,'2026-11-19 14:08:37','rule',0,'absent',2,1,'2026-11-19 14:07:35','2026-11-19 14:07:35','2026-11-19 14:08:36',0),(8,'b443418b','放鸽子的小橘',NULL,'$2b$12$682aotXtAl32gLCbZlC1CutGi3RMTYXdn1pmJGjU0HotU1Iadonxu','1384434183',NULL,NULL,'老校区',NULL,NULL,0,102,3,'2026-11-19 14:08:30',1,0,1,'{\"tags\": [\"从未缺席\", \"新人球友\"], \"score\": 102, \"source\": \"rule\", \"summary\": \"放鸽子的小橘：累计到场 1 次、迟到 0 次、缺席 0 次、退出 0 次（其中临期退出 0 次），守约率 100%。\", \"trigger\": \"checkin\", \"ai_score\": null, \"degraded\": true, \"features\": {\"user_id\": 8, \"nickname\": \"放鸽子的小橘\", \"keep_rate\": 1.0, \"late_rate\": 0.0, \"late_count\": 0, \"absent_rate\": 0.0, \"cancel_rate\": 0.0, \"leave_count\": 0, \"skill_level\": 1, \"absent_count\": 0, \"signup_total\": 1, \"checked_count\": 1, \"settled_total\": 1, \"reputation_score\": 102, \"cancel_late_count\": 0, \"cancel_early_count\": 0, \"game_created_count\": 0}, \"ai_adjust\": 0, \"breakdown\": [{\"item\": \"按时签到\", \"count\": 1, \"weight\": 2, \"subtotal\": 2}, {\"item\": \"迟到签到\", \"count\": 0, \"weight\": -3, \"subtotal\": 0}, {\"item\": \"已请假\", \"count\": 0, \"weight\": 0, \"subtotal\": 0}, {\"item\": \"无故缺席\", \"count\": 0, \"weight\": -10, \"subtotal\": 0}, {\"item\": \"主动退出\", \"count\": 0, \"weight\": -2, \"subtotal\": 0}, {\"item\": \"临近开球退出(≤2h)\", \"count\": 0, \"weight\": -4, \"subtotal\": 0}], \"score_gap\": 0, \"risk_level\": \"low\", \"rule_score\": 102, \"suggestions\": [\"多参与球局可以提升画像准确度，也更容易被组织者接纳。\"], \"credit_level\": 3, \"generated_at\": \"2026-11-19T14:08:40.293478\", \"reputation_score\": 102, \"credit_level_text\": \"正常\"}',102,'2026-11-19 14:08:40','rule',0,'checkin',2,1,'2026-11-19 14:07:36','2026-11-19 14:07:35','2026-11-19 14:08:40',0),(9,'g614609','发局表单验证',NULL,'$2b$12$O2iKXwDrf//fcPgIT6xRJuRX/Zshi7jU/OqPYUj5F/QF.s1iVV7xi','137614609',NULL,NULL,'老校区',NULL,NULL,0,100,3,NULL,0,0,1,NULL,NULL,NULL,NULL,0,NULL,0,1,'2026-11-19 14:10:16','2026-11-19 14:10:15','2026-11-19 14:10:15',0),(10,'h181133','月球组织者',NULL,'$2b$12$.n4kqzNKT.RqE9jIFtZtGuUWSSJIyZ.93EGm3D4dQFsDzXgXZNUdi','1371811331',NULL,NULL,'老校区',NULL,NULL,0,102,3,'2026-11-19 14:19:44',1,0,1,'{\"tags\": [\"从未缺席\", \"新人球友\"], \"score\": 102, \"source\": \"rule\", \"summary\": \"月球组织者：累计到场 1 次、迟到 0 次、缺席 0 次、退出 0 次（其中临期退出 0 次），守约率 100%。\", \"trigger\": \"async:checkin\", \"ai_score\": null, \"degraded\": true, \"features\": {\"user_id\": 10, \"nickname\": \"月球组织者\", \"keep_rate\": 1.0, \"late_rate\": 0.0, \"late_count\": 0, \"absent_rate\": 0.0, \"cancel_rate\": 0.0, \"leave_count\": 0, \"skill_level\": 1, \"absent_count\": 0, \"signup_total\": 1, \"checked_count\": 1, \"settled_total\": 1, \"reputation_score\": 102, \"cancel_late_count\": 0, \"cancel_early_count\": 0, \"game_created_count\": 1}, \"ai_adjust\": 0, \"breakdown\": [{\"item\": \"按时签到\", \"count\": 1, \"weight\": 2, \"subtotal\": 2}, {\"item\": \"迟到签到\", \"count\": 0, \"weight\": -3, \"subtotal\": 0}, {\"item\": \"已请假\", \"count\": 0, \"weight\": 0, \"subtotal\": 0}, {\"item\": \"无故缺席\", \"count\": 0, \"weight\": -10, \"subtotal\": 0}, {\"item\": \"主动退出\", \"count\": 0, \"weight\": -2, \"subtotal\": 0}, {\"item\": \"临近开球退出(≤2h)\", \"count\": 0, \"weight\": -4, \"subtotal\": 0}], \"score_gap\": 0, \"risk_level\": \"low\", \"rule_score\": 102, \"suggestions\": [\"多参与球局可以提升画像准确度，也更容易被组织者接纳。\"], \"credit_level\": 3, \"generated_at\": \"2026-11-19T14:23:14.424810\", \"reputation_score\": 102, \"credit_level_text\": \"正常\"}',102,'2026-11-19 14:23:14','rule',0,'async:checkin',1,1,'2026-11-19 14:19:43','2026-11-19 14:19:42','2026-11-19 14:23:14',0),(11,'p181133','缺席的小橘',NULL,'$2b$12$vo63lpDzrAeliHBIW/Q0A.WBq8GDZ3wARVg6casZNM2SoTxvdfLHu','1371811332',NULL,NULL,'老校区',NULL,NULL,0,90,3,'2026-11-19 14:19:44',0,1,1,'{\"tags\": [\"频繁放鸽子\", \"新人球友\"], \"score\": 90, \"source\": \"rule\", \"summary\": \"缺席的小橘：累计到场 0 次、迟到 0 次、缺席 1 次、退出 0 次（其中临期退出 0 次），守约率 0%。\", \"trigger\": \"absent\", \"ai_score\": null, \"degraded\": true, \"features\": {\"user_id\": 11, \"nickname\": \"缺席的小橘\", \"keep_rate\": 0.0, \"late_rate\": 0.0, \"late_count\": 0, \"absent_rate\": 1.0, \"cancel_rate\": 0.0, \"leave_count\": 0, \"skill_level\": 1, \"absent_count\": 1, \"signup_total\": 1, \"checked_count\": 0, \"settled_total\": 1, \"reputation_score\": 90, \"cancel_late_count\": 0, \"cancel_early_count\": 0, \"game_created_count\": 0}, \"ai_adjust\": 0, \"breakdown\": [{\"item\": \"按时签到\", \"count\": 0, \"weight\": 2, \"subtotal\": 0}, {\"item\": \"迟到签到\", \"count\": 0, \"weight\": -3, \"subtotal\": 0}, {\"item\": \"已请假\", \"count\": 0, \"weight\": 0, \"subtotal\": 0}, {\"item\": \"无故缺席\", \"count\": 1, \"weight\": -10, \"subtotal\": -10}, {\"item\": \"主动退出\", \"count\": 0, \"weight\": -2, \"subtotal\": 0}, {\"item\": \"临近开球退出(≤2h)\", \"count\": 0, \"weight\": -4, \"subtotal\": 0}], \"score_gap\": 0, \"risk_level\": \"medium\", \"rule_score\": 90, \"suggestions\": [\"报名后请按时到场；确实来不了请提前请假，避免扣除信誉分并被禁赛。\", \"多参与球局可以提升画像准确度，也更容易被组织者接纳。\"], \"credit_level\": 3, \"generated_at\": \"2026-11-19T14:19:43.762649\", \"reputation_score\": 90, \"credit_level_text\": \"正常\"}',90,'2026-11-19 14:19:44','rule',0,'absent',1,1,'2026-11-19 14:19:43','2026-11-19 14:19:42','2026-11-19 14:19:43',0);
/*!40000 ALTER TABLE `t_user` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping routines for database 'campus_ball'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-11-19 15:40:39
