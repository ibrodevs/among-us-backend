FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY . .
# Static collection needs no live credentials or database connection.
RUN DJANGO_DEBUG=true DJANGO_SECRET_KEY=build-only-never-a-runtime-secret python manage.py collectstatic --noinput \
    && useradd --create-home crew
USER crew
EXPOSE 8000
STOPSIGNAL SIGTERM
CMD ["/app/scripts/container-entrypoint.sh"]
