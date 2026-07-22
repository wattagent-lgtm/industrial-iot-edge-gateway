param(
    [string]$GatewayIp = "192.168.1.42",
    [int]$Port = 5005,
    [int]$DurationSecondsPerConcept = 180,
    [int]$LegacyIntervalMilliseconds = 100,
    [int]$CooldownSeconds = 30
)

$ErrorActionPreference = "Stop"
if ($DurationSecondsPerConcept -lt 10) { throw "DurationSecondsPerConcept must be at least 10." }
if ($LegacyIntervalMilliseconds -lt 100) { throw "LegacyIntervalMilliseconds must be at least 100." }

function Get-MqttSnapshot {
    try {
        $s = Invoke-RestMethod -Uri ("http://{0}/api/status" -f $GatewayIp) -TimeoutSec 5
        return [ordered]@{
            published = [int64]$s.mqtt.published
            dropped   = [int64]$s.mqtt.dropped
            failed    = [int64]$s.mqtt.failed
            queued    = [int64]$s.mqtt.queued
        }
    }
    catch {
        Write-Warning ("Cannot read MQTT counters: {0}" -f $_.Exception.Message)
        return [ordered]@{ published = 0; dropped = 0; failed = 0; queued = 0 }
    }
}

function Wait-MqttQueue([int]$MaximumSeconds) {
    $limit = (Get-Date).AddSeconds($MaximumSeconds)
    do {
        $snapshot = Get-MqttSnapshot
        if ($snapshot.queued -eq 0) { return $snapshot }
        Write-Host ("Waiting for MQTT queue: {0}" -f $snapshot.queued)
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $limit)
    return $snapshot
}

function Invoke-LegacyConcept {
    $start = Get-Date
    $deadline = $start.AddSeconds($DurationSecondsPerConcept)
    $nextSend = $start
    $nextProgress = $start
    $client = $null
    $stream = $null
    $sequence = 0
    $ack = 0
    $failed = 0
    $bytes = 0L
    $latencyTotal = 0.0
    $latencyMaximum = 0.0
    $mqttStart = Get-MqttSnapshot

    Write-Host ""
    Write-Host "PHASE A - OLD CONCEPT"
    Write-Host "Full JSON snapshot every $LegacyIntervalMilliseconds ms (no aggregation/deadband)"

    try {
        while ((Get-Date) -lt $deadline) {
            $wait = [int](($nextSend - (Get-Date)).TotalMilliseconds)
            if ($wait -gt 0) { Start-Sleep -Milliseconds $wait }
            $sequence++
            $temperature = [Math]::Round(35.0 + (Get-Random -Minimum -30 -Maximum 31) / 10.0, 1)
            $flow = [Math]::Round(125.0 + (Get-Random -Minimum -40 -Maximum 41) / 10.0, 1)
            $vibration = [Math]::Round(0.45 + (Get-Random -Minimum -20 -Maximum 31) / 100.0, 2)
            $message = [ordered]@{
                protocol = "iiot-edge-json"; protocol_version = 1; schema_version = 1
                message_type = "telemetry"; message_id = "PUMP-OLD-$sequence"
                device_id = "PUMP-OLD"; device_name = "Legacy Full Snapshot Simulator"
                device_type = "pump"; area = "process"; sequence = $sequence
                timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
                quality = "GOOD"
                data = [ordered]@{
                    temperature_c = $temperature; flow_lpm = $flow
                    vibration_mm_s = $vibration; machine_run = $true
                    pressure_bar = (Get-Random -Minimum 95 -Maximum 111)
                    current_a = [Math]::Round(3.0 + (Get-Random -Minimum 0 -Maximum 301) / 100.0, 2)
                    voltage_v = [Math]::Round(220.0 + (Get-Random -Minimum 0 -Maximum 201) / 10.0, 1)
                }
            }
            $json = $message | ConvertTo-Json -Compress -Depth 6
            $wire = [Text.Encoding]::UTF8.GetBytes($json + "`n")
            $bytes += $wire.Length
            $timer = [Diagnostics.Stopwatch]::StartNew()
            try {
                if ($null -eq $client -or -not $client.Connected) {
                    $client = [Net.Sockets.TcpClient]::new()
                    $client.NoDelay = $true; $client.ReceiveTimeout = 5000; $client.SendTimeout = 5000
                    $client.Connect($GatewayIp, $Port); $stream = $client.GetStream()
                }
                $stream.Write($wire, 0, $wire.Length); $stream.Flush()
                $buffer = [byte[]]::new(64); $received = $stream.Read($buffer, 0, $buffer.Length)
                $response = [Text.Encoding]::UTF8.GetString($buffer, 0, $received).Trim()
                if ($response -ne '{"status":"OK"}') { throw "Unexpected response: $response" }
                $timer.Stop(); $ack++; $latencyTotal += $timer.Elapsed.TotalMilliseconds
                if ($timer.Elapsed.TotalMilliseconds -gt $latencyMaximum) { $latencyMaximum = $timer.Elapsed.TotalMilliseconds }
            }
            catch {
                $timer.Stop(); $failed++
                Write-Warning ("Legacy packet {0}: {1}" -f $sequence, $_.Exception.Message)
                if ($null -ne $stream) { $stream.Dispose() }; if ($null -ne $client) { $client.Dispose() }
                $stream = $null; $client = $null
            }
            $now = Get-Date
            if ($now -ge $nextProgress) {
                Write-Host ("{0} attempted={1} ACK={2} failed={3} bytes={4}" -f $now.ToString("HH:mm:ss"),$sequence,$ack,$failed,$bytes)
                $nextProgress = $now.AddSeconds(15)
            }
            $nextSend = $nextSend.AddMilliseconds($LegacyIntervalMilliseconds)
            if ($nextSend -lt (Get-Date)) { $nextSend = (Get-Date).AddMilliseconds($LegacyIntervalMilliseconds) }
        }
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }; if ($null -ne $client) { $client.Dispose() }
    }

    $mqttEnd = Get-MqttSnapshot
    $attempted = $ack + $failed
    return [pscustomobject]@{
        concept = "old-full-snapshot"; duration_seconds = [Math]::Round(((Get-Date)-$start).TotalSeconds,1)
        attempted = $attempted; acknowledged = $ack; tcp_failed = $failed
        success_percent = if ($attempted) { [Math]::Round(100*$ack/$attempted,3) } else { 0 }
        payload_bytes = $bytes; estimated_4g_bytes = $bytes + 170L*$attempted
        average_latency_ms = if ($ack) { [Math]::Round($latencyTotal/$ack,1) } else { 0 }
        maximum_latency_ms = [Math]::Round($latencyMaximum,1)
        mqtt_published = $mqttEnd.published-$mqttStart.published
        mqtt_dropped = $mqttEnd.dropped-$mqttStart.dropped
        mqtt_failed = $mqttEnd.failed-$mqttStart.failed
        mqtt_queue_end = $mqttEnd.queued
    }
}

$runStarted = Get-Date
$old = Invoke-LegacyConcept
Write-Host ""
Write-Host "Cooldown: allowing queued MQTT messages to drain..."
[void](Wait-MqttQueue $CooldownSeconds)

Write-Host ""
Write-Host "PHASE B - NEW MULTI-RATE CONCEPT"
& (Join-Path $PSScriptRoot "simulate_multirate_workload.ps1") `
    -GatewayIp $GatewayIp -Port $Port -DurationSeconds $DurationSecondsPerConcept
$newCsv = Get-ChildItem -LiteralPath $PSScriptRoot -Filter "multirate-*.csv" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $newCsv) { throw "Multi-rate result CSV was not created." }
$n = Import-Csv -LiteralPath $newCsv.FullName | Select-Object -First 1
$new = [pscustomobject]@{
    concept = "new-multirate-deadband"; duration_seconds = [double]$n.duration_seconds
    attempted = [int]$n.attempted; acknowledged = [int]$n.acknowledged; tcp_failed = [int]$n.failed
    success_percent = [double]$n.success_percent; payload_bytes = [int64]$n.payload_bytes
    estimated_4g_bytes = [int64]$n.estimated_4g_bytes
    average_latency_ms = [double]$n.average_latency_ms; maximum_latency_ms = [double]$n.maximum_latency_ms
    mqtt_published = [int64]$n.mqtt_published_delta; mqtt_dropped = [int64]$n.mqtt_dropped_delta
    mqtt_failed = [int64]$n.mqtt_failed_delta; mqtt_queue_end = [int64]$n.mqtt_queue_end
}

$resultPath = Join-Path $PSScriptRoot ("concept-comparison-{0}.csv" -f $runStarted.ToString("yyyyMMdd-HHmmss"))
@($old, $new) | Export-Csv -LiteralPath $resultPath -NoTypeInformation -Encoding UTF8
$messageReduction = if ($old.attempted) { [Math]::Round(100*(1-$new.attempted/$old.attempted),2) } else { 0 }
$payloadReduction = if ($old.payload_bytes) { [Math]::Round(100*(1-$new.payload_bytes/$old.payload_bytes),2) } else { 0 }
$trafficReduction = if ($old.estimated_4g_bytes) { [Math]::Round(100*(1-$new.estimated_4g_bytes/$old.estimated_4g_bytes),2) } else { 0 }

Write-Host ""
Write-Host "A/B CONCEPT COMPARISON"
@($old, $new) | Format-Table concept,attempted,acknowledged,tcp_failed,success_percent,payload_bytes,estimated_4g_bytes,average_latency_ms,mqtt_published,mqtt_dropped,mqtt_failed,mqtt_queue_end -AutoSize
Write-Host "Message reduction: $messageReduction%"
Write-Host "JSON payload reduction: $payloadReduction%"
Write-Host "Estimated 4G traffic reduction: $trafficReduction%"
Write-Host "Result: $resultPath"

