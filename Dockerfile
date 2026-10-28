FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 ticketoracle \
    && useradd --uid 10001 --gid ticketoracle --no-create-home ticketoracle \
    && mkdir /app/runtime \
    && chown ticketoracle:ticketoracle /app/runtime

COPY app.py app_hardened.py docker_run.py structured_lab.py ./
COPY static/ ./static/

# Runtime logs go here; application code stays read-only.
WORKDIR /app/runtime
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/docker_run.py"]
