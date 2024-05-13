.DEFAULT: help
.PHONY: help
help:
	@grep -E -h '\s##\s' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: checks
checks: ## Check things
checks: shellcheck semgrep
	poetry run mypy --strict container_backups tests/*.py
	poetry run ruff check *.py tests/*.py

.PHONY: shellcheck
shellcheck: ## Run shellcheck
shellcheck:
	@echo "Running shellcheck..."
	@find "$(shell pwd)" -name '*.sh' -ls -exec shellcheck "{}" \;
	@echo "Done running shellcheck"

.PHONY: semgrep
semgrep: ## Run semgrep
semgrep:
	semgrep ci --config auto \
	--exclude-rule "yaml.github-actions.security.third-party-action-not-pinned-to-commit-sha.third-party-action-not-pinned-to-commit-sha"

.PHONY: docker
docker: ## Build all the containers
docker: docker/postgresql-backup

.PHONY: docker/postgresql-backup
docker/postgresql-backup: ## Build a PostgreSQL backup in a Docker container
docker/postgresql-backup:
	docker build -t 'container-backups-postgresql' -f Dockerfile.postgresql-backup .

