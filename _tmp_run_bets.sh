#!/usr/bin/env bash
set -e
cd /stockex/backend
export $(grep -E '^MONGODB_URL=' .env | xargs)
mongosh "$MONGODB_URL" --quiet /tmp/_tmp_bets.js
