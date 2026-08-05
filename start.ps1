$ErrorActionPreference = 'Stop'
$bundledPython = 'C:\Users\jkpieters\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python "$PSScriptRoot\app.py"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 "$PSScriptRoot\app.py"
} elseif (Test-Path $bundledPython) {
    & $bundledPython "$PSScriptRoot\app.py"
} else {
    throw 'Python 3.11 of nieuwer is niet gevonden.'
}
