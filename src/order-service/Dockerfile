FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.source="https://github.com/livefire-team/livefire-fusion-poc"
# Microsoft ODBC Driver 18 for SQL Server, needed by pyodbc.
# The Microsoft package signing key is checked against its published fingerprint before it is trusted;
# the build fails if it does not match. curl and gnupg are only needed here and are purged afterwards
# (ca-certificates stays: the ODBC driver uses the system CA store for TLS to Azure SQL).
ARG MS_KEY_FPR=BC528686B50D79E339D3721CEB3E94ADBE1229CF
RUN set -eu \
 && apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && export GNUPGHOME="$(mktemp -d)" \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc -o /tmp/microsoft.asc \
 && gpg --batch --show-keys /tmp/microsoft.asc \
 && gpg --batch --show-keys --with-colons /tmp/microsoft.asc > /tmp/microsoft.keys \
 && npub="$(grep -c '^pub:' /tmp/microsoft.keys)" \
 && fpr="$(awk -F: '$1 == "fpr" { print $10; exit }' /tmp/microsoft.keys)" \
 && echo "microsoft.asc: $npub key(s), primary fingerprint $fpr" \
 && if [ "$npub" != "1" ] || [ "$fpr" != "$MS_KEY_FPR" ]; then \
      echo "ERROR: Microsoft signing key fingerprint mismatch (expected $MS_KEY_FPR)" >&2; exit 1; \
    fi \
 && gpg --batch --dearmor -o /usr/share/keyrings/microsoft-prod.gpg /tmp/microsoft.asc \
 && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list -o /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && apt-get purge -y --auto-remove curl gnupg \
 && dpkg -s msodbcsql18 > /dev/null \
 && rm -rf "$GNUPGHOME" /tmp/microsoft.asc /tmp/microsoft.keys /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
RUN useradd --create-home --uid 10001 appuser
USER 10001
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
