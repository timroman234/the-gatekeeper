FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["sh", "-c", "streamlit run app/main.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
