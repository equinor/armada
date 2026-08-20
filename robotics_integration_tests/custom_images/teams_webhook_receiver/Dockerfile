FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4
RUN useradd --create-home appuser
WORKDIR /app
COPY server.py .
USER appuser
EXPOSE 8080
CMD ["python", "-u", "server.py"]
