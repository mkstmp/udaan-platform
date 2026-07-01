FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
# Build context is the repo root (see cloudbuild.yaml: -f backend/Dockerfile .)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY frontend ./frontend
# Cloud Run sets $PORT; bind to it.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
