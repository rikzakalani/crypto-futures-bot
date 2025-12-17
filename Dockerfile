FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY bot/ .

ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
