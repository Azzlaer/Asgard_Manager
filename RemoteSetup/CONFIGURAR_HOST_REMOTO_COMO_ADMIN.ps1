#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Write-Host '=== ASGARD Remote Host Bootstrap ===' -ForegroundColor Cyan

$cap = Get-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0'
if ($cap.State -ne 'Installed') {
    Write-Host 'Instalando OpenSSH Server...'
    Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Host
}
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 | Out-Null
}

$group = Get-LocalGroup -Name 'OpenSSH Users' -ErrorAction SilentlyContinue
if ($group) {
    $current = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    try { Add-LocalGroupMember -Group 'OpenSSH Users' -Member $current -ErrorAction Stop } catch {}
}

$tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
if (-not $tailscale) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host 'Tailscale no está instalado. Intentando instalarlo con winget...'
        try {
            & $winget.Source install --id Tailscale.Tailscale -e --accept-package-agreements --accept-source-agreements
            $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
            if (-not $tailscale -and (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) {
                $tailscale = Get-Item "$env:ProgramFiles\Tailscale\tailscale.exe"
            }
        } catch {
            Write-Host "No se pudo instalar Tailscale automáticamente: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }
}
if ($tailscale) {
    $tailscalePath = if ($tailscale.Source) { $tailscale.Source } else { $tailscale.FullName }
    Write-Host 'Tailscale detectado. Activando modo unattended...'
    & $tailscalePath up --unattended=true
    & $tailscalePath ip -4
} else {
    Write-Host 'Tailscale requiere instalación o autorización manual en este equipo.' -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'OpenSSH quedó instalado, iniciado y configurado en el puerto 22.' -ForegroundColor Green
Write-Host 'Regresa al panel ASGARD, agrega este host y pulsa Probar SSH.' -ForegroundColor Green
Read-Host 'Presiona ENTER para cerrar'
