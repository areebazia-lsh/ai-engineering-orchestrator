# Stop existing uvicorn processes
Get-Process | Where-Object { $_.ProcessName -like "*python*" -and $_.CommandLine -like "*uvicorn*" } | Stop-Process -Force

# Wait for ports to be released
Start-Sleep -Seconds 2

# Start the server
cd e:\DevEps\ai-engineering-orchestrator\backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload