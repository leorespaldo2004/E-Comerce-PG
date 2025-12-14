# 🧪 Comandos de prueba

Para instalar en tu entorno local (PowerShell):

python -m venv .venv
; .venv\\Scripts\\Activate.ps1
; pip install --upgrade pip
; pip install -r requirements.txt

# Opción 1: con Dockerfile (si quieres construir la imagen Docker)
; docker build -t ecommerce-pg:latest .
; docker run -p 8000:8000 ecommerce-pg:latest

# Opción 2: con uvicorn directamente (en entorno virtual)
; python main.py
# o
; uvicorn main:app --reload --host localhost --port 8000
