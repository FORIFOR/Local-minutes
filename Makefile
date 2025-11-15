
.PHONY: dev stop test clean up down restart logs status ports-kill

dev:
	npm run dev

stop:
	./scripts/dev_stop.sh

test:
	. .venv/bin/activate && pytest -q

clean:
	rm -rf backend/data/*.db backend/data/app.log backend/artifacts/*.pid *.pid || true

# Aliases for common workflow
up: dev

down: stop

restart:
	$(MAKE) stop || true
	$(MAKE) dev

# Show backend application logs
logs:
	@touch backend/data/app.log
	@echo "Tailing backend logs: backend/data/app.log (Ctrl+C to exit)"
	@tail -n 200 -f backend/data/app.log

# Show process and port status
status:
	@echo "== PID files =="
	@for f in backend_uvicorn.pid frontend_vite.pid; do \
	  if [ -f $$f ]; then \
	    printf "%-20s %s\n" $$f `cat $$f`; \
	  else \
	    printf "%-20s (missing)\n" $$f; \
	  fi; \
	done
	@echo "\n== Listening ports =="
	@(command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8000 -sTCP:LISTEN || true)
	@(command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:5173 -sTCP:LISTEN || true)

# Free default ports forcibly (use with care)
ports-kill:
	@for p in 8000 5173; do \
	  if command -v lsof >/dev/null 2>&1; then \
	    PIDS=`lsof -t -iTCP:$$p -sTCP:LISTEN || true`; \
	    if [ -n "$$PIDS" ]; then \
	      echo "Killing PIDs on port $$p: $$PIDS"; \
	      kill $$PIDS 2>/dev/null || true; \
	    else \
	      echo "No listener on port $$p"; \
	    fi; \
	  fi; \
	done
