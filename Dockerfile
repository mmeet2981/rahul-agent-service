FROM python:3.11-slim

# Copy the uv binary from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory and environment variables
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# Install system dependencies for OpenCV, AV, PyMuPDF, yoyo-migrations, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies using uv (utilizing caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-install-project

# Copy the rest of the application code
COPY . .

# Install the project itself (if applicable) and generate virtualenv paths
RUN uv sync --frozen --no-cache

# Expose FastAPI port
EXPOSE 3030

# Default command starts the API app
CMD ["uv", "run", "main.py"]
