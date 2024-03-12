FROM python:3.12-slim

WORKDIR /app

COPY ./src/requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt

COPY ./src/main.py /app/

CMD ["python", "main.py"]