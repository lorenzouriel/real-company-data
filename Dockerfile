FROM python:3.11-slim

WORKDIR /app

# ODBC Driver 18 for SQL Server (required by pyodbc for the SQL Server sink)
RUN apt-get update && apt-get install -y --no-install-recommends curl unixodbc-dev \
    && curl -sSL https://packages.microsoft.com/keys/microsoft.asc -o /etc/apt/trusted.gpg.d/microsoft.asc \
    && curl -sSL https://packages.microsoft.com/config/debian/12/prod.list -o /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY rcd_data/ ./rcd_data/

RUN pip install --no-cache-dir -e .

ENTRYPOINT ["rcd-data"]
