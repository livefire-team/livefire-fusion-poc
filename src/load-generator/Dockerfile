FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/livefire-team/livefire-fusion-poc"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY loadgen/ loadgen/
RUN useradd --create-home --uid 10001 appuser
USER 10001
CMD ["python", "-m", "loadgen"]
