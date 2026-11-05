# Docker Dashboard - lists all containers, start/stop/restart, links + ping.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install --no-cache-dir fastapi==0.115.* "uvicorn[standard]==0.32.*" docker==7.* httpx==0.27.*
WORKDIR /app
COPY app.py db.py schema.sql ./
COPY static ./static
EXPOSE 9000
CMD ["python", "app.py"]