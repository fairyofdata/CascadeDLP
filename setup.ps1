# CascadeDLP 초기 설정 — PowerShell에서 .\setup.ps1
# 1) venv  2) 핵심 의존성  3) 선택 의존성(실패해도 계속)  4) Ollama 모델  5) 스모크 테스트
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== 1. venv ==" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { py -3.14 -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null

Write-Host "== 2. 핵심 의존성 ==" -ForegroundColor Cyan
& $py -m pip install -r requirements.txt

& $py -m pip install -e ".[mcp]"   # cascadedlp / cascadedlp-mcp 명령 설치 (레이어)

Write-Host "== 3. 선택 의존성 (NER 기준선, 실패해도 계속) ==" -ForegroundColor Cyan
try { & $py -m pip install -r requirements-optional.txt }
catch { Write-Host "선택 의존성 설치 실패 — Python 3.14 호환 문제일 수 있음. PLAN.md에 기록하고 규칙+LLM으로 진행." -ForegroundColor Yellow }

Write-Host "== 4. Ollama 모델 ==" -ForegroundColor Cyan
ollama --version
$models = @("qwen3:8b", "qwen3.5:9b", "qwen3.5:4b")  # 2026-09-29 변경, PLAN.md 참고
foreach ($m in $models) {
  Write-Host "pull $m"
  ollama pull $m
  if ($LASTEXITCODE -ne 0) { Write-Host "$m 실패 — 태그를 확인하세요 (대안: qwen2.5:7b-instruct-q4_K_M)" -ForegroundColor Yellow }
}
ollama list

Write-Host "== 5. 스모크 테스트 ==" -ForegroundColor Cyan
& $py tools\smoke_test.py
