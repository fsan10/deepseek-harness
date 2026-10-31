FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 每次正式部署由 deploy.ps1 注入构建指纹，避免代码目录更新后误复用旧镜像。
ARG COFFICE_BUILD_REV=unknown
LABEL org.opencontainers.image.revision="${COFFICE_BUILD_REV}"
ENV COFFICE_BUILD_REV=${COFFICE_BUILD_REV}

COPY apps/fund_split_adjust/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt \
    && useradd --create-home --uid 10001 coffice

COPY --chown=coffice:coffice apps /app/apps
COPY --chown=coffice:coffice etl /app/etl
COPY --chown=coffice:coffice sql /app/sql
COPY --chown=coffice:coffice scripts /app/scripts

RUN mkdir -p /app/.uploads/file_ingest /app/apps/fund_split_adjust/uploads \
    && chown -R coffice:coffice /app/.uploads /app/apps/fund_split_adjust/uploads

USER coffice

EXPOSE 8770 8101

CMD ["python", "-m", "apps.fund_split_adjust.server", "--bind", "0.0.0.0", "--port", "8770"]
