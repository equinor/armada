FROM mcr.microsoft.com/dotnet/sdk:8.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates postgresql-client \
 && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.dotnet/tools:${PATH}"
RUN dotnet tool install -g dotnet-ef

WORKDIR /work

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV GIT_REF=main \
    WAIT_FOR_DB_TIMEOUT=60

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
