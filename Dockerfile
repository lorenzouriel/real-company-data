FROM python:3.11-slim-bookworm

WORKDIR /app

# ODBC Driver 18 for SQL Server (required by pyodbc for the SQL Server sink).
# Pinned to -bookworm (Debian 12) above to match the debian/12 repo config
# below — the floating python:3.11-slim tag has since moved to Debian 13
# (trixie), which doesn't have a matching Microsoft repo and breaks this.
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg unixodbc-dev \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y curl gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY rcd_data/ ./rcd_data/

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["rcd-data"]
