FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ ./api/
COPY data/ ./data/
COPY charts/ ./charts/
COPY static/ ./static/

RUN date > /app/.build_ts

CMD ["sh", "-c", "PORT=${PORT:-8000} && echo \"Binding to $PORT\" && uvicorn api.main:app --host 0.0.0.0 --port $PORT --log-level info"]
