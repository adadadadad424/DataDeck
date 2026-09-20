FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    AUTH_REQUIRED=true \
    PORT=8501

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libffi8 \
    libjpeg62-turbo \
    libopenjp2-7 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system datadeck \
    && useradd --system --gid datadeck --create-home datadeck

WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --requirement requirements.txt

COPY --chown=datadeck:datadeck main.py ./
COPY --chown=datadeck:datadeck production_start.py ./
COPY --chown=datadeck:datadeck core ./core
COPY --chown=datadeck:datadeck billing ./billing
COPY --chown=datadeck:datadeck .streamlit/config.toml ./.streamlit/config.toml

USER datadeck
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:${PORT}/_stcore/health || exit 1

CMD ["python", "production_start.py"]
