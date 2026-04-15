FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Railway provides $PORT; default to 8000 for local dev
ENV PORT=8000

EXPOSE ${PORT}

CMD uvicorn api.main:app --host 0.0.0.0 --port $PORT
