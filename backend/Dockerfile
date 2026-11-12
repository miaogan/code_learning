# r10 容器化交付 · backend 运行镜像
#
# 贯穿契约（与 frontend/nginx.conf、docker-compose.yml 共享，改任一处须三处同改）：
#   服务名 backend / 容器端口 8000 / 健康探针 GET /health / 数据卷挂载点 /data
#
# 构建上下文是 ./backend 子目录（不是仓库根）：.env、本地 *.db、tests/ 根本不会进入上下文，
# 这是「零凭据进镜像」的主边界；backend/.dockerignore 只是纵深防御的第二道。
#
# r98：数据层改为 PostgreSQL，容器**不再持有任何持久状态**——数据库在 postgres 服务里，
# 连接串由 compose 通过 DATABASE_URL 注入。`/data` 仍在：给临时产物留一个可写目录，
# 也避免早期镜像里 `/data` 属主规则被误删后，升级卷挂载的人踩到 EACCES。

FROM python:3.13-slim

# PYTHONUNBUFFERED 让 docker logs 实时可见；PYTHONDONTWRITEBYTECODE 避免容器里生成 __pycache__。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 分层顺序不可颠倒：依赖层先于业务代码层，改 app/ 不会触发依赖重装。
#
# PIP_INDEX_URL 是**可选**构建参数，默认官方源。国内网络拉 pypi.org 常掉到几十 kB/s，
# 装一次依赖能拖到半小时；此时用镜像源构建即可，不改代码逻辑：
#   docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple backend
# 或写进仓库根 .env（compose 会把它透传给 build.args）。
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt ./
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt

COPY app/ ./app/

# 非 root 运行 + /data 归属必须在 USER app 之前完成。
# r98 起业务数据在 PostgreSQL，/data 只承载临时产物；这条规则保留是因为一旦有人重新挂载
# 命名卷到 /data，属主错了就是 EACCES —— 这类错误只在容器里出现，本地永远复现不了。
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
