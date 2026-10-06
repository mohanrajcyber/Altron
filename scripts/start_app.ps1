$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonCandidates = @(
  (Join-Path $repoRoot "..\..\..\.venv\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv\Scripts\python.exe")
)
$python = $null
foreach ($candidate in $pythonCandidates) {
  if (-not (Test-Path $candidate)) { continue }
  & $candidate -c "import sys" *> $null
  if ($LASTEXITCODE -eq 0) {
    $python = $candidate
    break
  }
  Write-Host "Skipping unusable Python environment: $candidate"
}

if ($python) {
  Write-Host "Starting ALTRON with $python"
  & $python -m altron app
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  Write-Host "Starting ALTRON with Python from PATH"
  python -m altron app
} else {
  Write-Error "Python was not found. Create a project .venv or install Python and add it to PATH."
  exit 1
}
exit $LASTEXITCODE
