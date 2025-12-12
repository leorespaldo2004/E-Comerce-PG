# Usa una imagen base oficial de Python
# Esto ya incluye Python y las herramientas necesarias
FROM python:3.13-slim

# Define el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copia el archivo de requisitos e instala las dependencias
# Esto se hace primero para aprovechar el cache de Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto de tu código al directorio /app
COPY . .

# Comando para ejecutar la aplicación cuando se inicia el contenedor
# Asegúrate de que 'main.py' sea el nombre de tu archivo principal
CMD ["python", "main.py"]