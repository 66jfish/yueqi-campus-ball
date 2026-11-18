"""
Vercel Serverless 入口（Mangum 适配 ASGI → Lambda/Serverless Function）
====================================================================
Vercel 的 Python Runtime 会加载本文件并调用 `handler`；
Mangum 把 FastAPI 的 ASGI 应用适配成 Vercel 需要的处理函数。

关键点：
    1. lifespan="off"：
       Serverless 每次调用是独立容器，进程内的后台定时任务（asyncio 循环）不可能常驻，
       因此关闭 lifespan 侧的定时任务，改为「惰性判断 + 定时 Cron 调接口」的方式：
         - 小黑屋是否仍在封禁：查询时用 ban_end_time > NOW() 惰性判定（不依赖任何任务）
         - 球局漏判缺席：读取球局时惰性补判 + Vercel Cron 每日兜底调用扫描接口
         - AI 画像重算：读取画像时按 dirty 标记重算 + Cron 兜底
    2. 数据库连接池：Serverless 场景使用 NullPool（每次请求新建/归还连接），
       避免容器冻结后残留失效连接；TiDB Cloud 强制 TLS，按配置注入 SSL 参数。
    3. 冷启动：引擎在模块级创建（同一容器内复用），不会每次请求都建连接池。
====================================================================
"""

import os
import sys

# 把项目根目录加入 import 路径，保证 app.* 可被导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mangum import Mangum  # noqa: E402

from app.main import app  # noqa: E402

handler = Mangum(app, lifespan="off")

# 本地调试：python api/index.py 后访问 http://127.0.0.1:8000/docs
if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
