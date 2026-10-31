# The referee as a container, for the G2 Container Apps Job. The tag must match the pinned playwright version.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" \
    > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /referee
COPY referee/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY journeys/ ./journeys/
COPY referee/assert_order.py ./referee/
USER pwuser
