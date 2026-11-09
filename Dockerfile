# syntax=docker/dockerfile:1

# ---- Stage 1: compile Tailwind CSS with the standalone CLI (no Node) ----
FROM python:3.12-slim-bookworm AS css
ARG TAILWIND_VERSION=v4.1.11
ARG TARGETARCH
RUN case "$TARGETARCH" in arm64) arch=arm64 ;; *) arch=x64 ;; esac \
 && python -c "import urllib.request,sys; urllib.request.urlretrieve(sys.argv[1], '/usr/local/bin/tailwindcss')" \
      "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-${arch}" \
 && chmod +x /usr/local/bin/tailwindcss
WORKDIR /src
COPY . .
RUN tailwindcss -i assets/css/input.css -o /out/app.css --minify

# ---- Stage 2: runtime ----
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    DATA_DIR=/app/data
WORKDIR /app
RUN useradd --create-home --uid 1000 app
COPY requirements.txt .
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10
RUN pip install -r requirements.txt
COPY . .
COPY --from=css /out/app.css static/css/app.css
RUN sed -i 's/\r$//' docker/*.sh scripts/*.sh \
 && SECRET_KEY=build-only python manage.py collectstatic --noinput \
 && mkdir -p /app/data/db /app/data/media /app/data/private /app/data/backups /app/data/logs \
 && chown -R app:app /app/data
USER app
EXPOSE 8000
CMD ["sh", "docker/app-start.sh"]
