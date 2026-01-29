FROM mcr.microsoft.com/dotnet/sdk:10.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates postgresql-client jq \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.dotnet/tools:${PATH}"
RUN dotnet tool install -g dotnet-ef --version 10.0.0

WORKDIR /work

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV GIT_REF=latest \
    WAIT_FOR_DB_TIMEOUT=60

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
