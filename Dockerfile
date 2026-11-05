FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OUTPUT_DIR=/data/output CHECKPOINT_PATH=/data/checkpoints.db
RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini docker-entrypoint.sh ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir ".[postgres]"
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready').status==200 else 1)"
ENTRYPOINT ["./docker-entrypoint.sh"]
