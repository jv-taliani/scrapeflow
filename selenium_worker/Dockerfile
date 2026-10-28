FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY selenium_worker/requirements.txt ./selenium_worker/requirements.txt
RUN pip install --no-cache-dir -r selenium_worker/requirements.txt

COPY src/ ./src/
COPY selenium_worker/ ./selenium_worker/

ENV PYTHONPATH=/app/src:/app \
    PYTHONUNBUFFERED=1 \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER=/usr/bin/chromedriver

RUN useradd --create-home worker
USER worker

ENTRYPOINT ["python", "-m", "selenium_worker.main"]
