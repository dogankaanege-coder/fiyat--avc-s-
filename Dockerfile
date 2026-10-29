FROM python:3.11-slim

# Chromium ve headless tarayıcı bağımlılıkları
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
    PORT=10000

WORKDIR /app

# Önce gereksinimleri kur (curl_cffi)
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Tüm kodları kopyala
COPY . /app

EXPOSE 10000

CMD ["python3", "app.py"]
