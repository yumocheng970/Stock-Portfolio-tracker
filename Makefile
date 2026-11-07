# Paper-Trading Portfolio Tracker - common commands (run from the repo root).
# Python commands need the conda env:  conda activate spt
#
#   make test           rebuild the TEST database, run SQL tests + pytest
#   make apply-db       add/replace views, functions, triggers, analysis, indexes
#                       in portfolio_tracker (db/apply.sql; no data is touched)
#   make load-prices    load/refresh real prices into portfolio_tracker
#   make check-prices   read-only checks on the loaded prices
#   make seed           add sample users to portfolio_tracker (refuses if any exist)
#   make reseed         delete ALL users + audit rows, reset ids, seed again
#   make check-sample-data  read-only checks on the sample data
#   make dump           write db/dump/cheng_final_project.sql from portfolio_tracker
#   make verify-dump    restore the dump into a NEW temporary database, compare it
#                       with portfolio_tracker, run behaviour checks, drop it again
#
# Tests never touch the real database: TEST_DB is rebuilt from scratch,
# REAL_DB only gets insert-only loads and read-only checks.

TEST_DB ?= portfolio_tracker_test
REAL_DB ?= portfolio_tracker
DUMP_FILE  = db/dump/cheng_final_project.sql
# Temporary database for verify-dump; created and dropped by that target only
RESTORE_DB = portfolio_tracker_restore_check
PYTHON  ?= python
PSQL     = psql -X -q -v ON_ERROR_STOP=1

.PHONY: test test-db test-sql test-py apply-db load-prices check-prices seed reseed check-sample-data \
        dump verify-dump

test: test-sql test-py

# Create the test DB if it doesn't exist, then rebuild it with reset.sql
test-db:
	@psql -X -lqt | cut -d '|' -f 1 | grep -qw $(TEST_DB) || createdb $(TEST_DB)
	$(PSQL) -d $(TEST_DB) -f db/reset.sql

test-sql: test-db
	$(PSQL) -d $(TEST_DB) -f db/tests/test_schema.sql

test-py:
	$(PYTHON) -m pytest -q

# All or nothing: one transaction around the whole of db/apply.sql
apply-db:
	$(PSQL) --single-transaction -d $(REAL_DB) -f db/apply.sql

load-prices:
	$(PYTHON) -m etl.load_prices

check-prices:
	$(PSQL) -d $(REAL_DB) -f db/tests/check_prices.sql

seed:
	$(PYTHON) -m etl.seed_sample_data

reseed:
	$(PYTHON) -m etl.seed_sample_data --replace

check-sample-data:
	$(PSQL) -d $(REAL_DB) -f db/tests/check_sample_data.sql

# Final deliverable (Task 2). Plain SQL, restorable with psql anywhere:
#   --no-owner       no ALTER ... OWNER TO ethan (objects belong to whoever restores)
#   --no-privileges  no GRANT/REVOKE naming roles of this machine
dump:
	pg_dump --no-owner --no-privileges --format=plain -d $(REAL_DB) -f $(DUMP_FILE)
	@ls -l $(DUMP_FILE)

# Restore the dump into a fresh empty database and prove it equals REAL_DB.
# The temporary database is dropped at the end, also when a check fails.
verify-dump:
	dropdb --if-exists $(RESTORE_DB)
	createdb $(RESTORE_DB)
	@set -e; tmp=$$(mktemp -d); trap 'dropdb --if-exists $(RESTORE_DB); rm -rf "$$tmp"' EXIT; \
	$(PSQL) --single-transaction -d $(RESTORE_DB) -f $(DUMP_FILE) > /dev/null; \
	echo "== compare inventory: $(REAL_DB) vs $(RESTORE_DB)"; \
	$(PSQL) -At -d $(REAL_DB)    -f db/tests/dump_compare.sql > $$tmp/real.txt; \
	$(PSQL) -At -d $(RESTORE_DB) -f db/tests/dump_compare.sql > $$tmp/restored.txt; \
	diff $$tmp/real.txt $$tmp/restored.txt; \
	echo "identical: $$(wc -l < $$tmp/real.txt) lines"; \
	grep '^rows ' $$tmp/restored.txt; \
	echo "== behaviour checks"; \
	$(PSQL) -d $(RESTORE_DB) -f db/tests/check_restore.sql; \
	echo "== sample-data fingerprint"; \
	$(PSQL) -At -d $(REAL_DB)    -f db/tests/check_sample_data.sql > $$tmp/fp_real.txt; \
	$(PSQL) -At -d $(RESTORE_DB) -f db/tests/check_sample_data.sql > $$tmp/fp_restored.txt; \
	a=$$(tail -1 $$tmp/fp_real.txt); b=$$(tail -1 $$tmp/fp_restored.txt); \
	echo "$(REAL_DB): $$a"; echo "$(RESTORE_DB): $$b"; \
	test "$$a" = "$$b"; \
	echo "verify-dump: ALL OK ($(RESTORE_DB) dropped)"
