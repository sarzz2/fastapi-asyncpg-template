#!/bin/bash
set -e

# Run migrations
echo "Running migrations..."
python migrate.py

# Start the application
echo "Starting application..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --loop uvloop --http httptools --log-level info --workers 4
