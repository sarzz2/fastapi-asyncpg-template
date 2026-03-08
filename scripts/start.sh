#!/bin/bash
set -e

# Run migrations
echo "Running migrations..."
python migrate.py

# Create default admin
echo "Creating default admin..."
export PYTHONPATH=$PYTHONPATH:.
python scripts/create_default_admin.py

# Start the application
echo "Starting application..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000 --loop uvloop --http httptools --log-level info --workers 4
