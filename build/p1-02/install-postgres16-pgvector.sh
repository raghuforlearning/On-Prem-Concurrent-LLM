#!/usr/bin/env bash
# ============================================================================
# P1-02 — PostgreSQL 16 + pgvector installation & acceptance script
# Target: aiinference VM (Ubuntu 22.04). Guided-mode reference copy.
# EXECUTED 08-Aug-2026 — all acceptance tests PASSED (see BUILD-LOG.md).
# ============================================================================
set -e

# --- Install (PGDG official repo) ------------------------------------------
sudo apt install -y postgresql-common curl ca-certificates
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get update
sudo apt install -y postgresql-16 postgresql-16-pgvector

# --- Database + app role + pgvector -----------------------------------------
# sudo -u postgres psql:
#   CREATE USER orchestrator_app WITH PASSWORD '<strong-password>';   (P1-03 needs it)
#   CREATE DATABASE orchestrator OWNER orchestrator_app;
#   \c orchestrator
#   CREATE EXTENSION vector;

# --- WAL archiving (PITR engine) --------------------------------------------
sudo mkdir -p /var/lib/postgresql/wal_archive /var/lib/postgresql/backups
sudo chown postgres:postgres /var/lib/postgresql/wal_archive /var/lib/postgresql/backups
sudo chmod 700 /var/lib/postgresql/wal_archive
# ALTER SYSTEM SET archive_mode = 'on';
# ALTER SYSTEM SET archive_command = 'test ! -f /var/lib/postgresql/wal_archive/%f && cp %p /var/lib/postgresql/wal_archive/%f';
# ALTER SYSTEM SET wal_level = 'replica';
# ALTER SYSTEM SET archive_timeout = '1h';   -- recovery floor never >1h behind
sudo systemctl restart postgresql

# --- Audit schema ------------------------------------------------------------
sudo -u postgres psql -d orchestrator -f "$(dirname "$0")/audit_schema.sql"

# --- Acceptance tests (all PASSED 08-Aug-2026) --------------------------------
# 1. pg_lsclusters -> 16 main online 5432                     [PASS]
# 2. \dx in orchestrator -> vector 0.8.6                      [PASS]
# 3. pg_switch_wal() -> segment appears in wal_archive        [PASS]
# 4. audit chain: row2.prev_hash == row1.entry_hash           [PASS]
# 5. UPDATE/DELETE on audit_log -> rejected by trigger        [PASS]
# 6. pg_basebackup + PITR drill to 2026-08-08 08:41:22+00:
#    recovered cluster showed 2 rows, disaster row absent     [PASS]
# NOTE: recovery target can only be as recent as the last ARCHIVED WAL
# segment — force one with SELECT pg_switch_wal(); before a drill.
