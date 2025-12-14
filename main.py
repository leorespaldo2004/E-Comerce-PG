if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", 
                host="localhost", 
                port=8000, 
                #log_level="info",
                reload=True)

# Activar entorno .\venv\Scripts\activate
