FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y git openssh-client
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ .
CMD ["python", "metadata_parser.py"]