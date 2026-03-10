FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copier tout le code
COPY . .

# Définir le répertoire de travail sur le backend où se trouve main.py
WORKDIR /app/backend

# Exposer le port
EXPOSE 8000

# Lancer l'application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
