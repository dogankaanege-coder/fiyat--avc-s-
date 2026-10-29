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

# Hugging Face Spaces için standart non-root kullanıcı (UID 1000)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    CHROME_BIN=/usr/bin/chromium \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR $HOME/app

COPY --chown=user:user . $HOME/app

EXPOSE 7860

CMD ["python3", "app.py"]
