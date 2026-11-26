<#
  Elimina el clúster EKS emulado del Equipo 5 y apaga Floci.
  Uso: powershell -ExecutionPolicy Bypass -File floci/eliminar-cluster.ps1
#>
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$env:AWS_ACCESS_KEY_ID     = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$Endpoint = "http://localhost:4566"

aws --endpoint-url $Endpoint --region us-east-1 eks delete-cluster --name voltrix-equipo5 | Out-Null
kubectl config delete-context voltrix-equipo5 2>&1 | Out-Null
docker compose -f docker-compose.yml down
Write-Host "Clúster eliminado y Floci detenido."
