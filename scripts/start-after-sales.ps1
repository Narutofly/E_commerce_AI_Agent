param([string]$Python = 'python', [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& $Python -m uvicorn backend.after_sales.main:app --host 127.0.0.1 --port $Port
