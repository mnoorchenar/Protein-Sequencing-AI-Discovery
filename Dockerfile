FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all app files (templates, static, etc.)
COPY . .

# Expose port
EXPOSE 7860

# Set environment variable
ENV PYTHONUNBUFFERED=1

# Run the application
CMD ["python", "app.py"]
