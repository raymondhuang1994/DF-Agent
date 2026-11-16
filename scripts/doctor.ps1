[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Roots,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$PythonPath,
    [string]$HostEvidencePath,
    [string]$BindingsPath,
    [string]$EnvironmentPath,
    [string]$SessionId = 'unspecified'
)
$ErrorActionPreference = 'Stop'
$EntryDoctor = Join-Path $PSScriptRoot '../plugins/df-agent/skills/df-agent/scripts/doctor.ps1'
& $EntryDoctor @PSBoundParameters
