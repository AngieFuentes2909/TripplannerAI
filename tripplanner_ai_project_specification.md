# TRIPPLANNER AI · Trabajo Final · Programación Agéntica
**Your AI Travel Companion: Del Playground a una plataforma inteligente para planificar y gestionar viajes**

* **Asignatura:** Programación Agéntica
* **Plazo:** 15 días calendario
* **Programa:** Ingeniería de Sistemas
* **Tecnologías clave:** Strands Agents, Amazon Bedrock AgentCore, MCP (Model Context Protocol), AWS Lambda, Amazon API Gateway, Amazon DynamoDB, Amazon S3, AWS SAM, React/Frontend a elección.

---

## 1. El Desafío
Convertir **TripPlanner** (una solución multiagente construida con Strands Agents y desplegada en Amazon Bedrock AgentCore con mecanismos de memoria) en una aplicación web completa y real sobre una arquitectura distribuida en AWS. 

El usuario debe poder ingresar a una plataforma frontend, interactuar mediante chat con streaming, consultar vuelos y clima, planificar vacaciones, crear itinerarios, registrar reservas simuladas/persistentes y recuperar viajes anteriores.

### Los tres agentes existentes (Requisito no negociable)
1. **Orchestrator Agent:** Interactúa con el usuario mediante HTTP streaming y coordina a los agentes especialistas.
2. **Flight Agent:** Especialista en consultas de vuelos mediante MCP de vuelos.
3. **Weather Agent:** Especialista en consultas meteorológicas mediante MCP de clima.

> *Nota:* Se prohíbe reemplazar la arquitectura multiagente por una simulación monolítica.

---

## 2. Objetivos Específicos
* **OE1:** Diseñar una experiencia de usuario intuitiva.
* **OE2:** Integrar frontend y AgentCore mediante HTTP streaming directo.
* **OE3:** Conservar la arquitectura multiagente.
* **OE4:** Agregar nuevas Tools respaldadas por Lambdas.
* **OE5:** Implementar la lógica de negocio con AWS Lambda.
* **OE6:** Publicar APIs mediante Amazon API Gateway (Canal 1).
* **OE7:** Persistir información en Amazon DynamoDB.
* **OE8:** Aprovechar las memorias de los agentes para contexto conversacional.
* **OE9:** Aplicar buenas prácticas de arquitectura distribuida e IAM de mínimo privilegio.

---

## 3. Experiencia de Usuario (Frontend & Agent-Driven UI)
El frontend debe contener como mínimo 6 módulos:
1. **Dashboard:** Resumen de usuario, próximos viajes, accesos rápidos.
2. **Asistente conversacional:** Chat con el Orchestrator mediante HTTP streaming.
3. **Consulta de vuelos:** Tarjetas comparativas (aerolínea, horarios, precio).
4. **Información meteorológica:** Temperatura, condiciones y probabilidad de lluvia.
5. **Mis viajes e itinerarios:** Viajes guardados, agenda por día.
6. **Gestión de reservas:** Listado con estados (*Simulada*, *Pendiente*, *Confirmada*), creación, edición y asociación a un viaje.

---

## 4. Funcionalidades Obligatorias y Tools
Cada Tool mínima debe estar respaldada por una operación de negocio en **AWS Lambda** conectada a **Amazon DynamoDB**:

| Tool | Propósito | Respaldo |
| :--- | :--- | :--- |
| `CreateTrip` | Crear un viaje del usuario | Lambda $\rightarrow$ DynamoDB |
| `GetTrips` | Consultar viajes del usuario | Lambda $\rightarrow$ DynamoDB |
| `UpdateTrip` | Actualizar datos de un viaje | Lambda $\rightarrow$ DynamoDB |
| `CreateItinerary` | Crear el itinerario de un viaje | Lambda $\rightarrow$ DynamoDB |
| `UpdateItinerary` | Modificar un itinerario | Lambda $\rightarrow$ DynamoDB |
| `CreateReservation` | Registrar reserva asociada a un viaje | Lambda $\rightarrow$ DynamoDB |
| `GetReservations` | Consultar reservas | Lambda $\rightarrow$ DynamoDB |
| `UpdateReservation` | Actualizar una reserva o su estado | Lambda $\rightarrow$ DynamoDB |

---

## 5. Arquitectura General (Dos Canales Independientes)
* **Canal 1 (Operaciones de Negocio):** Frontend $\rightarrow$ Amazon API Gateway $\rightarrow$ AWS Lambda $\rightarrow$ Amazon DynamoDB (Listados, formularios, CRUD de viajes/reservas).
* **Canal 2 (Interacción Agéntica):** Frontend $\rightarrow$ HTTP Streaming directo $\rightarrow$ Amazon Bedrock AgentCore (Orchestrator $\rightarrow$ Flight/Weather MCPs y Tools de negocio vía Lambdas).
* **Hosting Frontend:** Amazon S3 (+ Amazon CloudFront opcional).
* **Infraestructura como Código (IaC):** AWS SAM recomendado (`template.yaml` unificado).

---

## 6. Escenario Obligatorio de Demostración
> *"Quiero organizar unas vacaciones de cuatro días en Cartagena. Salgo desde Bogotá, viajo con dos personas más y tengo un presupuesto de 5 millones de pesos. Quiero conocer el clima, encontrar vuelos y organizar algunas actividades turísticas."*

El flujo completo comprende:
1. Ingreso al frontend e interacción con el asistente (streaming).
2. Orchestrator interpreta y delega en Flight y Weather (vía MCP).
3. Presentación de tarjetas de vuelos y clima.
4. Solicitud de creación de viaje, generación de itinerario y registro de reserva.
5. Persistencia exitosa en DynamoDB y recuperación de datos en sesiones futuras.

---

## 7. Entregables
1. **Frontend:** Publicado en S3.
2. **Backend Serverless:** Lambdas y API Gateway funcionales.
3. **DynamoDB:** Tablas y persistencia operativa.
4. **Diagrama de Arquitectura:** Con los dos canales separados.
5. **Repositorio Git:** Código limpio con historial de commits y plantilla AWS SAM.
6. **Documentación Técnica:** Arquitectura, modelo de datos, APIs, Lambdas, Tools y guía de despliegue.
7. **Demostración en vivo:** Ejecución real del escenario obligatorio.