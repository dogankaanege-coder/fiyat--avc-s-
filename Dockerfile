FROM python:3.11-slim

# Install Chromium and dependencies for headless web scraping
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    curl \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libnss3 \
    && rm -rf /var/lib/apt/lists/*

ENV CHROME_BIN=/usr/bin/chromium \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY . /app

EXPOSE 8080

CMD ["python3", "app.py"]
