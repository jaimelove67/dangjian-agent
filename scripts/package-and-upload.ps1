# dangjian-agent - package project and upload to server
#
# Usage (PowerShell, project root):
#   .\scripts\package-and-upload.ps1 -ServerIp 123.45.67.89 -User root
# Options:
#   -KeyPath        SSH private key path (default ~/.ssh/id_ed25519)
#   -RemotePath     Destination dir on server (default /root/dangjian-agent)
#   -SkipUpload     Package only, do not upload
#
# Requires: built-in tar.exe and OpenSSH client.

param(
    [Parameter(Mandatory = $true)][string]$ServerIp,
    [string]$User = "root",
    [string]$KeyPath = "$env:USERPROFILE\.ssh\id_ed25519",
    [string]$RemotePath = "/root/dangjian-agent",
    [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Archive = Join-Path $env:TEMP "dangjian-agent-$Stamp.tar.gz"

Write-Host "[1/3] Packaging project -> $Archive" -ForegroundColor Cyan

$tarArgs = @(
    "-czf", $Archive,
    "--exclude=.git",
    "--exclude=.env", "--exclude=.env.*",   # 本机密钥不入包；服务器用环境模板自行配置
    "--exclude=.venv", "--exclude=.venv-module6",
    "--exclude=node_modules",
    "--exclude=uploads", "--exclude=audit-spool",
    "--exclude=logs", "--exclude=tmp", "--exclude=temp",
    "--exclude=backups", "--exclude=data",
    "--exclude=.idea", "--exclude=.vscode", "--exclude=.workbuddy",
    "--exclude=.claude", "--exclude=.sisyphus", "--exclude=.playwright-mcp",
    "--exclude=.mypy_cache", "--exclude=.pytest_cache", "--exclude=.ruff_cache",
    "--exclude=*.log", "--exclude=*.db", "--exclude=*.sqlite*",
    "-C", $Root,
    "."
)

& tar @tarArgs
if ($LASTEXITCODE -ne 0) { throw "tar failed (exit $LASTEXITCODE)" }

$sizeMB = [math]::Round((Get-Item $Archive).Length / 1MB, 1)
Write-Host "    Done, $sizeMB MB" -ForegroundColor Green

if ($SkipUpload) {
    Write-Host "[2/3] Upload skipped. Archive: $Archive" -ForegroundColor Yellow
    Write-Host "   On server, extract with:" -ForegroundColor Yellow
    Write-Host "   mkdir -p $RemotePath; tar -xzf <archive> -C $RemotePath" -ForegroundColor Yellow
    return
}

Write-Host "[2/3] Connecting to $User@$ServerIp, creating dir and uploading" -ForegroundColor Cyan
$sshOpt = @("-o", "StrictHostKeyChecking=accept-new")
if (Test-Path $KeyPath) { $sshOpt += @("-i", $KeyPath) }

& ssh @sshOpt "$User@$ServerIp" "mkdir -p $RemotePath"
if ($LASTEXITCODE -ne 0) { throw "SSH connection failed. Check IP/user/key." }

& scp @sshOpt $Archive "$User@$ServerIp`:$RemotePath/dangjian-agent.tar.gz"
if ($LASTEXITCODE -ne 0) { throw "scp upload failed" }

Write-Host "[3/3] Extracting on server" -ForegroundColor Cyan
& ssh @sshOpt "$User@$ServerIp" "cd $RemotePath; tar -xzf dangjian-agent.tar.gz; rm dangjian-agent.tar.gz; ls | head -20"
if ($LASTEXITCODE -ne 0) { throw "Extract on server failed" }

Write-Host "Done! Next run deploy/server/setup.sh on the server to install Docker and deploy." -ForegroundColor Green