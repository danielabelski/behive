#!/usr/bin/env python3
"""BeHive server launcher with proper credentials and env"""
import os
import sys

DB_PASS = "hive_2026_prod"
db_url = f"postgresql://hive_app:{DB_PASS}@localhost:5432/hive"
os.environ["DATABASE_URL"] = db_url
os.environ["BEHIVE_DB_URL"] = db_url
os.environ["HIVE_PG_USER"] = "hive_app"
os.environ["HIVE_PG_PASSWORD"] = DB_PASS
os.environ["HIVE_PG_DATABASE"] = "hive"
os.environ["HIVE_PG_HOST"] = "127.0.0.1"
os.environ["HIVE_PG_PORT"] = "5432"
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["BEHIVE_MODEL"] = "bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0"
os.environ["BEHIVE_MODEL_SCOUT"] = "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"
os.environ["BEHIVE_MODEL_SYNTH"] = "bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0"
os.environ["BEHIVE_PHASE_TIMEOUT"] = "600"
# Ensure venv python is found as python3
os.environ["PATH"] = "/home/ubuntu/behive-pkg/.venv/bin:" + os.environ.get("PATH", "")

sys.path.insert(0, "/home/ubuntu/behive-pkg/src")
import uvicorn
uvicorn.run("behive.server:app", host="0.0.0.0", port=8091, log_level="warning")
