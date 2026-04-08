FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
RUN groupadd -r flinttrade && useradd -r -g flinttrade flinttrade
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/ packages/
COPY .env.example .env.example
RUN mkdir -p /data/flinttrade/audit && chown -R flinttrade:flinttrade /data/flinttrade
ENV PYTHONUNBUFFERED=1
ENV AUDIT_LOG_DIR=/data/flinttrade/audit
USER flinttrade
CMD ["python", "packages/core/src/app.py"]
