$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$env:PYTHONPATH = "$projectRoot/libs/common;$projectRoot/pipeline;$projectRoot/query"
& "$projectRoot/.venv/Scripts/python.exe" -m uvicorn query.api.app:app --host 127.0.0.1 --port 8770 --env-file "$projectRoot/.env.local"
exit $LASTEXITCODE
