FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install all dependencies (torch excluded — stub mode active until dedicated ML service)
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST=1
COPY . .

EXPOSE 8000
COPY start.sh .
RUN chmod +x start.sh
CMD ["./start.sh"]
