# Floci EKS — Componente A (orquestación)

Clúster EKS emulado con [Floci](https://floci.io) y manifiestos de Kubernetes
del servicio **Pronóstico de Generación (Equipo 5)**. Todo queda como código
para que un tercero lo reproduzca sin pasos manuales.

```text
floci/
├── docker-compose.yml        # Emulador AWS local (puerto 4566)
├── crear-cluster.ps1 / .sh   # IaC: IAM + clúster EKS + kubeconfig
├── eliminar-cluster.ps1 / .sh
├── iam/
│   ├── eks-cluster-trust-policy.json  # Rol del clúster (lo asume eks.amazonaws.com)
│   └── deployer-policy.json           # Usuario de kubectl: solo eks:DescribeCluster
└── k8s/
    ├── 00-namespace.yaml
    ├── 01-configmap.yaml         # Variables y URLs de los equipos 1, 2 y 4
    ├── 02-secret.yaml            # Credenciales de la BD
    ├── 03-postgres.yaml          # BD liviana compartida por las réplicas
    ├── 04-deployment.yaml        # API con 2 réplicas y probes a /health
    └── 05-service.yaml           # Enruta peticiones a las réplicas
```

## Requisitos

- Docker en **modo root**: Docker Desktop (Windows/macOS) o Docker Engine rootful
  (Linux). Docker rootless y Podman no sirven: k3s necesita acceso al kernel.
- AWS CLI v2 (2.13 o superior) y kubectl.

## 1. Crear el clúster (Avance 1)

Windows (PowerShell, desde la raíz del repo):

```powershell
powershell -ExecutionPolicy Bypass -File floci/crear-cluster.ps1
```

Linux/macOS:

```bash
bash floci/crear-cluster.sh
```

El script levanta Floci, crea el rol IAM del clúster y un usuario IAM con
mínimo privilegio para kubectl, crea el clúster `voltrix-equipo5`, espera el
estado `ACTIVE` y configura el contexto de kubectl.

Evidencia:

```bash
aws --endpoint-url http://localhost:4566 --region us-east-1 eks list-clusters
aws --endpoint-url http://localhost:4566 --region us-east-1 eks describe-cluster --name voltrix-equipo5
kubectl --context voltrix-equipo5 get nodes -o wide
```

## 2. Desplegar el servicio (Avance 2)

Construir la imagen y cargarla en el nodo k3s del clúster (el nombre del
contenedor se confirma con `docker ps`):

```bash
docker build -t voltrix-equipo5-pronostico:1.0.0 .
docker save -o pronostico.tar voltrix-equipo5-pronostico:1.0.0
docker cp pronostico.tar floci-aws-eks-voltrix-equipo5:/tmp/pronostico.tar
docker exec floci-aws-eks-voltrix-equipo5 k3s ctr images import /tmp/pronostico.tar
```

Aplicar los manifiestos y verificar las 2 réplicas:

```bash
kubectl --context voltrix-equipo5 apply -f floci/k8s/
kubectl --context voltrix-equipo5 -n voltrix-equipo5 get pods,svc
kubectl --context voltrix-equipo5 -n voltrix-equipo5 port-forward svc/pronostico-api 8080:8000
# En otra terminal: curl http://localhost:8080/health
```

## 3. Eliminar

```powershell
powershell -ExecutionPolicy Bypass -File floci/eliminar-cluster.ps1
```
