# Guion de Video — Presentación Trip Planner A2A con MCP Remoto

Guion estructurado paso a paso para la grabación del video explicativo del proyecto. Diseñado para demostrar el dominio conceptual de la arquitectura multi-agente, el protocolo A2A, la integración con servidores **MCP remotos (Model Context Protocol)** y el despliegue en la nube de **AWS Bedrock AgentCore**.

---

## 1. Ficha técnica del video

- **Duración estimada:** 5 a 7 minutos.
- **Audiencia:** Profesor evaluador y compañeros de curso.
- **Tono:** Técnico, fluido, seguro y orientado a arquitectura de software en la nube.
- **Requisitos previos en pantalla:**
  - Visual Studio Code con el proyecto y código abierto.
  - Pestañas listas en VS Code: `README.md`, `app/FlightsAgent/main.py` y `app/OrchestratorAgent/main.py`.
  - Una terminal de PowerShell maximizada con fuente clara y legible (14pt a 16pt).

---

## 2. Estructura general de la presentación

| Minuto | Bloque | Tema principal | Qué mostrar en pantalla |
|---|---|---|---|
| **0:00 - 1:15** | 1. Introducción | Propósito del sistema y patrón arquitectónico | `README.md` o estructura en VS Code |
| **1:15 - 2:15** | 2. Arquitectura | Desacoplamiento y protocolo A2A | `docs/01-diagrama-contexto.md` |
| **2:15 - 3:30** | 3. MCP Remoto | Cliente MCP y descubrimiento dinámico de herramientas | `app/FlightsAgent/main.py` (líneas 110-175 y 198) |
| **3:30 - 4:30** | 4. Retos en AWS | SigV4, IAM cross-runtime y AgentCore Memory | `app/OrchestratorAgent/main.py` |
| **4:30 - 6:00** | 5. Demo en vivo | Invocación en tiempo real en Bedrock AgentCore | Terminal PowerShell con `agentcore status` e `invoke` |
| **6:00 - 6:45** | 6. Conclusiones | Síntesis de aprendizajes y cierre | Directorio `docs/` en VS Code |

---

## 3. Guion detallado minuto a minuto

### Minuto 0:00 - 1:15 | Bloque 1: Introducción y Propósito

**Qué tener en pantalla:**
El archivo `README.md` o la estructura general del proyecto en VS Code.

**Qué decir:**
> *"Buenas tardes, profesor. En este video voy a presentar la arquitectura, implementación y funcionamiento de nuestro sistema **Trip Planner Multi-Agente**, desarrollado sobre la infraestructura nativa de **AWS Bedrock AgentCore**, utilizando el framework **Strands Agents**, el protocolo estándar entre agentes **A2A (Agent-to-Agent)** y el protocolo estándar de herramientas **MCP (Model Context Protocol)**.*
>
> *El problema que resolvemos es la atención a consultas de viaje complejas expresadas en lenguaje natural —itinerarios, aerolíneas, tarifas y clima de destino— aplicando el principio de separación de responsabilidades mediante el patrón de **Orquestador y Especialistas**, donde cada agente opera como un microservicio autónomo e independiente en la nube."*

---

### Minuto 1:15 - 2:15 | Bloque 2: Arquitectura y Protocolo A2A

**Qué tener en pantalla:**
El diagrama de arquitectura de `docs/01-diagrama-contexto.md` o `docs/02-diagrama-secuencia.md`.

**Qué decir:**
> *"El sistema está compuesto por tres agentes independientes:*
>
> 1. *El **OrchestratorAgent**: Actúa como **cliente A2A**. Es el punto de entrada del usuario; analiza la solicitud con el modelo fundacional Amazon Nova Lite, decide a qué especialistas consultar y consolida la respuesta final.*
> 2. *El **FlightsAgent**: Es un **servidor A2A** especialista en consulta de vuelos, aerolíneas, horarios y tarifas.*
> 3. *El **WeatherAgent**: Es un **servidor A2A** especialista en pronósticos meteorológicos.*
>
> *El pilar de esta arquitectura es el **desacoplamiento total**: el orquestador nunca importa el código fuente ni las dependencias de los especialistas. Se comunica con ellos estrictamente a través de la red utilizando el protocolo estándar **A2A** con mensajes estructurados en **JSON-RPC 2.0** y eventos de streaming."*

---

### Minuto 2:15 - 3:30 | Bloque 3: Integración del Servidor MCP Remoto en FlightsAgent

**Qué tener en pantalla:**
Abre `app/FlightsAgent/main.py` y enfócate en las líneas 110 a 175.

**Qué decir:**
> *"Uno de los puntos clave del proyecto es la integración de **Model Context Protocol (MCP)** en el `FlightsAgent`:*
>
> *Entre las **líneas 113 y 118**, configuramos la conexión hacia nuestro servidor MCP remoto (`https://ignav.com/mcp`) autenticado con su respectiva API key en las cabeceras HTTP.*
>
> *En la función `initialize_mcp_client()` —entre las **líneas 130 y 172**— instanciamos el cliente oficial `MCPClient` sobre transporte Streamable HTTP / SSE. En la **línea 158** iniciamos la sesión con `client.start()`, y en la **línea 160** ejecutamos `client.list_tools_sync()`.*
>
> *Esto permite el **descubrimiento dinámico de herramientas**: el agente no tiene las tools cableadas en código estático, sino que las consulta en vivo desde el servidor MCP remoto, cargando dinámicamente `search_airports` y `search_flights`.*
>
> *Finalmente, en la **línea 198**, inyectamos estas herramientas (`tools=flight_tools`) directamente en la instancia del agente de Strands, y en el `system_prompt` guiamos al LLM para resolver códigos IATA y consultar itinerarios reales con enlaces de reserva."*

---

### Minuto 3:30 - 4:30 | Bloque 4: Retos de Ingeniería y Seguridad en AWS

**Qué tener en pantalla:**
Abre `app/OrchestratorAgent/main.py` mostrando la clase `HttpxSigV4Auth` y la función `_create_a2a_client`.

**Qué decir:**
> *"Durante la construcción y despliegue en AWS Bedrock AgentCore resolvimos desafíos arquitectónicos críticos:*
>
> 1. ***Firma Criptográfica SigV4 en A2A:** Los endpoints de AgentCore exigen autenticación **AWS Signature Version 4**. Implementamos un transportador HTTP personalizado (`HttpxSigV4Auth`) que calcula en tiempo real el hash SHA-256 de cada invocación A2A hacia `bedrock-agentcore`.*
> 2. ***Políticas IAM Cross-Runtime:** Definimos permisos en IAM (`a2a-invoke-policy.json`) que autorizan al orquestador a invocar los runtimes de FlightsAgent y WeatherAgent con `bedrock-agentcore:InvokeAgentRuntime`.*
> 3. ***Memoria Persistente con AgentCore Memory:** Integramos `TripPlannerMemory` con estrategias de preferencias de usuario y resúmenes de sesión para mantener el contexto entre múltiples conversaciones."*

---

### Minuto 4:30 - 6:00 | Bloque 5: Demostración en Vivo en AWS Bedrock AgentCore

**Qué tener en pantalla:**
Terminal de PowerShell maximizada con letra clara.

#### Paso 1: Mostrar el estado de los recursos en la nube
Ejecuta:
```powershell
agentcore status
```

**Qué decir:**
> *"Aquí ejecutamos `agentcore status`. Podemos confirmar que en nuestra cuenta de AWS en la región `us-east-1` están desplegados y en estado **READY** los tres runtimes (`FlightsAgent`, `WeatherAgent` y `OrchestratorAgent`), además del recurso de memoria persistente `TripPlannerMemory`."*

#### Paso 2: Ejecutar la invocación en vivo
Ejecuta:
```powershell
agentcore invoke --runtime OrchestratorAgent "Quiero viajar de Bogotá a Cartagena el 25 de octubre de 2026. ¿Qué vuelos y clima hay?"
```

**Qué decir mientras procesa y al ver la respuesta:**
> *"En este momento la consulta se procesa en la infraestructura real de AWS Bedrock:*
> 1. *El `OrchestratorAgent` recibe la petición en la nube.*
> 2. *Invoca por A2A con SigV4 al `FlightsAgent` y al `WeatherAgent`.*
> 3. *El `FlightsAgent` consulta en vivo el servidor MCP remoto para recuperar vuelos reales (aerolíneas como Wingo y JetSMART, tarifas y enlaces directos de reserva).*
> 4. *El `WeatherAgent` devuelve el pronóstico meteorológico para Cartagena.*
> 5. *El orquestador consolida los datos y le entrega al usuario un plan de viaje claro, estructurado y sin ruido de razonamiento interno.*
>
> *Como vemos en pantalla, la respuesta consolida perfectamente los vuelos en tiempo real provenientes del MCP remoto y el clima para la fecha seleccionada."*

---

### Minuto 6:00 - 6:45 | Bloque 6: Conclusiones y Cierre

**Qué tener en pantalla:**
El explorador de archivos mostrando la carpeta `docs/` en VS Code.

**Qué decir:**
> *"Para concluir, este proyecto demuestra una implementación completa y robusta de la nube moderna para Inteligencia Artificial Agentica:*
> - *El protocolo **A2A** para la orquestación distribuida de microservicios.*
> - *El protocolo **MCP** para la integración modular de herramientas remotas.*
> - *La infraestructura segura y elástica de **AWS Bedrock AgentCore** con roles IAM y memoria persistente.*
>
> *Toda la arquitectura, código y documentación se encuentran disponibles en el repositorio. Muchas gracias."*
