# Gtrack — Import & Equipment Tracking
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY . .

RUN mkdir -p instance/uploads

EXPOSE 8000

# Seed on first run if the database is empty, then serve.
CMD ["sh", "-c", "python seed.py --keep && gunicorn wsgi:app --bind 0.0.0.0:8000 --workers 2 --timeout 120"]
