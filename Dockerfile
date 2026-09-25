FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# libpq-dev : en-têtes PostgreSQL nécessaires à la compilation de certaines
# dépendances transitives ; build-essential : compilateur C, retiré du même
# calque pour garder l'image finale légère n'est pas fait ici par choix de
# simplicité (une seule étape, plus facile à maintenir qu'un build multi-
# étapes pour une équipe qui découvre Docker).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
