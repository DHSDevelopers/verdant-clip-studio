FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-lite.txt requirements.txt ./
RUN pip install -r requirements-lite.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "web.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
