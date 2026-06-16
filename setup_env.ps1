# setup_env.ps1 — Create conda env and install all dependencies for AITranslate
$ErrorActionPreference = "Stop"

$envName = "aitranslate"

$existing = conda env list | Select-String "^\s*$envName\s"
if ($existing) {
    Write-Host "Conda env '$envName' already exists. Removing..."
    conda env remove -n $envName -y
}

Write-Host "Creating conda env '$envName' with Python 3.11..."
conda create -n $envName python=3.11 -y
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Activating and installing packages..."
conda run -n $envName pip install PyQt6 Pillow easyocr deep-translator pywin32 pynput

Write-Host ""
Write-Host "Done. Activate with: conda activate $envName"
Write-Host "Then run: python main.py"
