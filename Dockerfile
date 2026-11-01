# RxGuard-RAG image: the API plus the built frontend, served from one origin.
# Real models by default (CPU-only torch; both models baked in at build time).
# CI builds a light image with --build-arg EXTRAS="" (offline model doubles, MODEL_MODE=fake).
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.11-slim

ARG EXTRAS="[ml,llm]"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/app/models

WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY src ./src
# requirements.lock pins every version; the CPU index serves torch without the CUDA download.
RUN pip install --upgrade pip \
 && pip install --extra-index-url https://download.pytorch.org/whl/cpu -c requirements.lock ".${EXTRAS}"

# Download the embedding model and reranker now, so containers never fetch them at runtime.
RUN if [ -n "${EXTRAS}" ]; then python -c "\
from sentence_transformers import CrossEncoder, SentenceTransformer; \
SentenceTransformer('BAAI/bge-small-en-v1.5'); CrossEncoder('BAAI/bge-reranker-base')"; fi
ENV HF_HUB_OFFLINE=1

COPY alembic.ini ./
COPY migrations ./migrations
COPY data ./data
COPY --from=web /web/dist ./frontend/dist
ENV FRONTEND_DIST=/app/frontend/dist RXGUARD_GENERATED_RULES_DIR=/app/generated

RUN useradd --create-home --uid 10001 rxguard && mkdir -p /app/generated && chown -R rxguard /app
USER rxguard

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
# --proxy-headers: behind the TLS proxy, per-IP rate limits must see the real client address.
CMD ["sh", "-c", "exec uvicorn src.rxguard.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*' --workers ${WEB_CONCURRENCY:-1}"]
