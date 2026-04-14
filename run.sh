#!/bin/bash
# Wrapper script for cron job

cd ~/.openclaw/workspace/autonomous-memecoin-hunter
source venv/bin/activate
python scanner.py >> logs/cron.log 2>&1
