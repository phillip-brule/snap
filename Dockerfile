FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 xxd \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=run.py
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["sh", "-c", "python -c 'from app import create_app; from app.seed import seed; app=create_app(); app.app_context().push(); seed()' && gunicorn -b 0.0.0.0:5000 'run:app'"]
