"""Router agrupador v1: registra rutas v1 en la app principal."""

def include_v1_routes(app):
    """Register v1 routers on the FastAPI app."""
    try:
        from .endpoints import products as products_module
        app.include_router(products_module.router, prefix="/api/v1")
        # Also include auth endpoints
        from .endpoints import auth as auth_module
        app.include_router(auth_module.router, prefix="/api/v1")
        # Include users endpoints
        from .endpoints import users as users_module
        app.include_router(users_module.router, prefix="/api/v1")
    except Exception as e:
        print(f"Warning: could not include v1 routes: {e}")
    return None
