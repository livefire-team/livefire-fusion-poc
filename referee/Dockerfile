# The Referee as a container: the G2 Container Apps Job (job-referee). The tag must match the pinned playwright version.
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble
LABEL org.opencontainers.image.source="https://github.com/livefire-team/livefire-fusion-poc"
# Security updates for the base layer, then Microsoft ODBC Driver 18 for the SQL check. The Microsoft signing key is
# checked against its published fingerprint before it is trusted.
ARG MS_SIGNING_FINGERPRINT=BC528686B50D79E339D3721CEB3E94ADBE1229CF
RUN set -eu \
 && apt-get update && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
 && export GNUPGHOME="$(mktemp -d)" \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc -o /tmp/microsoft.asc \
 && fpr="$(gpg --batch --show-keys --with-colons /tmp/microsoft.asc | awk -F: '$1 == "fpr" { print $10; exit }')" \
 && if [ "$fpr" != "$MS_SIGNING_FINGERPRINT" ]; then echo "Microsoft key fingerprint mismatch: $fpr" >&2; exit 1; fi \
 && gpg --batch --dearmor -o /usr/share/keyrings/microsoft.gpg /tmp/microsoft.asc \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" \
    > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc \
 && apt-get purge -y --auto-remove gnupg \
 && rm -rf "$GNUPGHOME" /tmp/microsoft.asc /var/lib/apt/lists/*
WORKDIR /referee
COPY referee/requirements.txt ./referee/
RUN pip install --no-cache-dir --break-system-packages -r referee/requirements.txt
COPY journeys/ ./journeys/
COPY referee/assert_order.py referee/run.py ./referee/
ARG GIT_SHA=unknown
ENV JOURNEY_COMMIT=$GIT_SHA PYTHONUNBUFFERED=1
USER pwuser
CMD ["python", "referee/run.py"]
