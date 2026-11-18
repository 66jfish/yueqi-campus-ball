"""
pytest 全局夹具
====================================================================
把「与单个测试用例无关、但会影响所有用例的运行时开关」集中在这里，
避免每个测试文件重复配置。

当前配置：
    AI_PROFILE_ASYNC_REFRESH = False
        结算后「立刻异步重算画像」在测试中统一关闭。原因：
          1. 测试库是单连接的内存 SQLite（StaticPool），后台任务与测试用例
             并发争用同一连接会互相阻塞（生产环境是连接池，不存在该问题）；
          2. 异步任务的执行时机不确定，会让「dirty 标记」类断言产生随机失败。
        异步链路本身由 tests/test_ai_profile.py::test_async_refresh_scheduler_runs
        显式打开并等待任务完成来验证，不依赖这里。
====================================================================
"""

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True)
def _disable_async_profile_refresh(monkeypatch):
    """统一关闭「结算后立即异步重算画像」，保证测试确定性（见文件头说明）"""
    monkeypatch.setattr(settings, "AI_PROFILE_ASYNC_REFRESH", False)
    yield
