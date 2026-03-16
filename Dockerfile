FROM python:3.11-slim

WORKDIR /app

# Install system deps for psycopg2 and WeasyPrint (PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    libgdk-pixbuf2.0-0 libffi-dev libxml2 libxslt1.1 \
    libopenjp2-7 libjpeg-dev fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY app/ .

# Create reports directory for PDF storage
RUN mkdir -p /app/reports

# Run as non-root
RUN useradd -m appuser && chown -R appuser /app
USER appuser

EXPOSE 8003

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]