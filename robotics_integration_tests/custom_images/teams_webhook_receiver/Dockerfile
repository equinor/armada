FROM python:3.14-slim
RUN useradd --create-home appuser
WORKDIR /app
COPY server.py .
USER appuser
EXPOSE 8080
CMD ["python", "-u", "server.py"]
