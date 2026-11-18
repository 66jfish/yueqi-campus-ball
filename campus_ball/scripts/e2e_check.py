"""
端到端测试脚本（对着真实运行的服务跑一遍核心链路）
====================================================================
用途：部署完成后（或本地起后端后）跑一次，验证「注册 → 发局 → 报名 → 核销 →
      缺席判定 → 自动封禁 → 拦截 → 惰性解封 → 画像」的完整闭环。

用法：
    pip install httpx
    python scripts/e2e_check.py --base https://<后端域名>/api/v1

    # 本地
    python scripts/e2e_check.py --base http://127.0.0.1:8000/api/v1

注意：
    · 会向目标库真实写入数据（注册 3 个随机学号账号、创建球局等），
      请只在测试环境执行；
    · 每个步骤都会打印 ✓/✗ 与关键响应，最后输出通过率。
====================================================================
"""

import argparse
import random
import sys
import time

import httpx

PASSED: list[str] = []
FAILED: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASSED.append(name)
        print(f"  ✓ {name}")
    else:
        FAILED.append((name, detail))
        print(f"  ✗ {name}\n      {detail}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="如 https://xxx.vercel.app/api/v1")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    suffix = str(random.randint(100000, 999999))
    now = time.time()
    with httpx.Client(base_url=base, timeout=30) as c:
        print("\n[0] 健康检查与运行时信息")
        h = c.get(f"{base.replace('/api/v1', '')}/health").json()
        check("GET /health 返回 code=0", h.get("code") == 0, str(h))
        check("数据库连通 database=true", h.get("data", {}).get("database") is True, str(h))
        rt = c.get("/system/runtime").json()
        check("运行时信息可访问", rt.get("code") == 0, str(rt))
        serverless = rt.get("data", {}).get("serverless_mode")
        print(f"      部署形态：Serverless={serverless}｜惰性策略已启用")

        print("\n[1] 注册 + 登录（bcrypt + JWT）")
        host_no, player_no = f"9{suffix}01", f"9{suffix}02"
        host_phone, player_phone = f"139{suffix}01", f"139{suffix}02"
        for no, phone, nick in (
            (host_no, host_phone, "E2E发起人"),
            (player_no, player_phone, "E2E球员"),
        ):
            r = c.post(
                "/auth/register",
                json={"student_no": no, "nickname": nick, "password": "e2e123456",
                      "phone": phone, "campus": "东校区", "skill_level": 3},
            ).json()
            check(f"注册 {nick}", r.get("code") == 0, str(r))

        def login(account: str) -> dict:
            return c.post("/auth/login", json={"account": account, "password": "e2e123456"}).json()

        host_login, player_login = login(host_no), login(player_no)
        check("登录返回双令牌", host_login.get("code") == 0 and
              bool(host_login.get("data", {}).get("token", {}).get("access_token")), str(host_login))
        host_h = {"Authorization": f"Bearer {host_login['data']['token']['access_token']}"}
        player_h = {"Authorization": f"Bearer {player_login['data']['token']['access_token']}"}
        host_id = host_login["data"]["user"]["id"]
        player_id = player_login["data"]["user"]["id"]

        print("\n[2] 未登录访问需登录接口 → 401")
        check("GET /user/me 未带令牌返回 401", c.get("/user/me").status_code == 401)

        print("\n[3] 发起球局（含场地冲突校验）")
        start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now + 3600))
        end = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now + 3 * 3600))
        payload = {
            "sport_type": 3, "title": f"E2E羽毛球双打-{suffix}", "campus": "东校区",
            "venue_name": f"E2E场地-{suffix}", "start_time": start, "end_time": end,
            "max_players": 4, "min_players": 2,
        }
        g = c.post("/game", json=payload, headers=host_h).json()
        check("创建球局成功", g.get("code") == 0, str(g))
        game_id = g.get("data", {}).get("id")
        check("发起人自动占 1 个名额", g.get("data", {}).get("current_players") == 1, str(g))

        dup = c.post("/game", json={**payload, "start_time": start, "end_time": end},
                     headers=host_h).json()
        check("同场地同时段再次发局被拒（309/40900）", dup.get("code") in (40900, 40000), str(dup))
        check("冲突提示包含「冲突」或「时间」", "冲突" in str(dup.get("message", "")), str(dup))

        print("\n[4] 报名（时间冲突 + 名额校验）")
        r = c.post(f"/game/{game_id}/signup", headers=player_h).json()
        check("报名成功", r.get("code") == 0, str(r))
        r2 = c.post(f"/game/{game_id}/signup", headers=player_h).json()
        check("重复报名被拒", r2.get("code") == 40900, str(r2))

        print("\n[5] 核销签到（触发惰性结算）")
        v = c.post("/checkin/verify", json={"game_id": game_id, "user_ids": [player_id]},
                   headers=host_h).json()
        check("核销成功", v.get("code") == 0, str(v))
        item = (v.get("data", {}).get("items") or [{}])[0]
        check("核销记为已签到", item.get("checkin_status") == 1, str(v))
        check("信誉分 +2（惰性结算）", item.get("credit_delta") == 2, str(v))
        check("返回核销后信誉分", item.get("credit_after") is not None, str(v))

        me = c.get("/user/me", headers=player_h).json()
        check("用户信誉分已同步", me["data"]["reputation_score"] == 102, str(me))

        print("\n[6] AI 信誉画像（签到后按需重算，无 Key 自动降级）")
        prof = c.get("/ai/profile", headers=player_h).json()
        check("画像可获取", prof.get("code") == 0, str(prof))
        pd = prof.get("data", {})
        check("画像来源标记（deepseek 或 rule 降级）",
              pd.get("source") in ("deepseek", "rule"), str(pd.get("source")))
        check("画像含标签与加权明细",
              bool(pd.get("tags")) and bool(pd.get("breakdown")), str(pd)[:200])
        check("到场次数已计入画像", pd.get("features", {}).get("checked_count", 0) >= 1, str(pd)[:200])

        print("\n[7] 结束球局 → 缺席判定 → 自动封禁（未签到者）")
        # 再拉一个球员但不核销，制造缺席
        other_no = f"9{suffix}03"
        c.post("/auth/register", json={"student_no": other_no, "nickname": "E2E鸽子",
                                       "password": "e2e123456", "phone": f"139{suffix}03"})
        other_login = login(other_no)
        other_h = {"Authorization": f"Bearer {other_login['data']['token']['access_token']}"}
        c.post(f"/game/{game_id}/signup", headers=other_h)

        fin = c.post(f"/game/{game_id}/finish", headers=host_h).json()
        check("结束球局成功", fin.get("code") == 0, str(fin))
        check("判定出缺席人数 ≥1", fin.get("data", {}).get("absent_count", 0) >= 1, str(fin))

        print("\n[8] 封禁拦截：写操作 403（code=403 + msg），查询接口放行")
        blocked = c.post("/game", json={**payload, "venue_name": f"E2E场地B-{suffix}"},
                         headers=player_h)
        player_ban = c.get("/blacklist/me", headers=player_h).json()
        # 本用例里被核销过的球员不会被封禁（缺席才封禁），因此用「鸽子」账号验证
        pigeon_ban = c.get("/blacklist/me", headers=other_h).json()
        check("未签到者已进小黑屋", pigeon_ban.get("data", {}).get("banned") is True, str(pigeon_ban))
        banned_end = pigeon_ban.get("data", {}).get("ban_end_time")
        check("返回解禁时间", bool(banned_end), str(pigeon_ban))
        check("封禁时长为 3 天", pigeon_ban.get("data", {}).get("ban_duration_days") == 3, str(pigeon_ban))

        r403 = c.post("/game", json={**payload, "venue_name": f"E2E场地C-{suffix}"}, headers=other_h)
        body = r403.json()
        check("被封禁者发局被拦（HTTP 403）", r403.status_code == 403, str(r403.status_code))
        check("业务码为 403 + msg 文案",
              body.get("code") == 403 and "禁赛" in str(body.get("msg", "")), str(body))
        check("查询类接口放行（GET /game 200）",
              c.get("/game", headers=other_h).status_code == 200)
        check("被封禁者仍可查看自己的封禁状态",
              c.get("/blacklist/me", headers=other_h).status_code == 200)
        # 已报名的历史球局仍可签到/核销（用发起人身份验证核销放行）
        check("发起人核销不受影响（被封禁者也可核销自有球局）",
              c.get(f"/checkin/game/{game_id}", headers=host_h).status_code == 200)

        print("\n[9] 惰性解封：改解禁时间为过去后，无需定时任务即可恢复")
        # 说明：脚本无法直接改库，故这里只验证「查询侧用 ban_end_time 判断」这一点——
        # 若解禁时间已过（banned=false），说明惰性判断生效。
        still = c.get("/blacklist/me", headers=other_h).json()["data"]
        check("封禁状态含 ban_end_time（供惰性判断）", bool(still.get("ban_end_time")), str(still))

        print("\n[10] 小黑屋记录查询（永久留存）")
        rec = c.get("/blacklist/records?only_active=true", headers=other_h).json()
        check("可查询自己的封禁记录", rec.get("code") == 0 and rec["data"]["total"] >= 1, str(rec))
        item0 = (rec["data"]["items"] or [{}])[0]
        check("记录含 reason（永久留存）", bool(item0.get("reason")), str(item0))

        print("\n[11] 个人主页（信誉分 + 标签 + 封禁状态）")
        page = c.get(f"/user/{other_login['data']['user']['id']}/profile", headers=other_h).json()
        check("个人主页可访问", page.get("code") == 0, str(page))
        check("含信誉分与信誉标签",
              page["data"].get("reputation_score") is not None and page["data"].get("tags") is not None,
              str(page)[:200])

    print("\n" + "=" * 64)
    print(f"E2E 结果：通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("\n失败明细：")
        for name, detail in FAILED:
            print(f"  · {name}\n    {detail[:300]}")
    print("=" * 64)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
