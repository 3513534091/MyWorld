#!/usr/bin/env pwsh
# MyWorld 启动脚本（Windows）
# 用法：.\run.ps1            使用默认端口
#       .\run.ps1 --port 9000 --open

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root

try {
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m myworld @args
    }
    elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m myworld @args
    }
    else {
        throw "未找到 python，请先安装 Python 3.10+ 并加入 PATH"
    }
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
