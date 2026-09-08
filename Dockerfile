# syntax=docker/dockerfile:1.7

FROM python:3.14-slim-trixie AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME=/home/socauto \
    TMPDIR=/tmp \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.11.12 /uv /uvx /bin/
COPY --from=oven/bun:1.3.14 /usr/local/bin/bun /usr/local/bin/bun

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates chromium ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 socauto \
    && useradd --system --uid 10001 --gid socauto --home-dir /home/socauto --shell /usr/sbin/nologin socauto \
    && install --directory --owner=socauto --group=socauto --mode=0700 /app/data /home/socauto \
    && chmod 1777 /tmp

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

COPY package.json bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache bun install --frozen-lockfile --production

COPY alembic.ini ./
COPY migrations ./migrations
COPY signer ./signer
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

USER socauto

FROM oven/bun:1.3.14 AS web-build

WORKDIR /web

COPY web/package.json web/bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache bun install --frozen-lockfile

COPY web ./
RUN bun run build

FROM nginxinc/nginx-unprivileged:stable-alpine AS web

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /web/dist /usr/share/nginx/html
