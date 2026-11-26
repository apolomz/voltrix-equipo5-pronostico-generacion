<#
  Voltrix Energy - Equipo 5 (Pronóstico de Generación)
  Componente A: crea el clúster EKS emulado en Floci como código (IaC).

  Requisitos: Docker Desktop encendido, AWS CLI v2 y kubectl.
  Uso (desde la raíz del repo):
      powershell -ExecutionPolicy Bypass -File floci/crear-cluster.ps1

  El script es idempotente: si el rol, el usuario o el clúster ya existen,
  los reutiliza en lugar de fallar.
#>

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$ClusterName = "voltrix-equipo5"
$Region      = "us-east-1"
$Endpoint    = "http://localhost:4566"
$RoleName    = "voltrix-equipo5-eks-cluster-role"
$UserName    = "voltrix-equipo5-deployer"
$AwsProfile  = "floci-voltrix"

function Invoke-Floci { & aws --endpoint-url $Endpoint --region $Region @args }
function Assert-Ok([string]$Mensaje) { if ($LASTEXITCODE -ne 0) { throw $Mensaje } }
function Paso([string]$Texto) { Write-Host "`n==> $Texto" -ForegroundColor Cyan }

# --- 0. Herramientas necesarias -------------------------------------------
Paso "Verificando herramientas (docker, aws, kubectl)"
foreach ($cmd in "docker", "aws", "kubectl") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "Falta '$cmd'. Instálalo y vuelve a ejecutar el script."
    }
}

# Credenciales administrativas del emulador: solo sirven contra Floci.
$env:AWS_ACCESS_KEY_ID     = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_DEFAULT_REGION    = $Region
Remove-Item Env:AWS_PROFILE -ErrorAction SilentlyContinue

# --- 1. Levantar Floci ----------------------------------------------------
Paso "Levantando Floci (docker compose)"
docker compose -f docker-compose.yml up -d
Assert-Ok "No se pudo levantar Floci. ¿Docker Desktop está encendido?"

Write-Host "Esperando a que Floci responda en $Endpoint ..."
$listo = $false
for ($i = 1; $i -le 30; $i++) {
    $null = Invoke-Floci sts get-caller-identity 2>&1
    if ($LASTEXITCODE -eq 0) { $listo = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $listo) { throw "Floci no respondió a tiempo. Revisa: docker logs voltrix-floci" }

# --- 2. Rol IAM del clúster (mínimo privilegio) ---------------------------
Paso "Rol IAM del clúster: $RoleName"
$null = Invoke-Floci iam get-role --role-name $RoleName 2>&1
if ($LASTEXITCODE -ne 0) {
    Invoke-Floci iam create-role --role-name $RoleName `
        --assume-role-policy-document file://iam/eks-cluster-trust-policy.json | Out-Null
    Assert-Ok "No se pudo crear el rol $RoleName"
}
Invoke-Floci iam attach-role-policy --role-name $RoleName `
    --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Warning "No se pudo adjuntar AmazonEKSClusterPolicy (se continúa)." }
$RoleArn = Invoke-Floci iam get-role --role-name $RoleName --query Role.Arn --output text
Write-Host "Rol: $RoleArn"

# --- 3. Usuario IAM para kubectl (solo eks:DescribeCluster) ---------------
Paso "Usuario IAM de despliegue: $UserName"
$null = Invoke-Floci iam get-user --user-name $UserName 2>&1
if ($LASTEXITCODE -ne 0) {
    Invoke-Floci iam create-user --user-name $UserName | Out-Null
    Assert-Ok "No se pudo crear el usuario $UserName"
}
Invoke-Floci iam put-user-policy --user-name $UserName `
    --policy-name voltrix-equipo5-describe-cluster `
    --policy-document file://iam/deployer-policy.json | Out-Null
Assert-Ok "No se pudo asignar la política al usuario"

# Se renuevan las llaves en cada ejecución para no dejar llaves viejas.
$llaves = Invoke-Floci iam list-access-keys --user-name $UserName `
    --query "AccessKeyMetadata[].AccessKeyId" --output text
foreach ($id in ("$llaves" -split "\s+" | Where-Object { $_ })) {
    Invoke-Floci iam delete-access-key --user-name $UserName --access-key-id $id | Out-Null
}
$json  = Invoke-Floci iam create-access-key --user-name $UserName --output json
Assert-Ok "No se pudo crear la llave de acceso"
$llave = ($json -join "`n") | ConvertFrom-Json

# Perfil local de AWS CLI (queda en ~/.aws, nunca en el repositorio).
aws configure set aws_access_key_id     $llave.AccessKey.AccessKeyId     --profile $AwsProfile
aws configure set aws_secret_access_key $llave.AccessKey.SecretAccessKey --profile $AwsProfile
aws configure set region       $Region   --profile $AwsProfile
aws configure set endpoint_url $Endpoint --profile $AwsProfile
Write-Host "Perfil '$AwsProfile' configurado."

# --- 4. Clúster EKS emulado ----------------------------------------------
Paso "Clúster EKS: $ClusterName"
$null = Invoke-Floci eks describe-cluster --name $ClusterName 2>&1
if ($LASTEXITCODE -ne 0) {
    Invoke-Floci eks create-cluster --name $ClusterName --role-arn $RoleArn `
        --resources-vpc-config '{}' | Out-Null
    Assert-Ok "No se pudo crear el clúster $ClusterName"
} else {
    Write-Host "El clúster ya existe; se reutiliza."
}

Write-Host "Esperando estado ACTIVE (Floci arranca un nodo k3s) ..."
$estado = ""
for ($i = 1; $i -le 60; $i++) {
    $estado = Invoke-Floci eks describe-cluster --name $ClusterName --query cluster.status --output text
    Write-Host "  [$i] estado: $estado"
    if ($estado -eq "ACTIVE") { break }
    if ($estado -eq "FAILED") { throw "El clúster quedó en FAILED. Revisa: docker logs voltrix-floci" }
    Start-Sleep -Seconds 5
}
if ($estado -ne "ACTIVE") { throw "El clúster no llegó a ACTIVE a tiempo." }

# --- 5. kubeconfig --------------------------------------------------------
Paso "Configurando kubectl (contexto $ClusterName)"
# Se quitan las credenciales 'test' para que kubectl use el perfil del usuario.
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY -ErrorAction SilentlyContinue
aws eks update-kubeconfig --name $ClusterName --region $Region `
    --profile $AwsProfile --alias $ClusterName
Assert-Ok "No se pudo actualizar el kubeconfig"

# --- 6. Verificación ------------------------------------------------------
Paso "Verificación con kubectl"
kubectl --context $ClusterName wait --for=condition=Ready node --all --timeout=180s
kubectl --context $ClusterName get nodes -o wide
kubectl --context $ClusterName cluster-info

Write-Host "`nClúster '$ClusterName' listo en Floci." -ForegroundColor Green
