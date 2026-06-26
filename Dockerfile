FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY scripts ./scripts
RUN chmod +x /app/scripts/entrypoint.sh
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
ENV DATABASE_URL=postgresql://ytdb:ytdb@postgres:5432/ytdb
ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
