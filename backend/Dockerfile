FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

COPY . .

EXPOSE 8000

# Shell form (not exec array) so $PORT is expanded at container start.
# Railway (and most PaaS platforms) inject PORT and expect the process to
# bind to it; local `docker run` without PORT set falls back to 8000.
# docker-compose.yml overrides this CMD with an explicit --port 8000 --reload
# command for local development, so this default only matters for
# production/Railway and plain `docker run`.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
