[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string[]]$Roots,
    [string]$OutputPath,
    [string]$PythonPath,
    [string]$HostEvidencePath,
    [string]$BindingsPath,
    [string]$EnvironmentPath,
    [string]$SessionId = 'unspecified',
    [string]$TaskId,
    [string[]]$WriteRoot,
    [ValidateSet('setup', 'memory', 'feedback', 'output', 'runtime')][string[]]$AllowOperation,
    [string[]]$DocumentRoot
)
$ErrorActionPreference = 'Stop'
$EntryDoctor = Join-Path $PSScriptRoot '../plugins/df-agent/skills/df-agent/scripts/doctor.ps1'
& $EntryDoctor @PSBoundParameters
