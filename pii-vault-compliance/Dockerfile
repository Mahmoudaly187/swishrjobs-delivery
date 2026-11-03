FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pii_vault ./pii_vault
COPY scripts ./scripts
COPY data ./data
COPY reports ./reports
COPY pytest.ini Makefile README.md ./
COPY tests ./tests

EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "pii_vault.api:app", "--host", "0.0.0.0", "--port", "8000"]
