# 后端容器镜像（常驻模式：本地 / 腾讯云轻量服务器 / 微信云托管 / 任意容器平台）
# 构建：docker build -t yueqi-campus-ball-api .
# 运行：docker run -p 8000:8000 --env-file .env yueqi-campus-ball-api
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    SERVERLESS_MODE=false \
    ENV=prod

# 只装一个 curl 供健康检查用（其余依赖都是纯 Python wheel，无需编译工具链）
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 国内服务器构建加速：优先用清华 PyPI 镜像（海外可用时无副作用）
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# 常驻模式：多 worker + 连接池；进程内定时任务（缺席兜底扫描等）会正常执行
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers"]
