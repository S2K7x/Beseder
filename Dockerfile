# Beseder: one container, works on a Raspberry Pi (arm64) and on any x86 machine.
FROM python:3.12-slim

# Set to "true" to bundle the Claude Code CLI ("Claude Code on the Pi" AI provider).
ARG WITH_CLAUDE_CLI=false

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BESEDER_HOST=0.0.0.0 \
    BESEDER_PORT=8000 \
    BESEDER_DATA_DIR=/data \
    BESEDER_IN_DOCKER=1 \
    CLAUDE_CONFIG_DIR=/data/claude

RUN if [ "$WITH_CLAUDE_CLI" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
      && npm install -g @anthropic-ai/claude-code \
      && npm cache clean --force \
      && rm -rf /var/lib/apt/lists/*; \
    fi

RUN useradd --create-home --uid 1000 beseder \
    && mkdir -p /data \
    && chown beseder:beseder /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY beseder ./beseder
COPY web ./web

USER beseder
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["python", "-m", "beseder"]
