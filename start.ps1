$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$envPath = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    $examplePath = Join-Path $PSScriptRoot ".env.example"
    if (-not (Test-Path -LiteralPath $examplePath)) {
        Write-Error "Missing .env.example. Restore the project configuration file, then run start.bat again."
        exit 1
    }

    $randomBytes = New-Object byte[] 32
    $randomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomGenerator.GetBytes($randomBytes)
    } finally {
        $randomGenerator.Dispose()
    }
    $databasePassword = ($randomBytes | ForEach-Object { $_.ToString("x2") }) -join ""

    $environment = [System.IO.File]::ReadAllText($examplePath)
    if (-not $environment.Contains("POSTGRES_PASSWORD=change-me") -or
        -not $environment.Contains("DATABASE_URL=postgresql://opendispatch:change-me@db:5432/opendispatch")) {
        Write-Error ".env.example does not contain the expected database placeholders; create .env manually before starting."
        exit 1
    }

    $environment = $environment.Replace("POSTGRES_PASSWORD=change-me", "POSTGRES_PASSWORD=$databasePassword")
    $environment = $environment.Replace(
        "DATABASE_URL=postgresql://opendispatch:change-me@db:5432/opendispatch",
        "DATABASE_URL=postgresql://opendispatch:$databasePassword@db:5432/opendispatch"
    )
    $utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($envPath, $environment, $utf8WithoutBom)
    Write-Host "Created a local .env with a random database password."
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) {
    Write-Error "Docker CLI was not found. Install Docker Desktop, then run start.bat again."
    exit 1
}

docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) {
    $desktopCandidates = @($env:ProgramFiles, $env:ProgramW6432) |
        Where-Object { $_ } |
        ForEach-Object { Join-Path $_ "Docker\Docker\Docker Desktop.exe" } |
        Select-Object -Unique
    $desktopPath = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

    if (-not $desktopPath) {
        Write-Error "Docker Desktop is not running and its app could not be found. Start Docker Desktop, then run start.bat again."
        exit 1
    }

    Write-Host "Starting Docker Desktop..."
    Start-Process -FilePath $desktopPath

    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        docker info --format '{{.ServerVersion}}' *> $null
        if ($LASTEXITCODE -eq 0) { break }
    } while ((Get-Date) -lt $deadline)

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker Desktop did not become ready within 3 minutes. Check Docker Desktop, then run start.bat again."
        exit 1
    }
}

Write-Host "Starting OpenDispatch. Press Ctrl+C to stop the services."

$privateInterfaceIndexes = @(
    Get-NetConnectionProfile -ErrorAction SilentlyContinue |
        Where-Object { $_.NetworkCategory -eq "Private" } |
        Select-Object -ExpandProperty InterfaceIndex
)
$lanAddress = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
    Where-Object {
        $_.InterfaceIndex -in $privateInterfaceIndexes -and
        $_.NetAdapter.Status -eq "Up" -and
        $_.IPv4DefaultGateway
    } |
    ForEach-Object { $_.IPv4Address } |
    Where-Object { $_.IPAddress -and $_.IPAddress -notmatch "^(127|169\.254)\." } |
    Select-Object -First 1 -ExpandProperty IPAddress

if ($lanAddress) {
    $env:OPENDISPATCH_WEB_BIND = $lanAddress
    Write-Host ("Phone access on this Private Wi-Fi: http://{0}:5173" -f $lanAddress)
    Write-Warning "LAN access uses unencrypted HTTP, so passwords and login tokens are not encrypted in transit. Use a trusted shop network only; do not use guest/public Wi-Fi or forward port 5173 from your router."
} else {
    $env:OPENDISPATCH_WEB_BIND = "127.0.0.1"
    Write-Warning "No active Windows network marked Private was found; the site will be available only on this computer."
    Write-Host "To enable phone access, set the shop Wi-Fi network to Private in Windows Network settings, then restart OpenDispatch."
}

docker compose up --build
exit $LASTEXITCODE
