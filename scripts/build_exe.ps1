$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..
& .\.venv\Scripts\python.exe -m pip install -e ".[build]" -q
New-Item -ItemType Directory -Force -Path build | Out-Null
@"
from altron.__main__ import main
import sys
if __name__ == '__main__':
    sys.exit(main(['app']))
"@ | Set-Content -Encoding utf8 .\build\altron_app_entry.py

& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean `
  --name ALTRON `
  --onefile `
  --console `
  --paths . `
  --add-data "altron\web;altron\web" `
  --hidden-import altron `
  --hidden-import altron.server `
  --hidden-import uvicorn `
  --hidden-import fastapi `
  .\build\altron_app_entry.py

Write-Host "Built .\dist\ALTRON.exe - run it to open the desktop command core."
