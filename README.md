# Stock-Portfolio-tracker
Course project for database system

## Restore the database from the dump

`db/dump/cheng_final_project.sql` is a plain-SQL `pg_dump` (tables, data, views, functions,
procedures, triggers, indexes). It has no owners or grants, so it restores under any role
that may create a database. Requires PostgreSQL 16 and a recent `psql` (16.10 or newer).

```bash
# 1. Create an EMPTY database (any name)
createdb portfolio_tracker

# 2. Load the dump; stop at the first error, all or nothing
psql -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f cheng_final_project.sql

# 3. Quick check: 11 tables, sample data present
psql -d portfolio_tracker -c "SELECT count(*) AS trades FROM trade" -c "SELECT * FROM v_cash_balance LIMIT 5"
```

With a password login (e.g. Windows, user `postgres`), add `-h localhost -U postgres` to each command:

```bash
createdb -h localhost -U postgres portfolio_tracker
psql -h localhost -U postgres -v ON_ERROR_STOP=1 --single-transaction -d portfolio_tracker -f cheng_final_project.sql
```

Run the file with `psql`, not in a GUI query window (the data is loaded with `COPY ... FROM stdin`).
If an older `psql` stops at `invalid command \restrict`, upgrade psql (or delete the `\restrict` and
`\unrestrict` lines at the top and bottom of the file).

To regenerate and re-verify the dump (developer machine): `make dump && make verify-dump`.
