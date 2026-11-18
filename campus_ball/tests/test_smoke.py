"""冒烟测试：不依赖 MySQL，验证应用能正常启动、路由/开源文档能正常生成"""

from fastapi.testclient import TestClient

from app.core.constants import CheckinStatus, map_credit_level
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.main import app


def test_health_endpoint():
    """健康检查接口可访问（数据库不可用时返回 degraded 而不是崩溃）"""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "database" in body["data"]


def test_openapi_can_generate():
    """所有路由都能生成 OpenAPI，说明导入与依赖注入没有问题"""
    with TestClient(app) as client:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json()["paths"]
        assert "/api/v1/auth/login" in paths
        assert "/api/v1/game" in paths
        assert "/api/v1/checkin/checkin" in paths


def test_auth_required_for_protected_endpoint():
    """未带 Token 访问需要登录的接口，应返回 401（自定义异常处理器生效）"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/user/me")
        assert resp.status_code == 401
        assert resp.json()["code"] == 40100


def test_password_hash_and_verify():
    """密码使用 bcrypt 加密存储，可往返校验"""
    hashed = hash_password("123456")
    assert hashed.startswith("$2b$")      # bcrypt 哈希
    assert hashed != "123456"
    assert verify_password("123456", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_jwt_round_trip():
    """JWT 签发与解析一致"""
    token = create_access_token(42)
    payload = decode_token(token)
    assert payload["sub"] == "42"


def test_credit_level_mapping():
    """信誉分 -> 等级 映射（惰性结算时使用）；初始分 100 必须是 NORMAL(3)，与库默认值一致"""
    assert map_credit_level(130).name == "GOLD"
    assert map_credit_level(115).name == "GOOD"
    assert map_credit_level(100).name == "NORMAL"
    assert map_credit_level(70).name == "WATCH"
    assert map_credit_level(30).name == "BLACKLIST"
    assert int(map_credit_level(100)) == 3  # 与 t_user.credit_level 默认值一致


def test_credit_rules_exist():
    """信誉分规则表覆盖签到/迟到/缺席/请假四种结算场景"""
    from app.core.constants import CREDIT_RULES

    assert CREDIT_RULES[CheckinStatus.CHECKED] == 2
    assert CREDIT_RULES[CheckinStatus.LATE] == -3
    assert CREDIT_RULES[CheckinStatus.ABSENT] == -10
    assert CREDIT_RULES[CheckinStatus.LEAVE] == 0
