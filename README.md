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

## Manual verification: User dropdown

1. Start the app locally and open `http://localhost:8000`.
2. Log in with a test user (or simulate `request.state.user` in middleware) so `current_user` is present.
3. Click the settings (gear) button in the top-right. The dropdown should appear with `Mi Perfil` and `Cerrar Sesión`.
4. If the logged-in user has role `admin`, the `Gestión del Catálogo` entry should be visible.
5. Click outside the dropdown or press `Escape` — the menu should close.

If any behavior differs, inspect the browser console for JS errors and verify the template at `templates/index.html`.
