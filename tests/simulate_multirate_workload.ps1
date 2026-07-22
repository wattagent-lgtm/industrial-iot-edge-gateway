param(
    [string]$GatewayIp = "192.168.1.42",
    [int]$Port = 5005,
    [int]$DurationSeconds = 180,
    [string]$DeviceId = "PUMP-01",
    [string]$DeviceName = "Multi-rate Pump Simulator",
    [int]$FastPublishMs = 1000,
    [int]$SlowPublishMs = 2000,
    [int]$DiagnosticPublishMs = 30000,
    [double]$TemperatureDeadband = 0.2,
    [double]$FlowDeadband = 1.0,
    [double]$VibrationDeadband = 0.05
)

$ErrorActionPreference = "Stop"
if ($DurationSeconds -lt 1) { throw "DurationSeconds must be at least 1." }
if ($FastPublishMs -lt 100 -or $SlowPublishMs -lt 100) {
    throw "Publish intervals must be at least 100 ms."
}

$startedAt = Get-Date
$deadline = $startedAt.AddSeconds($DurationSeconds)
$resultPath = Join-Path $PSScriptRoot ("multirate-{0}.csv" -f $startedAt.ToString("yyyyMMdd-HHmmss"))
$client = $null
$stream = $null
$sequence = 0
$acknowledged = 0
$failed = 0
$payloadBytes = 0L
$latencyTotalMs = 0.0
$latencyMaxMs = 0.0
$counts = @{ fast = 0; slow = 0; event = 0; diagnostic = 0 }
$failures = @{ fast = 0; slow = 0; event = 0; diagnostic = 0 }

function Connect-Gateway {
    if ($null -ne $script:client -and $script:client.Connected) { return }
    $script:client = [System.Net.Sockets.TcpClient]::new()
    $script:client.NoDelay = $true
    $script:client.ReceiveTimeout = 5000
    $script:client.SendTimeout = 5000
    $script:client.Connect($GatewayIp, $Port)
    $script:stream = $script:client.GetStream()
}

function Disconnect-Gateway {
    if ($null -ne $script:stream) { $script:stream.Dispose() }
    if ($null -ne $script:client) { $script:client.Dispose() }
    $script:stream = $null
    $script:client = $null
}

function Get-MqttSnapshot {
    try {
        $status = Invoke-RestMethod -Uri ("http://{0}/api/status" -f $GatewayIp) -TimeoutSec 5
        return [ordered]@{
            published = [int64]$status.mqtt.published
            dropped   = [int64]$status.mqtt.dropped
            failed    = [int64]$status.mqtt.failed
            queued    = [int64]$status.mqtt.queued
            coalesced = [int64]$status.mqtt.coalesced
            priority_evictions = [int64]$status.mqtt.priority_evictions
        }
    }
    catch {
        Write-Warning ("Cannot read MQTT counters: {0}" -f $_.Exception.Message)
        return [ordered]@{ published = 0; dropped = 0; failed = 0; queued = 0; coalesced = 0; priority_evictions = 0 }
    }
}

function Send-Message([string]$Class, [System.Collections.IDictionary]$Data, [string]$MessageType = "telemetry") {
    $script:sequence++
    $message = [ordered]@{
        protocol         = "iiot-edge-json"
        protocol_version = 1
        schema_version   = 2
        message_type     = $MessageType
        data_class       = $Class
        message_id       = "${DeviceId}-$($script:sequence)"
        device_id        = $DeviceId
        device_name      = $DeviceName
        device_type      = "pump"
        area             = "process"
        sequence         = $script:sequence
        timestamp        = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
        quality          = "GOOD"
        data             = $Data
    }
    $payload = $message | ConvertTo-Json -Compress -Depth 7
    $wire = [System.Text.Encoding]::UTF8.GetBytes($payload + "`n")
    $script:payloadBytes += $wire.Length
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        Connect-Gateway
        $script:stream.Write($wire, 0, $wire.Length)
        $script:stream.Flush()
        $buffer = [byte[]]::new(64)
        $received = $script:stream.Read($buffer, 0, $buffer.Length)
        $response = [System.Text.Encoding]::UTF8.GetString($buffer, 0, $received).Trim()
        if ($response -ne '{"status":"OK"}') { throw "Unexpected response: $response" }
        $timer.Stop()
        $script:acknowledged++
        $script:counts[$Class]++
        $script:latencyTotalMs += $timer.Elapsed.TotalMilliseconds
        if ($timer.Elapsed.TotalMilliseconds -gt $script:latencyMaxMs) {
            $script:latencyMaxMs = $timer.Elapsed.TotalMilliseconds
        }
        return $true
    }
    catch {
        $timer.Stop()
        $script:failed++
        $script:failures[$Class]++
        Write-Warning ("{0} message {1}: {2}" -f $Class, $script:sequence, $_.Exception.Message)
        Disconnect-Gateway
        return $false
    }
}

# Sampling state: vibration 100 ms, flow/status 500 ms, temperature 2 s.
$nextVibration = $startedAt
$nextFlow = $startedAt
$nextTemperature = $startedAt
$nextFast = $startedAt.AddMilliseconds($FastPublishMs)
$nextSlow = $startedAt.AddMilliseconds($SlowPublishMs)
$nextDiagnostic = $startedAt.AddMilliseconds($DiagnosticPublishMs)
$nextStatusChange = $startedAt.AddSeconds(15)
$nextProgress = $startedAt.AddSeconds(15)
$temperature = 35.0
$flowSum = 0.0
$flowMin = [double]::MaxValue
$flowMax = [double]::MinValue
$flowSamples = 0
$vibrationSquareSum = 0.0
$vibrationPeak = 0.0
$vibrationSamples = 0
$diagnosticSamples = New-Object System.Collections.ArrayList
$machineRun = $true
$lastTemperaturePublished = $null
$lastFlowPublished = $null
$lastVibrationPublished = $null
$mqttStart = Get-MqttSnapshot

Write-Host "Multi-rate IIoT workload simulator"
Write-Host "Sampling: vibration=100 ms, flow/status=500 ms, temperature=2000 ms"
Write-Host "Publish: fast=${FastPublishMs} ms, slow=${SlowPublishMs} ms, diagnostic=${DiagnosticPublishMs} ms"
Write-Host "Gateway: ${GatewayIp}:$Port; duration: $DurationSeconds seconds"

try {
    while ((Get-Date) -lt $deadline) {
        $now = Get-Date

        if ($now -ge $nextVibration) {
            $vibration = [Math]::Round(0.45 + (Get-Random -Minimum -20 -Maximum 31) / 100.0, 2)
            $vibrationSquareSum += $vibration * $vibration
            if ($vibration -gt $vibrationPeak) { $vibrationPeak = $vibration }
            $vibrationSamples++
            [void]$diagnosticSamples.Add($vibration)
            if ($diagnosticSamples.Count -gt 100) { $diagnosticSamples.RemoveAt(0) }
            $nextVibration = $nextVibration.AddMilliseconds(100)
        }

        if ($now -ge $nextFlow) {
            $flow = [Math]::Round(125.0 + (Get-Random -Minimum -40 -Maximum 41) / 10.0, 1)
            $flowSum += $flow
            if ($flow -lt $flowMin) { $flowMin = $flow }
            if ($flow -gt $flowMax) { $flowMax = $flow }
            $flowSamples++
            $nextFlow = $nextFlow.AddMilliseconds(500)
        }

        if ($now -ge $nextTemperature) {
            $temperature = [Math]::Round($temperature + (Get-Random -Minimum -3 -Maximum 4) / 10.0, 1)
            $nextTemperature = $nextTemperature.AddMilliseconds(2000)
        }

        if ($now -ge $nextStatusChange) {
            $previous = $machineRun
            $machineRun = -not $machineRun
            [void](Send-Message "event" ([ordered]@{
                tag = "machine_run"; previous = $previous; current = $machineRun;
                reason = if ($machineRun) { "SIMULATED_START" } else { "SIMULATED_STOP" }
            }) "event")
            $nextStatusChange = $nextStatusChange.AddSeconds(15)
        }

        if ($now -ge $nextFast -and $flowSamples -gt 0 -and $vibrationSamples -gt 0) {
            $flowAverage = [Math]::Round($flowSum / $flowSamples, 2)
            $vibrationRms = [Math]::Round([Math]::Sqrt($vibrationSquareSum / $vibrationSamples), 3)
            $flowChanged = ($null -eq $lastFlowPublished -or [Math]::Abs($flowAverage - $lastFlowPublished) -ge $FlowDeadband)
            $vibrationChanged = ($null -eq $lastVibrationPublished -or [Math]::Abs($vibrationRms - $lastVibrationPublished) -ge $VibrationDeadband)
            if ($flowChanged -or $vibrationChanged) {
                [void](Send-Message "fast" ([ordered]@{
                    flow_lpm = [ordered]@{ average = $flowAverage; minimum = $flowMin; maximum = $flowMax; samples = $flowSamples }
                    vibration_mm_s = [ordered]@{ rms = $vibrationRms; peak = $vibrationPeak; samples = $vibrationSamples }
                    machine_run = [ordered]@{ value = $machineRun; changed = $false }
                }))
                $lastFlowPublished = $flowAverage
                $lastVibrationPublished = $vibrationRms
            }
            $flowSum = 0.0; $flowMin = [double]::MaxValue; $flowMax = [double]::MinValue; $flowSamples = 0
            $vibrationSquareSum = 0.0; $vibrationPeak = 0.0; $vibrationSamples = 0
            $nextFast = $nextFast.AddMilliseconds($FastPublishMs)
        }

        if ($now -ge $nextSlow) {
            if ($null -eq $lastTemperaturePublished -or [Math]::Abs($temperature - $lastTemperaturePublished) -ge $TemperatureDeadband) {
                [void](Send-Message "slow" ([ordered]@{
                    temperature_c = [ordered]@{ value = $temperature; sample_interval_ms = 2000; deadband = $TemperatureDeadband }
                }))
                $lastTemperaturePublished = $temperature
            }
            $nextSlow = $nextSlow.AddMilliseconds($SlowPublishMs)
        }

        if ($now -ge $nextDiagnostic) {
            [void](Send-Message "diagnostic" ([ordered]@{
                sample_interval_ms = 100
                vibration_samples_mm_s = @($diagnosticSamples)
            }) "diagnostic")
            $diagnosticSamples.Clear()
            $nextDiagnostic = $nextDiagnostic.AddMilliseconds($DiagnosticPublishMs)
        }

        if ($now -ge $nextProgress) {
            Write-Host ("{0} ACK={1} failed={2} fast={3} slow={4} event={5} diagnostic={6} bytes={7}" -f `
                $now.ToString("HH:mm:ss"), $acknowledged, $failed, $counts.fast, $counts.slow,
                $counts.event, $counts.diagnostic, $payloadBytes)
            $nextProgress = $nextProgress.AddSeconds(15)
        }
        Start-Sleep -Milliseconds 10
    }
}
finally {
    Disconnect-Gateway
    $mqttEnd = Get-MqttSnapshot
    $endedAt = Get-Date
    $attempted = $acknowledged + $failed
    $success = if ($attempted) { [Math]::Round(100.0 * $acknowledged / $attempted, 4) } else { 0 }
    $averageLatency = if ($acknowledged) { [Math]::Round($latencyTotalMs / $acknowledged, 1) } else { 0 }
    $estimated4GBytes = $payloadBytes + ($attempted * 170)
    $mqttPublishedDelta = $mqttEnd.published - $mqttStart.published
    $mqttDroppedDelta = $mqttEnd.dropped - $mqttStart.dropped
    $mqttFailedDelta = $mqttEnd.failed - $mqttStart.failed
    $mqttCoalescedDelta = $mqttEnd.coalesced - $mqttStart.coalesced
    $mqttPriorityEvictionsDelta = $mqttEnd.priority_evictions - $mqttStart.priority_evictions
    $header = 'started_at,ended_at,duration_seconds,attempted,acknowledged,failed,success_percent,fast,slow,event,diagnostic,payload_bytes,estimated_4g_bytes,average_latency_ms,maximum_latency_ms,mqtt_published_delta,mqtt_dropped_delta,mqtt_failed_delta,mqtt_coalesced_delta,mqtt_priority_evictions_delta,mqtt_queue_end'
    $row = '"{0}","{1}",{2},{3},{4},{5},{6},{7},{8},{9},{10},{11},{12},{13},{14},{15},{16},{17},{18},{19},{20}' -f `
        $startedAt.ToString("o"), $endedAt.ToString("o"), [Math]::Round(($endedAt-$startedAt).TotalSeconds,1),
        $attempted, $acknowledged, $failed, $success, $counts.fast, $counts.slow, $counts.event,
        $counts.diagnostic, $payloadBytes, $estimated4GBytes, $averageLatency, [Math]::Round($latencyMaxMs,1),
        $mqttPublishedDelta, $mqttDroppedDelta, $mqttFailedDelta, $mqttCoalescedDelta,
        $mqttPriorityEvictionsDelta, $mqttEnd.queued
    @($header, $row) | Set-Content -LiteralPath $resultPath -Encoding UTF8
    Write-Host ""
    Write-Host "Multi-rate test finished: ACK=$acknowledged/$attempted failed=$failed success=$success%"
    Write-Host "Messages: fast=$($counts.fast) slow=$($counts.slow) event=$($counts.event) diagnostic=$($counts.diagnostic)"
    Write-Host "JSON/TCP bytes: $payloadBytes; estimated MQTT/TLS/IP bytes: $estimated4GBytes"
    Write-Host "Latency: average=$averageLatency ms maximum=$([Math]::Round($latencyMaxMs,1)) ms"
    Write-Host "MQTT: published=$mqttPublishedDelta dropped=$mqttDroppedDelta coalesced=$mqttCoalescedDelta priority_evictions=$mqttPriorityEvictionsDelta failed=$mqttFailedDelta queue_end=$($mqttEnd.queued)"
    Write-Host "Result: $resultPath"
}

if ($failed -gt 0) { exit 1 }
