Set-Location $PSScriptRoot
Start-Process "http://127.0.0.1:8000"
if (Get-Command py -ErrorAction SilentlyContinue) { py app.py } else { python app.py }
