param(
    [string]$GatewayIp = "192.168.1.42",
    [int]$DurationHours = 6,
    [int]$DurationMinutes = 0,
    [int]$SampleIntervalSeconds = 30
)

$ErrorActionPreference = "Stop"
$started = Get-Date
$effectiveMinutes = if ($DurationMinutes -gt 0) {
    $DurationMinutes
} else {
    $DurationHours * 60
}
$deadline = $started.AddMinutes($effectiveMinutes)
$stamp = $started.ToString("yyyyMMdd-HHmmss")
$csvPath = Join-Path $PSScriptRoot "reliability-$stamp.csv"
$samples = 0
$successfulSamples = 0
$failedSamples = 0
$restartCount = 0
$lteOfflineSamples = 0
$internetFailedSamples = 0
$minimumFreeBytes = [long]::MaxValue
$firstPacketCount = $null
$lastPacketCount = $null
$previousUptime = $null

Write-Host "Monitoring $GatewayIp for $effectiveMinutes minutes"
Write-Host "Results: $csvPath"

while ((Get-Date) -lt $deadline) {
    $sampleTime = Get-Date
    $samples++
    $row = [ordered]@{
        timestamp = $sampleTime.ToString("yyyy-MM-ddTHH:mm:ssK")
        reachable = $false
        gateway_status = "UNAVAILABLE"
        uptime_seconds = $null
        free_memory_bytes = $null
        tcp_server = "UNKNOWN"
        http_server = "OFFLINE"
        packets_received = $null
        packets_per_second = $null
        known_devices = $null
        lte_registration = "UNKNOWN"
        lte_signal_dbm = $null
        lte_mobile_ip = $null
        lte_internet_ok = $null
        error = $null
    }

    try {
        $status = Invoke-RestMethod -Uri "http://$GatewayIp/api/status" -TimeoutSec 10
        $statistics = Invoke-RestMethod -Uri "http://$GatewayIp/api/statistics" -TimeoutSec 10
        $row.reachable = $true
        $row.gateway_status = $status.gateway_status
        $row.uptime_seconds = $status.uptime_seconds
        $row.free_memory_bytes = $status.free_memory
        $row.tcp_server = $status.tcp_server
        $row.http_server = $status.http_server
        $row.packets_received = $statistics.packets_received
        $row.packets_per_second = $statistics.packets_per_second
        $row.known_devices = $statistics.known_devices
        $row.lte_registration = $status.lte.registration
        $row.lte_signal_dbm = $status.lte.signal_dbm
        $row.lte_mobile_ip = $status.lte.mobile_ip
        $row.lte_internet_ok = $status.lte.internet_ok
        $successfulSamples++

        if ($status.free_memory -lt $minimumFreeBytes) {
            $minimumFreeBytes = $status.free_memory
        }
        if ($null -ne $previousUptime -and $status.uptime_seconds -lt $previousUptime) {
            $restartCount++
        }
        $previousUptime = $status.uptime_seconds
        if ($null -eq $firstPacketCount) { $firstPacketCount = $statistics.packets_received }
        $lastPacketCount = $statistics.packets_received
        if ($status.lte.registration -ne "REGISTERED") { $lteOfflineSamples++ }
        if ($status.lte.internet_ok -eq $false) { $internetFailedSamples++ }

        Write-Host ("{0} OK uptime={1}s free={2:N0}KB packets={3} LTE={4}" -f `
            $sampleTime.ToString("HH:mm:ss"), $status.uptime_seconds,
            ($status.free_memory / 1KB), $statistics.packets_received,
            $status.lte.registration)
    }
    catch {
        $failedSamples++
        $row.error = $_.Exception.Message
        Write-Warning ("{0} gateway unavailable: {1}" -f `
            $sampleTime.ToString("HH:mm:ss"), $_.Exception.Message)
    }

    [PSCustomObject]$row | Export-Csv -LiteralPath $csvPath -NoTypeInformation -Append

    $remaining = [int](($deadline - (Get-Date)).TotalSeconds)
    if ($remaining -gt 0) {
        Start-Sleep -Seconds ([Math]::Min($SampleIntervalSeconds, $remaining))
    }
}

$availability = if ($samples) { 100.0 * $successfulSamples / $samples } else { 0 }
$packetIncrease = if ($null -ne $firstPacketCount -and $null -ne $lastPacketCount) {
    $lastPacketCount - $firstPacketCount
} else { 0 }
$minimumFreeKb = if ($minimumFreeBytes -eq [long]::MaxValue) { 0 } else {
    [Math]::Round($minimumFreeBytes / 1KB, 1)
}

Write-Host ""
Write-Host "$effectiveMinutes-minute reliability summary" -ForegroundColor Cyan
Write-Host ("Availability: {0:N3}% ({1}/{2} samples)" -f $availability, $successfulSamples, $samples)
Write-Host "Failed samples: $failedSamples"
Write-Host "Detected restarts: $restartCount"
Write-Host "Minimum free memory: $minimumFreeKb KB"
Write-Host "Packets received during test: $packetIncrease"
Write-Host "LTE offline samples: $lteOfflineSamples"
Write-Host "LTE internet-failed samples: $internetFailedSamples"
Write-Host "CSV report: $csvPath"

$passed = ($availability -ge 99.9 -and $restartCount -eq 0 -and
           $minimumFreeKb -ge 50 -and $lteOfflineSamples -eq 0)
if ($passed) {
    Write-Host "RESULT: PASS" -ForegroundColor Green
    exit 0
}

Write-Host "RESULT: REVIEW REQUIRED" -ForegroundColor Yellow
exit 1
