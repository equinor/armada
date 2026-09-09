FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
RUN useradd --create-home appuser
WORKDIR /app
COPY server.py .
USER appuser
EXPOSE 8080
CMD ["python", "-u", "server.py"]
