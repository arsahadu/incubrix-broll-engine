
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FFMPEG_BINARY=/usr/bin/ffmpeg \
    FFPROBE_BINARY=/usr/bin/ffprobe \
    TTS_ENGINE=espeak \
    ESPEAK_VOICE=en-in \
    HF_HOME=/models/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    libass9 \
    fontconfig \
    fonts-dejavu-core \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend ./frontend

RUN mkdir -p /workspace/outputs /models/huggingface

EXPOSE 8000 8501

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
