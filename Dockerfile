FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CRYPTO_ADMIN_HOST=0.0.0.0 \
    CRYPTO_ADMIN_PORT=8000 \
    CRYPTO_ADMIN_DB_PATH=/var/lib/crypto-admin/crypto_admin.sqlite3

WORKDIR /app

RUN groupadd --gid 10001 crypto-admin \
    && useradd --uid 10001 --gid crypto-admin --no-create-home crypto-admin \
    && install -d -o crypto-admin -g crypto-admin /var/lib/crypto-admin

COPY --chown=crypto-admin:crypto-admin app.py calculations.py db.py ./
COPY --chown=crypto-admin:crypto-admin static ./static

USER crypto-admin

EXPOSE 8000

CMD ["python", "app.py"]
