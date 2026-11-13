FROM python:3.12-slim

# Prevent Python from writing .pyc files and force unbuffered stdout/stderr logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    LIST_NAMES="Grocery" \
    SYNC_INTERVAL=60

WORKDIR /app

# Install Python dependencies into the image
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the sync script and create the persistent /data volume mount point
COPY sync.py /app/sync.py
RUN mkdir -p /data

VOLUME ["/data"]

CMD ["python", "-u", "/app/sync.py"]
