FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY api/ ./api/
COPY data/ ./data/
COPY charts/ ./charts/
COPY static/ ./static/
COPY refresh/ ./refresh/
COPY scripts/ ./scripts/
COPY refresh_all.py check_freshness.py ./

RUN date > /app/.build_ts

CMD ["sh", "-c", "PORT=${PORT:-8000} && uvicorn api.main:app --host 0.0.0.0 --port $PORT --log-level info --no-access-log"]
