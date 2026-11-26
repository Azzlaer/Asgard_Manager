param(
    [string]$ServerRoot = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $PSScriptRoot

function Normalize-PathInput([string]$Value) {
    if ($null -eq $Value) { return "" }
    return $Value.Trim().Trim('"').Trim("'")
}

function Select-ServerFolder {
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = "Selecciona la carpeta que contiene valheim_server.exe"
    $dialog.ShowNewFolderButton = $false
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        return $dialog.SelectedPath
    }
    return ""
}

function Resolve-ServerRoot([string]$Candidate) {
    $candidatePath = Normalize-PathInput $Candidate
    if ([string]::IsNullOrWhiteSpace($candidatePath)) {
        Write-Host "Selecciona la carpeta raiz del servidor dedicado de Valheim." -ForegroundColor Cyan
        try { $candidatePath = Select-ServerFolder } catch { $candidatePath = "" }
    }
    if ([string]::IsNullOrWhiteSpace($candidatePath)) {
        $candidatePath = Normalize-PathInput (Read-Host "Arrastra aqui la carpeta que contiene valheim_server.exe y presiona Enter")
    }
    if ([string]::IsNullOrWhiteSpace($candidatePath)) {
        throw "No se selecciono ninguna carpeta."
    }
    if (-not (Test-Path -LiteralPath $candidatePath -PathType Container)) {
        throw "La carpeta no existe: $candidatePath"
    }

    $directExe = Join-Path $candidatePath "valheim_server.exe"
    if (Test-Path -LiteralPath $directExe -PathType Leaf) {
        return (Resolve-Path -LiteralPath $candidatePath).Path
    }

    Write-Host "No encontre valheim_server.exe directamente. Buscando dentro de la carpeta..." -ForegroundColor Yellow
    $matches = @(Get-ChildItem -LiteralPath $candidatePath -Filter "valheim_server.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 20)
    if ($matches.Count -eq 1) {
        return $matches[0].Directory.FullName
    }
    if ($matches.Count -gt 1) {
        Write-Host "Se encontraron varios servidores:" -ForegroundColor Yellow
        for ($i=0; $i -lt $matches.Count; $i++) {
            Write-Host ("[{0}] {1}" -f ($i+1), $matches[$i].Directory.FullName)
        }
        $choice = 0
        while ($choice -lt 1 -or $choice -gt $matches.Count) {
            [void][int]::TryParse((Read-Host "Selecciona el numero del servidor"), [ref]$choice)
        }
        return $matches[$choice-1].Directory.FullName
    }
    throw "No se encontro valheim_server.exe en la carpeta seleccionada."
}

function Require-File([string]$Path, [string]$Description) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "No se encontro $Description`: $Path"
    }
}

$root = Resolve-ServerRoot $ServerRoot
$managed = Join-Path $root "valheim_server_Data\Managed"
$bepCore = Join-Path $root "BepInEx\core"

Require-File (Join-Path $root "valheim_server.exe") "valheim_server.exe"
Require-File (Join-Path $managed "assembly_valheim.dll") "assembly_valheim.dll"
Require-File (Join-Path $managed "UnityEngine.CoreModule.dll") "UnityEngine.CoreModule.dll"
Require-File (Join-Path $managed "UnityEngine.InputLegacyModule.dll") "UnityEngine.InputLegacyModule.dll"
Require-File (Join-Path $managed "UnityEngine.TextRenderingModule.dll") "UnityEngine.TextRenderingModule.dll"
Require-File (Join-Path $managed "UnityEngine.ParticleSystemModule.dll") "UnityEngine.ParticleSystemModule.dll"
Require-File (Join-Path $bepCore "BepInEx.dll") "BepInEx.dll"
Require-File (Join-Path $bepCore "0Harmony.dll") "0Harmony.dll"

$jotunn = $null
$pluginsRoot = Join-Path $root "BepInEx\plugins"
if (Test-Path -LiteralPath $pluginsRoot -PathType Container) {
    $jotunn = Get-ChildItem -LiteralPath $pluginsRoot -Filter "Jotunn.dll" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
}
$buildEnhanced = $null -ne $jotunn
$jotunnPath = if ($buildEnhanced) { $jotunn.FullName } else { "" }

$project = New-Object System.Xml.XmlDocument
$declaration = $project.CreateXmlDeclaration("1.0", "utf-8", $null)
[void]$project.AppendChild($declaration)
$projectNode = $project.CreateElement("Project")
[void]$project.AppendChild($projectNode)
$group = $project.CreateElement("PropertyGroup")
[void]$projectNode.AppendChild($group)

$values = [ordered]@{
    ValheimServerRoot = $root
    ValheimManaged    = $managed
    BepInExCore       = $bepCore
    JotunnDll         = $jotunnPath
    BuildEnhanced     = $(if ($buildEnhanced) { "true" } else { "false" })
}
foreach ($entry in $values.GetEnumerator()) {
    $node = $project.CreateElement($entry.Key)
    $node.InnerText = [string]$entry.Value
    [void]$group.AppendChild($node)
}

$outPath = Join-Path $scriptRoot "UserPaths.props"
$settings = New-Object System.Xml.XmlWriterSettings
$settings.Indent = $true
$settings.Encoding = New-Object System.Text.UTF8Encoding($false)
$writer = [System.Xml.XmlWriter]::Create($outPath, $settings)
try { $project.Save($writer) } finally { $writer.Dispose() }

Write-Host ""
Write-Host "CONFIGURACION AUTOMATICA COMPLETA" -ForegroundColor Green
Write-Host "Servidor: $root"
Write-Host "Managed:  $managed"
Write-Host "BepInEx:  $bepCore"
if ($buildEnhanced) {
    Write-Host "Jotunn:   $jotunnPath" -ForegroundColor Green
    Write-Host "Avatar Enhanced: habilitado (ParticleSystemModule detectado)" -ForegroundColor Green
} else {
    Write-Host "Jotunn:   no encontrado" -ForegroundColor Yellow
    Write-Host "Avatar Enhanced: se omitira; ServerBase y AdminClient se compilaran normalmente." -ForegroundColor Yellow
}
Write-Host "Rutas guardadas en: $outPath"
