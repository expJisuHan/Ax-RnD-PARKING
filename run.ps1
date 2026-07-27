$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "가상환경이 없습니다. readme.md의 설치 명령을 먼저 실행하세요."
}

Set-Location -LiteralPath $projectRoot
& $venvPython -m uvicorn src.server:app --host 0.0.0.0 --port 8000
