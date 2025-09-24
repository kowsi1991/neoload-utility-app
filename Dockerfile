# Use a small official Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy and install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Expose port used by the app
EXPOSE 8080

# Run with gunicorn (4 workers). NeoloadUtility must provide `app` variable.
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "NeoloadUtility:app"]
