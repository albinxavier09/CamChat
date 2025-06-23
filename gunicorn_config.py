import os

# Get the port from the environment variable, default to 8000
port = int(os.environ.get("PORT", 8000))

# Gunicorn config variables
bind = f"0.0.0.0:{port}"
workers = int(os.environ.get("WEB_CONCURRENCY", 3))
threads = int(os.environ.get("PYTHON_MAX_THREADS", 2))
worker_class = "sync"

# Timeout settings
# This is important for long-running video processing tasks.
# 300 seconds = 5 minutes
timeout = 300
keepalive = 5

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info" 