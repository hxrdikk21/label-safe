.PHONY: start stop dev ingest rules ports-free llm-status llm-check rag-eval refresh lock prod-up prod-down

# real: BGE embeddings + reranker (pip install -e ".[ml]"); fake: offline test doubles (make start MODEL_MODE=fake).
# Ingest and serve with the same mode; `make ingest` re-embeds passages made by the other mode.
MODEL_MODE ?= real
# LLM work uses Gemini: set LLM_BACKEND=gemini and GEMINI_API_KEY in .env (see .env.example).
LIMIT ?= 500

# The whole project: PostgreSQL + migrations + drug catalogue + FDA labels (first run only),
# then backend (:8000) and frontend (:5173). Ctrl+C stops the servers; Postgres keeps running.
start: .venv .env frontend/node_modules
	@docker info >/dev/null 2>&1 || { echo "Docker isn't running. Start Docker Desktop, then run make start again."; exit 1; }
	@$(MAKE) --no-print-directory ports-free
	docker compose up -d --wait postgres
	.venv/bin/alembic upgrade head
	.venv/bin/python -m src.rxguard.ingestion.seed_loader
	@if [ "$$(docker compose exec -T postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -tAc "select count(*) from evidence_passages"')" = "0" ]; then \
		echo "First run: fetching FDA labels for $(LIMIT) drugs (this takes a while)"; \
		MODEL_MODE=$(MODEL_MODE) .venv/bin/python -m src.rxguard.ingestion.ingest_labels --limit $(LIMIT); \
	fi
	@ls data/generated/*.json >/dev/null 2>&1 || $(MAKE) --no-print-directory rules
	@$(MAKE) --no-print-directory llm-status
	@trap 'kill 0' INT TERM EXIT; \
	MODEL_MODE=$(MODEL_MODE) .venv/bin/uvicorn src.rxguard.api.main:app --reload --port 8000 & \
	npm --prefix frontend run dev

# Backend + frontend without a database (users and profiles reset on restart).
dev: .venv frontend/node_modules
	@$(MAKE) --no-print-directory llm-status
	@trap 'kill 0' INT TERM EXIT; \
	DATABASE_URL= MODEL_MODE=$(MODEL_MODE) .venv/bin/uvicorn src.rxguard.api.main:app --reload --port 8000 & \
	npm --prefix frontend run dev

# Fetch more FDA labels into PostgreSQL and embed them: make ingest LIMIT=50
ingest:
	MODEL_MODE=$(MODEL_MODE) .venv/bin/python -m src.rxguard.ingestion.ingest_labels --limit $(LIMIT)

.venv:
	python3 -m venv .venv
	.venv/bin/pip install -q -e ".[dev,ml,llm]"

frontend/node_modules:
	npm --prefix frontend install

# Local secrets from the template: random Postgres password and JWT key, used consistently.
.env:
	@python3 -c "import secrets; p = secrets.token_hex(16); t = open('.env.example').read(); \
	t = t.replace('POSTGRES_PASSWORD=', 'POSTGRES_PASSWORD=' + p, 1).replace('<password>', p); \
	t = t.replace('JWT_SECRET_KEY=', 'JWT_SECRET_KEY=' + secrets.token_hex(32), 1); open('.env', 'w').write(t)"
	@echo "Created .env with generated secrets"

# Rules for the whole catalogue from DDInter and the ingested FDA labels (unreviewed; curated rules win).
rules:
	.venv/bin/python -m src.rxguard.safety.build_rules

# Re-fetch every label and rebuild the rules (monthly cron in production: see docs/PRODUCTION.md).
refresh:
	MODEL_MODE=$(MODEL_MODE) .venv/bin/python -m src.rxguard.ops.bootstrap --refresh --limit $(LIMIT)

# Pin every dependency for the image and CI (Python 3.11, all platforms).
lock:
	uv pip compile pyproject.toml --extra ml --extra llm --python-version 3.11 --universal -o requirements.lock

# Production stack (Caddy HTTPS + API + PostgreSQL + bootstrap + backups) from .env.
prod-up:
	docker compose -f deployment/docker-compose.prod.yml --env-file .env up -d --build

prod-down:
	docker compose -f deployment/docker-compose.prod.yml --env-file .env down

# RAG retrieval quality on the real label corpus; add ARGS=--generate to also run the LLM step.
rag-eval:
	MODEL_MODE=$(MODEL_MODE) .venv/bin/python -m src.rxguard.evaluation.live_eval $(ARGS)

# Which writer answers questions: Gemini (grounded synthesis) or the template (quotes label text).
llm-status:
	@.venv/bin/python -c "from src.rxguard.core.config import Settings; s = Settings(); \
	key = s.gemini_api_key is not None and bool(s.gemini_api_key.get_secret_value()); \
	print(f'Answers: Gemini {s.gemini_model}, models: $(MODEL_MODE)') if s.llm_backend == 'gemini' and key else \
	print('WARNING: no Gemini (set LLM_BACKEND=gemini and GEMINI_API_KEY in .env); answers will only quote label text.')"

# One tiny request to Gemini with the key and model from .env.
llm-check:
	@.venv/bin/python -c "from src.rxguard.core.config import Settings; from src.rxguard.rag.generator import gemini_client; \
	s = Settings(); c = gemini_client(s); r = c.models.generate_content(model=s.gemini_model, contents='Reply with the single word OK.'); \
	print(s.gemini_model, '->', r.text)"

# Stop Postgres (data is kept in its Docker volume). Dev servers stop with Ctrl+C.
stop:
	docker compose down

# A stale server on these ports makes the frontend talk to old code; never kill it silently.
ports-free:
	@for port in 8000 5173; do \
		pid=$$(lsof -tiTCP:$$port -sTCP:LISTEN 2>/dev/null | head -1); \
		if [ -n "$$pid" ]; then \
			echo "Port $$port is already in use by: $$(ps -o command= -p $$pid | cut -c1-100)"; \
			case "$$(ps -o command= -p $$pid)" in *docker*|*com.docker*) \
				echo "  If it's the old production stack: docker compose -f deployment/docker-compose.prod.yml down";; \
			*) echo "  Stop it with: kill $$pid";; esac; \
			exit 1; \
		fi; \
	done

