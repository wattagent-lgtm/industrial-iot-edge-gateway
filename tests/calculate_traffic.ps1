[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 1048576)]
    [int]$PayloadBytes,

    [ValidateRange(1, 65535)]
    [int]$TopicBytes = 70,

    [Parameter(Mandatory = $true)]
    [ValidateRange(0.000001, 1000000)]
    [double]$MessagesPerSecond,

    [ValidateRange(1, 366)]
    [int]$Days = 30,

    [ValidateRange(0, 65535)]
    [int]$OverheadBytes = 100,

    [ValidateRange(0, 1000)]
    [double]$MarginPercent = 20
)

$ErrorActionPreference = 'Stop'
$secondsPerDay = 86400.0
$bytesPerMessage = [double]($PayloadBytes + $TopicBytes + $OverheadBytes)
$messagesPerDay = $MessagesPerSecond * $secondsPerDay
$messagesForPeriod = $messagesPerDay * $Days
$baseBytes = $bytesPerMessage * $messagesForPeriod
$marginMultiplier = 1.0 + ($MarginPercent / 100.0)
$plannedBytes = $baseBytes * $marginMultiplier

$result = [pscustomobject]@{
    PayloadBytes          = $PayloadBytes
    TopicBytes            = $TopicBytes
    PlanningOverheadBytes = $OverheadBytes
    BytesPerMessage       = [math]::Round($bytesPerMessage, 2)
    MessagesPerSecond     = $MessagesPerSecond
    MessagesPerDay        = [math]::Round($messagesPerDay, 2)
    PeriodDays            = $Days
    MessagesForPeriod     = [math]::Round($messagesForPeriod, 2)
    BaseMBDecimal         = [math]::Round($baseBytes / 1000000.0, 3)
    BaseGBDecimal         = [math]::Round($baseBytes / 1000000000.0, 3)
    MarginPercent         = $MarginPercent
    PlannedGBDecimal      = [math]::Round($plannedBytes / 1000000000.0, 3)
    PlannedGiBBinary      = [math]::Round($plannedBytes / 1GB, 3)
}

$result | Format-List
