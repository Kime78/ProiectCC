# Use the official Microsoft Playwright image which includes Chromium
FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# Ensure stdout and stderr are unbuffered so logs show up immediately in CloudWatch
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY scraper.py .

# We run as a standard Python script
CMD ["python", "scraper.py"]
