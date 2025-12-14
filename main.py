if __name__ == "__main__":
    import uvicorn
    import os

    # Usar el puerto que asigne la nube (Render) o 10000 por defecto
    port = int(os.environ.get("PORT", 10000))

    uvicorn.run("app.main:app", 
                host="0.0.0.0",     # IMPORTANTE: 0.0.0.0 permite acceso externo
                port=port, 
                reload=False)       # False para producción (es más rápido)