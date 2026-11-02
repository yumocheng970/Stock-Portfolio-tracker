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
#
# Tests never touch the real database: TEST_DB is rebuilt from scratch,
# REAL_DB only gets insert-only loads and read-only checks.

TEST_DB ?= portfolio_tracker_test
REAL_DB ?= portfolio_tracker
PYTHON  ?= python
PSQL     = psql -X -q -v ON_ERROR_STOP=1

.PHONY: test test-db test-sql test-py apply-db load-prices check-prices seed reseed check-sample-data

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
