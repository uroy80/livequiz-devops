FROM python:3.13-slim
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin livequiz
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ARG APP_VERSION=dev
ARG BUILD_NUMBER=local
ARG GIT_COMMIT=local
ENV APP_VERSION=${APP_VERSION} BUILD_NUMBER=${BUILD_NUMBER} GIT_COMMIT=${GIT_COMMIT} PYTHONUNBUFFERED=1 HOME=/tmp
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD ["python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
# one worker keeps all live games in one process; threads serve the WebSocket connections
CMD ["gunicorn", "--worker-class", "gthread", "--workers", "1", "--threads", "200", "--bind", "0.0.0.0:8000", "app:app"]
