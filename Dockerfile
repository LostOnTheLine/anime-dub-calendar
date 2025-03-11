FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y git openssh-client curl
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ .
CMD ["python", "metadata_parser.py"]
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
  CMD curl -f http://localhost:5000/ && [ -d /data/.git ] && [ -f /data/metadata.yaml ] || exit 1