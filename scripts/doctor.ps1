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
$EntryDoctor = Join-Path $PSScriptRoot '../plugins/team-advisor-entry/skills/team-advisor/scripts/doctor.ps1'
& $EntryDoctor @PSBoundParameters
