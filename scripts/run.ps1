param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CliArgs)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Сначала создайте .venv с Python из Miniconda (см. README).'
}
$venvConfig = Get-Content -LiteralPath (Join-Path $projectRoot '.venv\pyvenv.cfg')
$pythonHome = ($venvConfig | Where-Object { $_ -match '^home = ' }) -replace '^home = ', ''
if ($pythonHome) {
    $env:PATH = "$pythonHome;$pythonHome\Library\bin;$pythonHome\DLLs;" + $env:PATH
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m tg_chat_analyzer @CliArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
