FROM python:3.13-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends libarchive13t64 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app
RUN mkdir -p /work /var/lib/telegram-bot-api && chown 101:101 /work /var/lib/telegram-bot-api
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 101:101
CMD ["python", "bot.py"]
