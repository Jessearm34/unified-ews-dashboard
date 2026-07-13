FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker app:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --timeout 120 --max-requests 1000 --max-requests-jitter 100"]
