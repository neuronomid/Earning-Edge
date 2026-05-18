$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# Per-day rolling log so Windows Task Scheduler runs leave an audit trail.
$logDir = Join-Path $repoRoot "var\qa\_scheduler"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$logFile = Join-Path $logDir ("{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

function Write-LogLine {
    param([string]$Line)
    $stamped = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"), $Line
    Out-File -FilePath $logFile -Append -Encoding utf8 -InputObject $stamped
}

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

Write-LogLine ("launch python={0} args={1}" -f $python, ($args -join ' '))

# Capture python stdout+stderr to the same log file, utf8.
$output = & $python ".\scripts\run_qa_intraday.py" @args 2>&1
$code = $LASTEXITCODE
if ($output) {
    $output | Out-File -FilePath $logFile -Append -Encoding utf8
}

Write-LogLine ("exit code={0}" -f $code)
exit $code
