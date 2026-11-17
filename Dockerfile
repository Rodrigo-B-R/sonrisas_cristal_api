FROM python:3.12-slim

# No .pyc files, and logs go out right away (docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ENVIRONMENT=production

WORKDIR /app

# Only the dependencies first: Docker reuses this layer while requirements.txt does not change.
# (psycopg[binary] brings its own libpq and tzdata brings the time zones: no apt packages needed.)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Do not run as root
RUN useradd --create-home --uid 1000 app
COPY --chown=app:app app ./app
COPY --chown=app:app scripts ./scripts
USER app

EXPOSE 8000

# "Healthy" when GET / answers. Python is enough: the slim image has no curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/', timeout=3).status == 200 else 1)"

# One worker on purpose: the failed-login counter lives in memory (see app/security.py)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
