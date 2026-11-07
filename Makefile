# Paper-Trading Portfolio Tracker - common commands (run from the repo root).
# Python commands need the conda env:  conda activate spt
#
#   make run            start the CLI app on portfolio_tracker (real data)
#   make run-test-db    start the CLI app on portfolio_tracker_test (emptied by make test)
#   make run-readonly   start the CLI app on portfolio_tracker, READ-ONLY (safe demos)
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
# -P pager=off: never stop in a pager (less) on long test / check output
PSQL     = psql -X -q -v ON_ERROR_STOP=1 -P pager=off

.PHONY: test test-db test-sql test-py apply-db load-prices check-prices seed reseed check-sample-data \
        dump verify-dump run run-test-db run-readonly

test: test-sql test-py

# The CLI app (python -m app). DB_NAME in the environment wins over .env.
run:
	$(PYTHON) -m app

run-test-db:
	DB_NAME=$(TEST_DB) $(PYTHON) -m app

# Every transaction is read-only (server setting via PGOPTIONS): browsing works,
# any change is refused with a friendly message. Safe for demos on real data.
run-readonly:
	PGOPTIONS='-c default_transaction_read_only=on' $(PYTHON) -m app

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

# Final deliverable (Task 2). Plain SQL that ANY client can run (psql, DBeaver, pgAdmin):
#   --no-owner       no ALTER ... OWNER TO ethan (objects belong to whoever restores)
#   --no-privileges  no GRANT/REVOKE naming roles of this machine
#   --column-inserts --rows-per-insert=1000
#                    data as INSERT INTO t (col, ...) VALUES (...), (...) ... with up to
#                    1000 rows each, instead of psql-only COPY ... FROM stdin
#   sed              deletes the \restrict / \unrestrict lines pg_dump 16.10+ adds
#                    (psql meta-commands: other clients and older psql reject them)
#   grep             fails if any line still starts with a backslash
dump:
	pg_dump --no-owner --no-privileges --column-inserts --rows-per-insert=1000 \
	        -d $(REAL_DB) -f $(DUMP_FILE)
	sed -i -E '/^\\(un)?restrict /d' $(DUMP_FILE)
	@! grep -n '^\\' $(DUMP_FILE) || { echo "psql meta-command left in $(DUMP_FILE)"; exit 1; }
	@ls -l $(DUMP_FILE)

# Restore the dump into a fresh temporary database twice (with psql, and without
# psql through Python), compare with REAL_DB, run behaviour checks, drop it.
# Needs the conda env (spt) for the Python restore.
verify-dump:
	PYTHON=$(PYTHON) bash db/tests/verify_dump.sh $(REAL_DB) $(RESTORE_DB) $(DUMP_FILE)
