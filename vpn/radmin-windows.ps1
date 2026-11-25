[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Config,
    [ValidateSet('wake','health')][string]$Action = 'health'
)
$ErrorActionPreference = 'Stop'
$vpn = Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json

function Test-Tunnel {
    $adapter = Get-NetAdapter -Name $vpn.adapter -ErrorAction SilentlyContinue
    if (!$adapter -or $adapter.Status -ne 'Up') { return $false }
    $addresses = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -ErrorAction SilentlyContinue
    if (!($addresses | Where-Object AddressState -eq 'Preferred')) { return $false }
    if (!$vpn.peer) { return $true }
    $route = Find-NetRoute -RemoteIPAddress $vpn.peer -ErrorAction SilentlyContinue
    if (!($route | Where-Object InterfaceIndex -eq $adapter.ifIndex)) { return $false }
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connection = $client.ConnectAsync([System.Net.IPAddress]::Parse($vpn.peer), [int]$vpn.port)
        return ($connection.Wait(3000) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

if ($Action -eq 'wake' -and !(Test-Tunnel)) {
    if ($vpn.service) {
        $service = Get-Service -Name $vpn.service
        if ($service.Status -eq 'Stopped') { Start-Service -Name $vpn.service }
    }
    if ($vpn.program) {
        $program = (Resolve-Path -LiteralPath $vpn.program).Path
        $name = [System.IO.Path]::GetFileNameWithoutExtension($program)
        if (!(Get-Process -Name $name -ErrorAction SilentlyContinue | Where-Object Path -eq $program)) {
            Start-Process -FilePath $program
        }
    }
}
$deadline = [DateTime]::UtcNow.AddSeconds([int]$vpn.timeoutSeconds)
do {
    if (Test-Tunnel) {
        Write-Output 'Radmin VPN ready for the configured probe'
        exit 0
    }
    if ($Action -eq 'health') { break }
    Start-Sleep -Seconds 1
} while ([DateTime]::UtcNow -lt $deadline)
Write-Error 'Radmin VPN did not pass the configured probe'
