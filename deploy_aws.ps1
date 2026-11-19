# ==============================================================================
# TripPlanner AI — Script de Despliegue en AWS (SAM/CloudFormation + S3 + AgentCore)
# ==============================================================================
param(
    [string]$Region = "us-east-1",
    [string]$StackName = "tripplanner-ai-stack"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " ☁️ Desplegando TripPlanner AI en AWS ($Region)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Obtener Account ID
$accountId = (aws sts get-caller-identity --query Account --output text).Trim()
Write-Host "Cuenta AWS detectada: $accountId" -ForegroundColor Green

# 2. Crear bucket de artefactos SAM si no existe
$artifactBucket = "tripplanner-sam-artifacts-$accountId-$Region"
Write-Host "[1/4] Verificando bucket de artefactos CloudFormation: $artifactBucket..." -ForegroundColor Yellow
aws s3 mb "s3://$artifactBucket" --region $Region 2>$null

# 3. Empaquetar y desplegar template.yaml (DynamoDB + 8 Lambdas + API Gateway + S3 Website)
Write-Host "[2/4] Empaquetando y desplegando infraestructura Serverless (template.yaml)..." -ForegroundColor Yellow
aws cloudformation package `
    --template-file template.yaml `
    --s3-bucket $artifactBucket `
    --output-template-file packaged.yaml `
    --region $Region

aws cloudformation deploy `
    --template-file packaged.yaml `
    --stack-name $StackName `
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND `
    --region $Region

# 4. Obtener Outputs y sincronizar Frontend a S3
$apiUrl = (aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs[?OutputKey=='ApiGatewayUrl'].OutputValue" --output text).Trim()
$frontendBucket = (aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" --output text).Trim()
$websiteUrl = (aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs[?OutputKey=='FrontendWebsiteUrl'].OutputValue" --output text).Trim()

Write-Host "[3/4] Publicando Frontend (frontend/index.html) en S3 Bucket: $frontendBucket..." -ForegroundColor Yellow
aws s3 sync frontend/ "s3://$frontendBucket/" --region $Region

Write-Host "[4/4] Validando configuración de Amazon Bedrock AgentCore..." -ForegroundColor Yellow
agentcore validate

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Green
Write-Host " ✅ DESPLIEGUE SERVERLESS COMPLETADO" -ForegroundColor Green
Write-Host " • Canal 1 (API Gateway): $apiUrl" -ForegroundColor Cyan
Write-Host " • Hosting Frontend (S3): $websiteUrl" -ForegroundColor Cyan
Write-Host " • Para actualizar los runtimes AgentCore ejecuta: agentcore deploy" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Green
