# Debian/glibc (never Alpine — no musl wheels for onnxruntime/sqlite-vec).
# trixie ships SQLite >= 3.46 so sqlite-vec KNN works.
FROM python:3.12-slim-trixie

# UID-1000 non-root user (works on HF Spaces and everywhere else)
RUN useradd -m -u 1000 app
ENV HOME=/home/app \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    SNAPSHOT_BACKEND=none \
    EMBED_CACHE_DIR=/app/models

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/bake_model.py scripts/bake_model.py
# All app-writable dirs owned by the runtime user BEFORE baking, so the HF cache
# under /home/app and the model under /app/models are app-owned (no root-owned cache).
RUN mkdir -p /app/models /data && chown -R app:app /app /data /home/app
USER app
# Bake the model as `app` (needs network at build time; HF_HUB_OFFLINE is set AFTER this).
RUN python scripts/bake_model.py

COPY --chown=app:app app/ app/
COPY --chown=app:app static/ static/

# From here on the image is fully offline: HF hub reads only the baked cache.
ENV HF_HUB_OFFLINE=1

EXPOSE 8000
# EMBED_MODEL_PATH (the snapshot dir with tokenizer.json) is resolved at start for the chunker's tokenizer.
CMD ["sh", "-c", "export EMBED_MODEL_PATH=$(dirname $(find /app/models -name '*.onnx' | head -1)); exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
