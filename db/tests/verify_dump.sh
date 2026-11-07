#!/usr/bin/env bash
# =====================================================================
# Paper-Trading Portfolio Tracker  (CS 5200, Yumo Cheng)
# Prove that the dump restores into an EMPTY database and equals the real one.
# Called by `make verify-dump` (needs the conda env spt for step B).
#
# usage: db/tests/verify_dump.sh <real_db> <temp_db> <dump_file>
#
#   0. the file has no psql meta-commands (no line starts with "\")
#   A. restore with psql
#   B. restore WITHOUT psql (Python/psycopg sends the file as plain SQL),
#      like DBeaver / pgAdmin would
#   After each restore: inventory diff against the real DB
#   (db/tests/dump_compare.sql), behaviour checks (db/tests/check_restore.sql)
#   and the sample-data fingerprint (db/tests/check_sample_data.sql).
# The temp database is dropped at the end, also when a check fails.
# =====================================================================
set -euo pipefail

real_db=$1
temp_db=$2
dump=$3
PSQL="psql -X -q -v ON_ERROR_STOP=1"

work=$(mktemp -d)
cleanup() { dropdb --if-exists "$temp_db"; rm -rf "$work"; }
trap cleanup EXIT

echo "== 0. psql meta-commands in $dump"
if grep -n '^\\' "$dump"; then
    echo "FAIL: lines above start with a backslash (psql-only)"; exit 1
fi
echo "none ($(stat -c %s "$dump") bytes)"

# Reference values from the real database
$PSQL -At -d "$real_db" -f db/tests/dump_compare.sql > "$work/real.txt"
fp_real=$($PSQL -At -d "$real_db" -f db/tests/check_sample_data.sql | tail -1)

check_restored() {
    $PSQL -At -d "$temp_db" -f db/tests/dump_compare.sql > "$work/restored.txt"
    diff "$work/real.txt" "$work/restored.txt"
    echo "inventory identical to $real_db ($(wc -l < "$work/real.txt") lines):"
    grep '^rows ' "$work/restored.txt" | tr '\n' ' '; echo
    $PSQL -d "$temp_db" -f db/tests/check_restore.sql
    fp=$($PSQL -At -d "$temp_db" -f db/tests/check_sample_data.sql | tail -1)
    echo "fingerprint: $fp (real: $fp_real)"
    test "$fp" = "$fp_real"
}

for method in psql python; do
    dropdb --if-exists "$temp_db"
    createdb "$temp_db"
    start=$(date +%s.%N)
    if [ "$method" = psql ]; then
        echo "== A. restore with psql"
        $PSQL --single-transaction -d "$temp_db" -f "$dump" > /dev/null
    else
        echo "== B. restore WITHOUT psql (plain SQL through psycopg)"
        ${PYTHON:-python} -m db.tests.restore_without_psql "$temp_db" "$dump"
    fi
    awk -v m="$method" -v s="$start" -v e="$(date +%s.%N)" \
        'BEGIN { printf "restore time (%s): %.2f s\n", m, e - s }'
    check_restored
done

echo "verify-dump: ALL OK (psql and non-psql restore; $temp_db dropped)"
