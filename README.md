# TripPlanner AI · Your AI Travel Companion 🧭✈️🌦️

**Trabajo Final · Programación Agéntica — Del Playground a una plataforma inteligente para planificar y gestionar viajes**

Plataforma web distribuida sobre **AWS** que integra un sistema **multiagente real** en **Amazon Bedrock AgentCore** (**Strands Agents**, protocolo **A2A**, servidores **MCP** de vuelos y clima, y **AgentCore Memory**) con un backend **Serverless** (**Amazon API Gateway**, **8 funciones AWS Lambda** y **3 tablas en Amazon DynamoDB**) y un **Frontend de 6 módulos** publicado en **Amazon S3**.

---

## 🏛️ Arquitectura General (Dos Canales Independientes)

```mermaid
flowchart TB
    subgraph S3["🌐 Hosting Frontend (Amazon S3)"]
        UI["🖥️ Plataforma Web TripPlanner AI (6 Módulos)\n1. Dashboard · 2. Asistente IA · 3. Vuelos\n4. Clima · 5. Mis Viajes e Itinerarios · 6. Reservas"]
    end

    subgraph Canal1["⚡ CANAL 1: Operaciones de Negocio (Frontend → API Gateway → Lambda → DynamoDB)"]
        APIGW["🚪 Amazon API Gateway\n(TripPlanner-Business-API)"]
        Lambdas["λ 8 Funciones AWS Lambda\nCreateTrip · GetTrips · UpdateTrip\nCreateItinerary · UpdateItinerary\nCreateReservation · GetReservations · UpdateReservation"]
    end

    subgraph Canal2["🧠 CANAL 2: Interacción Agéntica (Frontend → HTTP Streaming → Bedrock AgentCore)"]
        Orch["🧭 OrchestratorAgent (HTTP Streaming :8080)\nStrands Agent + 8 Business Tools + A2A Clients"]
        Memory[("🧠 AgentCore Memory\nPreferencias · Resúmenes · Hechos · Episodios")]
        Flights["✈️ FlightsAgent (A2A :9001)\n+ MCP de Vuelos (Streamable HTTP)"]
        Weather["🌦️ WeatherAgent (A2A :9002)\n+ MCP de Clima (Streamable HTTP)"]
    end

    subgraph DDB["🗄️ Persistencia Transaccional (Amazon DynamoDB)"]
        T1[("📦 TripPlanner-Trips")]
        T2[("🗓️ TripPlanner-Itineraries")]
        T3[("🎫 TripPlanner-Reservations")]
    end

    UI ==>|"Canal 1: REST JSON (CORS)"| APIGW
    APIGW --> Lambdas
    Lambdas --> T1 & T2 & T3

    UI ==>|"Canal 2: HTTP POST /invocations (SSE Streaming)"| Orch
    Orch <--> Memory
    Orch -->|"Protocolo A2A"| Flights
    Orch -->|"Protocolo A2A"| Weather
    Orch -.->|"InvokeFunction (8 Tools)"| Lambdas
```

---

## 🧩 Los 3 Agentes en Amazon Bedrock AgentCore (Requisito No Negociable)

| Agente | Protocolo | Puerto Local | Especialidad y Conexiones |
| :--- | :---: | :---: | :--- |
| **`OrchestratorAgent`** | `HTTP Streaming` | `8080` | Interactúa con el usuario en streaming, gestiona `TripPlannerMemory`, delega vía **A2A** en `FlightsAgent` y `WeatherAgent`, y ejecuta las **8 Tools de negocio** respaldadas por AWS Lambda + DynamoDB. |
| **`FlightsAgent`** | `A2A` | `9001` | Especialista en cotización de vuelos conectado a servidor **MCP de Vuelos** (`search_airports`, `search_flights`) sobre Streamable HTTP. |
| **`WeatherAgent`** | `A2A` | `9002` | Especialista meteorológico conectado a servidor **MCP de Clima** (`get_forecast` / `mcp_get_weather`) sobre Streamable HTTP con pronóstico multipunto por días. |

---

## 🛠️ Las 8 Tools Obligatorias y Respaldo en AWS Lambda + DynamoDB

| Tool | Propósito | Función AWS Lambda | Ruta API Gateway (Canal 1) | Tabla DynamoDB |
| :--- | :--- | :--- | :--- | :--- |
| **`CreateTrip`** | Crear un viaje del usuario | `TripPlanner-CreateTrip` | `POST /trips` | `TripPlanner-Trips` |
| **`GetTrips`** | Consultar viajes del usuario | `TripPlanner-GetTrips` | `GET /trips`, `GET /trips/{tripId}` | `TripPlanner-Trips` (+ Itin/Res) |
| **`UpdateTrip`** | Actualizar datos de un viaje | `TripPlanner-UpdateTrip` | `PUT /trips/{tripId}` | `TripPlanner-Trips` |
| **`CreateItinerary`** | Crear el itinerario de un viaje | `TripPlanner-CreateItinerary` | `POST /itineraries` | `TripPlanner-Itineraries` |
| **`UpdateItinerary`** | Modificar un itinerario | `TripPlanner-UpdateItinerary` | `PUT /itineraries/{itineraryId}` | `TripPlanner-Itineraries` |
| **`CreateReservation`** | Registrar reserva asociada a un viaje | `TripPlanner-CreateReservation` | `POST /reservations` | `TripPlanner-Reservations` |
| **`GetReservations`** | Consultar reservas | `TripPlanner-GetReservations` | `GET /reservations` | `TripPlanner-Reservations` |
| **`UpdateReservation`** | Actualizar una reserva o su estado | `TripPlanner-UpdateReservation` | `PUT /reservations/{reservationId}` | `TripPlanner-Reservations` |

---

## 🖥️ Los 6 Módulos del Frontend (`frontend/index.html`)

1. **📊 Dashboard:** Resumen del viajero, KPIs de presupuesto en COP, próximos viajes, reservas recientes y botón directo para el **Escenario Obligatorio de Demostración**.
2. **💬 Asistente Conversacional:** Chat con el `OrchestratorAgent` mediante HTTP Streaming directo (Canal 2), chips de consulta rápida y botón de rotación de sesión para validar persistencia y memoria.
3. **✈️ Consulta de Vuelos:** Tarjetas comparativas (Wingo, Avianca, LATAM) con horarios, duración, precios en COP y creación de reserva simulada en 1 clic.
4. **🌦️ Información Meteorológica:** Temperatura (°C), condición, humedad (%), probabilidad de lluvia (%), índice UV, recomendaciones de equipaje y pronóstico para los 4 días.
5. **🗺️ Mis Viajes e Itinerarios:** Viajes guardados en DynamoDB, creación/edición de viajes y agenda interactiva día por día con costos por actividad.
6. **🎫 Gestión de Reservas:** Listado filtrable por estado (*Simulada*, *Pendiente*, *Confirmada*), creación, cambio de estado y asociación a un viaje.

---

## 📁 Estructura del Repositorio

```text
WorkshopAgentes/
├── template.yaml               # Plantilla IaC AWS SAM unificada (DynamoDB + 8 Lambdas + API GW + S3)
├── frontend/
│   └── index.html              # SPA de 6 módulos lista para Amazon S3
├── chat.html                   # Espejo directo de la aplicación Frontend
├── backend/
│   ├── src/
│   │   ├── handlers.py         # Handlers de las 8 funciones AWS Lambda + capa DynamoDB
│   │   └── __init__.py
│   ├── local_api_server.py     # Emulador local de Amazon API Gateway (Canal 1 en puerto 8085)
│   └── requirements.txt
├── app/
│   ├── OrchestratorAgent/      # Agente Orquestador (HTTP Streaming + A2A Client + 8 Tools Lambda)
│   │   ├── main.py
│   │   ├── business_tools.py   # Implementación de las 8 @tool conectadas a Lambda/DynamoDB
│   │   └── policies/a2a-invoke-policy.json
│   ├── FlightsAgent/           # Agente Especialista de Vuelos (A2A Server + MCP Vuelos)
│   │   └── main.py
│   └── WeatherAgent/           # Agente Especialista de Clima (A2A Server + MCP Clima)
│       └── main.py
├── agentcore/
│   ├── agentcore.json          # Definición declarativa de Runtimes y TripPlannerMemory
│   └── aws-targets.json        # Cuenta y región AWS
├── docs/
│   └── 10-arquitectura-dos-canales-y-entregable-final.md  # Documentación técnica completa
├── start_all_local.ps1         # Script para iniciar todos los servicios localmente
└── deploy_aws.ps1              # Script de despliegue en AWS (SAM + S3 + AgentCore)
```

---

## 🚀 Ejecución Rápida Local y Escenario Obligatorio

### Opción A: Iniciar todo con el script automatizado
```powershell
.\start_all_local.ps1
```

### Opción B: Iniciar servicios en terminales individuales
```powershell
# Terminal 1: FlightsAgent (A2A + MCP Vuelos en puerto 9001)
$env:PORT='9001'; python app/FlightsAgent/main.py

# Terminal 2: WeatherAgent (A2A + MCP Clima en puerto 9002)
$env:PORT='9002'; python app/WeatherAgent/main.py

# Terminal 3: Canal 1 API Gateway Local (Puerto 8085)
$env:API_PORT='8085'; python backend/local_api_server.py

# Terminal 4: OrchestratorAgent (Canal 2 Streaming en puerto 8080)
$env:PORT='8080'; python app/OrchestratorAgent/main.py
```

Luego abre `frontend/index.html` (o `chat.html`) en tu navegador y ejecuta el **Escenario Obligatorio de Demostración**:
> *"Quiero organizar unas vacaciones de cuatro días en Cartagena. Salgo desde Bogotá, viajo con dos personas más y tengo un presupuesto de 5 millones de pesos. Quiero conocer el clima, encontrar vuelos y organizar algunas actividades turísticas."*

---

## ☁️ Despliegue en AWS

Consulta la guía detallada en [docs/10-arquitectura-dos-canales-y-entregable-final.md](docs/10-arquitectura-dos-canales-y-entregable-final.md) o ejecuta:
```powershell
.\deploy_aws.ps1
```
