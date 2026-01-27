FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY bot.py /app/bot.py
COPY brain_client.py /app/brain_client.py
COPY mood_flow.py /app/mood_flow.py
COPY config.py /app/config.py
COPY formatters.py /app/formatters.py
COPY scheduler.py /app/scheduler.py
COPY handlers.py /app/handlers.py
COPY bot_helpers.py /app/bot_helpers.py
COPY vision /app/vision

CMD ["python", "/app/bot.py"]
