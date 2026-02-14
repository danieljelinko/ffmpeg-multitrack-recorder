FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg jq && rm -rf /var/lib/apt/lists/*

WORKDIR /tests
COPY tests/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

COPY tests/ .

CMD ["pytest", "-v", "--tb=short", "-x"]
