FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY . .
RUN useradd --create-home crew
USER crew
EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
