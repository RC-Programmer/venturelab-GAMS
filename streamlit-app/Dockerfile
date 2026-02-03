FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY .streamlit .streamlit
COPY app.py .

ENV PORT=8501

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:${PORT}/_stcore/health || exit 1

CMD streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0
