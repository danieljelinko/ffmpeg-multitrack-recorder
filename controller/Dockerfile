FROM python:3.11-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        libavdevice-dev \
        libavfilter-dev \
        libopus-dev \
        libvpx-dev \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY controller/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY controller/ .

ENV RECORDINGS_PATH=/recordings/ffmpeg
ENV RECORDER_API_SECRET=changeme
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
