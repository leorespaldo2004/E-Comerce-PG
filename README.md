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

## Manual verification: Favorites

1. Log in and ensure your user document contains a `favorites` array (can be empty).
2. Visit the home page and click the heart icon on a product card. The icon should fill and turn red immediately (optimistic UI).
3. Confirm the server responded successfully; if so the icon remains filled; on failure it reverts and an alert is shown.
4. Visit `/favorites` to see the filtered list of products that you favorited.

API endpoint: `POST /api/v1/users/favorites/{product_id}` toggles favorite state for the authenticated user.
