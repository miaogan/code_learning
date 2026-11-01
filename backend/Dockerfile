# r10 容器化交付 · backend 运行镜像
#
# 贯穿契约（与 frontend/nginx.conf、docker-compose.yml 共享，改任一处须三处同改）：
#   服务名 backend / 容器端口 8000 / 健康探针 GET /health / 数据卷挂载点 /data
#
# 构建上下文是 ./backend 子目录（不是仓库根）：.env、本地 *.db、tests/ 根本不会进入上下文，
# 这是「零凭据进镜像」的主边界；backend/.dockerignore 只是纵深防御的第二道。

FROM python:3.13-slim

# DB_PATH 指到卷挂载点，SQLite 落盘才在命名卷里（默认 app.db 会写进容器可写层，down 即丢）。
# PYTHONUNBUFFERED 让 docker logs 实时可见；PYTHONDONTWRITEBYTECODE 避免容器里生成 __pycache__。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DB_PATH=/data/app.db

WORKDIR /app

# 分层顺序不可颠倒：依赖层先于业务代码层，改 app/ 不会触发依赖重装。
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# 非 root 运行 + /data 归属必须在 USER app 之前完成。
# 原因不是运维洁癖：命名卷首次挂载会继承镜像内 /data 的属主，而 app/main.py 的 lifespan
# 启动即 init_db() + question_bank.ensure_seeded()（会写库）。属主错了 → 启动阶段 EACCES
# → 容器起不来 → healthcheck 永不 healthy → frontend 的 service_healthy 门控把整栈挡死。
RUN useradd --uid 10001 --create-home app \
    && mkdir -p /data \
    && chown -R app:app /data

USER app

EXPOSE 8000

# slim 基础镜像没有 curl，探针用标准库 urllib，不为此装包。
# 本条命令与 docker-compose.yml 的 healthcheck 逐字一致（compose 那份会整体覆盖本定义），
# 只允许 interval / start_period / retries 三个参数不同，否则 docker run 与 compose up 的就绪语义分叉。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c 'import urllib.request,sys; sys.exit(0 if urllib.request.urlopen("http://127.0.0.1:8000/health",timeout=3).status==200 else 1)'

# host 必须绑 0.0.0.0（容器内 127.0.0.1 外部不可达）。
# compose 会用 command 覆写为「推导 AI_PROVIDER + exec uvicorn ...」，端口仍以此为准。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
