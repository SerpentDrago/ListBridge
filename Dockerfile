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

# Patch pyalexatodo 0.2.0 upstream typing bug (ListInfo[ListInfo] & list[ListItem]) at build time
RUN python -c 'import os, re, site; \
pkg_dir = os.path.join(site.getsitepackages()[0], "pyalexatodo"); \
[ ( \
    open(os.path.join(r, f), "w", encoding="utf-8").write( \
        "from __future__ import annotations\nimport typing\n" + \
        re.sub(r"(?<![\w\.])list\[", "typing.List[", \
            open(os.path.join(r, f), "r", encoding="utf-8").read() \
            .replace("ListInfo[ListInfo]", "typing.List[ListInfo]") \
        ) + "\n" \
    ) \
) for r, _, files in os.walk(pkg_dir) for f in files if f.endswith(".py") ]'

# Copy the sync script and create the persistent /data volume mount point
COPY sync.py /app/sync.py
RUN mkdir -p /data

VOLUME ["/data"]

CMD ["python", "-u", "/app/sync.py"]
