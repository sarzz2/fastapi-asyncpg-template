FROM python:3.12.3-slim

# Set a working directory.
WORKDIR /app

# Install Poetry and configure it to not create virtual environments
RUN pip install poetry && \
    poetry config virtualenvs.create false

# Copy project dependencies files
COPY pyproject.toml poetry.lock* ./

# Install project dependencies
RUN poetry install --no-root --no-interaction --no-ansi

# Copy application code
COPY . .

# Expose the FastAPI port (if needed)
EXPOSE 8000

# Default command (can be overridden by Docker Compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
