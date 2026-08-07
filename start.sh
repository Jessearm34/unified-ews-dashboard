#!/bin/bash
echo "=== STARTUP $(date) ==="
echo "PORT=${PORT}"
echo "Python: $(python --version)"
echo "Files: $(ls api/routes/ | head -5)"
exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info
