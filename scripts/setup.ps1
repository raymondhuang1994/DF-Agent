[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('Plan', 'Apply', 'Status')][string]$Action,
    [string]$StateDir,
    [string[]]$Roots,
    [string]$PythonPath,
    [string]$OutputPath,
    [string]$PlanPath,
    [string]$BindingsPath,
    [string]$SessionId = 'unspecified'
)
$ErrorActionPreference = 'Stop'
$EntrySetup = Join-Path $PSScriptRoot '../plugins/team-advisor-entry/skills/team-advisor/scripts/setup.ps1'
& $EntrySetup @PSBoundParameters
