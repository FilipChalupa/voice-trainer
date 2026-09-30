# ---------- 1) frontend build ----------
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 2) backend + Piper trainer ----------
FROM python:3.12-slim AS backend

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git libsndfile1 gosu build-essential cmake ninja-build \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 1000 app && useradd -m -u 1000 -g app app

# Piper (GPL-3.0) with its training extras from a pinned commit. The default PyTorch wheel on Linux
# bundles CUDA, so the same image trains on an NVIDIA GPU and still starts on a CPU-only machine.
ARG PIPER_REF=efffbfb226bfb511ebbcf55d0cecd8b35a89743d
RUN --mount=type=cache,target=/root/.cache/pip \
    git clone https://github.com/OHF-Voice/piper1-gpl /opt/piper \
    && git -C /opt/piper checkout --quiet "${PIPER_REF}" \
    && cd /opt/piper \
    && pip install 'scikit-build<1' 'cmake>=3.18,<4' 'ninja>=1,<2' \
    && pip install -e '.[train]' \
    && ./build_monotonic_align.sh \
    && python3 setup.py build_ext --inplace \
    && python3 -c "import piper, piper.train.vits.lightning, piper.train.vits.monotonic_align; print('piper ok')"

# torchaudio is needed by the optional UTMOS quality predictor used during validation (val_mos).
# It lags behind torch releases, so it is pinned and installed without touching torch itself.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-deps torchaudio==2.11.0 \
    && python3 -c "import torch, torchaudio; print('torch', torch.__version__, 'torchaudio', torchaudio.__version__)"

WORKDIR /app
COPY backend/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

COPY backend/ ./
COPY VERSION ./VERSION
COPY --from=frontend /app/dist ./static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && chown -R app:app /app

# numba (pulled in by librosa) caches compiled functions; site-packages is read-only for the app user
ENV HOME=/home/app \
    NUMBA_CACHE_DIR=/tmp/numba_cache \
    MPLCONFIGDIR=/tmp/matplotlib
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
