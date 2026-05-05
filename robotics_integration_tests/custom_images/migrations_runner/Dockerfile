FROM mcr.microsoft.com/dotnet/sdk:10.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates postgresql-client jq \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user to run migrations
RUN groupadd --system --gid 1001 runner \
    && useradd --system --uid 1001 --gid runner --create-home --home-dir /home/runner --shell /bin/bash runner \
    && mkdir -p /work \
    && chown -R runner:runner /work

USER runner

ENV PATH="/home/runner/.dotnet/tools:${PATH}"
RUN dotnet tool install -g dotnet-ef --version 10.0.0

WORKDIR /work

COPY --chown=runner:runner entrypoint.sh /usr/local/bin/entrypoint.sh
USER root
RUN chmod +x /usr/local/bin/entrypoint.sh
USER runner

ENV GIT_REF=latest \
    WAIT_FOR_DB_TIMEOUT=60

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
