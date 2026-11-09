FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY fixtures/ ./fixtures/
RUN useradd --create-home --uid 10001 appuser
USER 10001
EXPOSE 8000
CMD ["uvicorn", "--app-dir", "app", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
