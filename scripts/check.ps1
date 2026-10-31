$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location -LiteralPath $projectRoot
try {
    New-Item -ItemType Directory -Path '.tmp' -Force | Out-Null
    $env:TEMP = Join-Path $projectRoot '.tmp'
    $env:TMP = $env:TEMP
    $env:PYTHONUTF8 = '1'
    $venvConfig = Get-Content -LiteralPath '.venv\pyvenv.cfg'
    $pythonHome = ($venvConfig | Where-Object { $_ -match '^home = ' }) -replace '^home = ', ''
    $env:PATH = "$pythonHome;$pythonHome\Library\bin;$pythonHome\DLLs;" + $env:PATH
    & $pythonPath -m unittest discover -s tests -v
    exit $LASTEXITCODE
} finally { Pop-Location }
