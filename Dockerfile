# Stage 1: Build SvelteKit frontend
FROM node:20-alpine AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY svelte.config.js vite.config.js ./
COPY src/ ./src/
COPY static/ ./static/
RUN npm run build

# Stage 2: Python FastAPI backend
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Python app first, then SvelteKit build (preserves the build)
COPY api/ ./api/
COPY data/ ./data/
COPY charts/ ./charts/
COPY static/.gitkeep ./

# Copy SvelteKit build from stage 1 (overwrites empty static/)
COPY --from=frontend /app/build ./static/

EXPOSE 8000
CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker api.main:app --bind 0.0.0.0:${PORT:-8000} --workers 1 --timeout 120 --max-requests 1000 --max-requests-jitter 100"]