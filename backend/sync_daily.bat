@echo off
cd /d "C:\Projects\AI Resume Analyzer\backend"
set JLA_USE_DATE_WINDOWS=true
python sync_jla_staging.py >> sync_log.txt 2>&1