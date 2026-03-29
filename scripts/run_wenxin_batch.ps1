param(
    [Parameter(Mandatory = $true)]
    [string]$Db,

    [Parameter(Mandatory = $true)]
    [string]$BatchId,

    [string]$OutputDir = "outputs",
    [int]$SubmitRpm = 6,
    [int]$PollRpm = 24,
    [int]$DownloadRpm = 12,
    [double]$IdleSleepSeconds = 1.0,
    [int]$MaxAttempts = 3,
    [string]$RetryDelays = "60,120,180",
    [int]$MaxCycles = 100000
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent
$env:PYTHONPATH = Join-Path $root "src"

if ([string]::IsNullOrWhiteSpace($env:QIANFAN_API_KEY)) {
    $userKey = [Environment]::GetEnvironmentVariable("QIANFAN_API_KEY", "User")
    if (-not [string]::IsNullOrWhiteSpace($userKey)) {
        $env:QIANFAN_API_KEY = $userKey
    }
}

if ([string]::IsNullOrWhiteSpace($env:QIANFAN_API_KEY)) {
    throw "QIANFAN_API_KEY is not configured."
}

Write-Host "Running Wenxin batch $BatchId"
Write-Host "DB: $Db"
Write-Host "Output: $OutputDir"
Write-Host "Rate limits: submit=$SubmitRpm rpm, poll=$PollRpm rpm, download=$DownloadRpm rpm"

python -m image_factory run-worker `
  --db $Db `
  --output-dir $OutputDir `
  --provider wenxin `
  --submit-rpm $SubmitRpm `
  --poll-rpm $PollRpm `
  --download-rpm $DownloadRpm `
  --idle-sleep-seconds $IdleSleepSeconds `
  --max-attempts $MaxAttempts `
  --retry-delays $RetryDelays `
  --max-cycles $MaxCycles

python -m image_factory status --db $Db --batch-id $BatchId
