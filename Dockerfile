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
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
ENV DATABASE_URL=postgresql://ytdb:ytdb@postgres:5432/ytdb
EXPOSE 8000
CMD ["ytdb", "serve", "--host", "0.0.0.0", "--port", "8000"]
