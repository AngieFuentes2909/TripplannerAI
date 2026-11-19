"""
Orchestrator Agent — Agente cliente A2A (Trip Planner AI)
Recibe la petición del usuario vía HTTP Streaming, coordina a los agentes
especialistas (FlightsAgent y WeatherAgent) mediante el protocolo A2A,
gestiona la memoria conversacional en Amazon Bedrock AgentCore Memory y
ejecuta las 8 Tools de negocio respaldadas por AWS Lambda + Amazon DynamoDB.
"""
import os
import sys
import asyncio
import httpx
from typing import Optional
from a2a.types import AgentCard
from a2a.client import ClientConfig
from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.agent.conversation_manager import NullConversationManager
from strands.agent.a2a_agent import A2AAgent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig

from business_tools import (
    ALL_BUSINESS_TOOLS,
    set_current_actor_id,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from starlette.middleware.cors import CORSMiddleware

app = BedrockAgentCoreApp()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FLIGHTS_URL = os.environ.get("FLIGHTS_AGENT_URL", "http://localhost:9001")
WEATHER_URL = os.environ.get("WEATHER_AGENT_URL", "http://localhost:9002")

# Configuración de Amazon Bedrock Nova Lite y AgentCore Memory
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TRIP_MEMORY_ID = os.environ.get("TRIP_MEMORY_ID") or os.environ.get("MEMORY_TRIPPLANNERMEMORY_ID", "")


def load_model() -> BedrockModel:
    """Instancia y retorna el modelo Amazon Bedrock Nova Lite."""
    return BedrockModel(
        model_id=BEDROCK_MODEL_ID,
        region_name=AWS_REGION,
        temperature=0.3,
        max_tokens=4096,
    )


def _build_session_manager(session_id: str, actor_id: str) -> Optional[AgentCoreMemorySessionManager]:
    """Construye el session manager de AgentCore Memory si TRIP_MEMORY_ID está configurado."""
    if not TRIP_MEMORY_ID:
        return None
    try:
        config = AgentCoreMemoryConfig(
            memory_id=TRIP_MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
        )
        return AgentCoreMemorySessionManager(
            agentcore_memory_config=config,
            region_name=AWS_REGION,
        )
    except Exception as e:
        print(f"Advertencia: no se pudo inicializar AgentCoreMemorySessionManager: {e}")
        return None


class HttpxSigV4Auth(httpx.Auth):
    """Firma solicitudes salientes hacia AWS Bedrock AgentCore Runtime con AWS SigV4."""
    def __init__(self, service="bedrock-agentcore", region="us-east-1"):
        import botocore.session
        from botocore.auth import SigV4Auth as BotoSigV4Auth
        self.service = service
        self.region = region
        self.session = botocore.session.get_session()
        self.credentials = self.session.get_credentials()
        self.signer = BotoSigV4Auth(self.credentials, self.service, self.region)

    def auth_flow(self, request: httpx.Request):
        from botocore.awsrequest import AWSRequest
        aws_request = AWSRequest(
            method=request.method,
            url=str(request.url),
            headers=dict(request.headers),
            data=request.content,
        )
        self.signer.add_auth(aws_request)
        for k, v in aws_request.headers.items():
            request.headers[k] = v
        yield request


def _create_a2a_client(endpoint: str, name: str, description: str) -> A2AAgent:
    """Crea un cliente A2AAgent configurado para entorno local o nube (AWS Bedrock AgentCore)."""
    if "localhost" in endpoint or "127.0.0.1" in endpoint:
        remote = A2AAgent(endpoint=endpoint, timeout=60)
        remote._agent_card = AgentCard(
            name=name,
            description=description,
            url=endpoint,
            version="1.0.0",
            protocol_version="0.3.0",
            capabilities={"streaming": True},
            skills=[],
            default_input_modes=["text"],
            default_output_modes=["text"],
        )
        return remote

    httpx_client = httpx.AsyncClient(auth=HttpxSigV4Auth(), timeout=120.0)
    client_config = ClientConfig(httpx_client=httpx_client)
    remote = A2AAgent(endpoint=endpoint, client_config=client_config)
    remote._agent_card = AgentCard(
        name=name,
        description=description,
        url=endpoint,
        version="1.0.0",
        protocol_version="0.2.0",
        capabilities={},
        skills=[],
        default_input_modes=["text"],
        default_output_modes=["text"],
    )
    return remote


def _extract_clean_text(result) -> str:
    """Extrae texto limpio del resultado del agente A2A remoto."""
    if hasattr(result, "message") and isinstance(result.message, dict):
        content = result.message.get("content", [])
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and "text" in c]
        if texts:
            return "".join(texts).strip()
    return str(result).strip()


def _get_flights_url() -> str:
    """Detecta si FlightsAgent está corriendo en local (9001 o 9000) o usa el endpoint cloud."""
    for local_port in (9001, 9000):
        try:
            with httpx.Client(timeout=0.6) as client:
                resp = client.get(f"http://localhost:{local_port}/.well-known/agent-card.json")
                if resp.status_code == 200:
                    return f"http://localhost:{local_port}"
        except Exception:
            pass
    return os.environ.get("FLIGHTS_AGENT_URL", "http://localhost:9001")


def _get_weather_url() -> str:
    """Detecta si WeatherAgent está corriendo en local (9002) o usa el endpoint cloud."""
    try:
        with httpx.Client(timeout=0.6) as client:
            resp = client.get("http://localhost:9002/.well-known/agent-card.json")
            if resp.status_code == 200:
                return "http://localhost:9002"
    except Exception:
        pass
    return os.environ.get("WEATHER_AGENT_URL", "http://localhost:9002")


@tool
def ask_flights(request: str) -> str:
    """Delega en el Flights Agent (vía A2A + MCP de vuelos) la búsqueda de vuelos.
    Úsalo cuando el usuario pregunte por vuelos, tiquetes o itinerarios aéreos.
    """
    import time
    endpoint = _get_flights_url()
    enhanced_request = (
        f"{request}\n"
        "(Por favor presenta las mejores 3 a 4 opciones detallando aerolínea, número de vuelo, horarios exactos de salida y llegada, duración y precio en COP)."
    )
    for attempt in range(3):
        try:
            remote = _create_a2a_client(endpoint, "Flights Agent", "Busca vuelos entre ciudades para una fecha dada.")
            result = remote(enhanced_request)
            return _extract_clean_text(result)
        except Exception as e:
            print(f"[Orchestrator] Error al consultar FlightsAgent en {endpoint}: {e}")
            if attempt < 2 and ("503" in str(e) or "UNAVAILABLE" in str(e) or "demand" in str(e).lower()):
                time.sleep(1.5 * (attempt + 1))
                continue
            return f"Aviso: El servicio de vuelos no está disponible en este momento ({e}). No inventes vuelos; informa que el servicio de vuelos no respondió."


@tool
def ask_weather(request: str) -> str:
    """Delega en el Weather Agent (vía A2A + MCP de clima) la consulta del pronóstico meteorológico.
    Úsalo cuando el usuario pregunte por el tiempo, temperatura, lluvia o condiciones climáticas.
    """
    import time
    endpoint = _get_weather_url()
    for attempt in range(3):
        try:
            remote = _create_a2a_client(endpoint, "Weather Agent", "Consulta el pronóstico del clima por ciudad y fecha vía MCP.")
            result = remote(request)
            return _extract_clean_text(result)
        except Exception as e:
            if attempt < 2 and ("503" in str(e) or "UNAVAILABLE" in str(e) or "demand" in str(e).lower()):
                time.sleep(1.5 * (attempt + 1))
                continue
            return f"Aviso: El servicio de clima no está disponible en este momento ({e}). No inventes clima; informa que el servicio de clima no respondió."


@tool
def recall_summary(actor_id: str, session_id: str) -> str:
    """Recupera el resumen consolidado de una sesión previa desde AgentCore Memory (/summaries/{actorId}/{sessionId}/).
    Úsalo cuando el usuario haga referencia a itinerarios o conversaciones previas.
    """
    if not TRIP_MEMORY_ID:
        return "No hay ID de memoria configurado para recuperar resúmenes."
    try:
        import boto3
        client = boto3.client("bedrock-agentcore", region_name=AWS_REGION)
        namespace = f"/summaries/{actor_id}/{session_id}/"
        response = client.retrieve_memory_records(
            memoryId=TRIP_MEMORY_ID,
            namespace=namespace,
            maxResults=5,
        )
        records = response.get("records", [])
        if not records:
            return f"No se encontraron resúmenes archivados para la sesión {session_id}."
        text_snippets = []
        for rec in records:
            content = rec.get("content", {})
            if isinstance(content, dict) and "text" in content:
                text_snippets.append(content["text"])
            elif isinstance(content, str):
                text_snippets.append(content)
        return "\n".join(text_snippets) if text_snippets else "Se encontró registro de sesión sin texto detallado."
    except Exception as e:
        return f"Aviso: no fue posible consultar el resumen de sesión en memoria ({e})."


SYSTEM_PROMPT = (
    "Eres TripPlanner AI, un asistente y planificador de viajes inteligente sobre una arquitectura multiagente en AWS.\n"
    "Cuentas con:\n"
    "- Memoria persistente de Amazon Bedrock AgentCore para recordar preferencias del viajero y contexto conversacional.\n"
    "- Dos agentes especialistas vía protocolo A2A respaldados por servidores MCP en vivo: `ask_flights` (Flight Agent) y `ask_weather` (Weather Agent).\n"
    "- Ocho Tools de negocio obligatorias respaldadas por AWS Lambda y Amazon DynamoDB:\n"
    "  `CreateTrip`, `GetTrips`, `UpdateTrip`, `CreateItinerary`, `UpdateItinerary`, `CreateReservation`, `GetReservations`, `UpdateReservation`.\n"
    "- La Tool `CompareBudget` (Comparador de Presupuestos en AWS Lambda `TripPlanner-CompareBudget`) que compara el presupuesto asignado al viaje frente a los costos de vuelos, hoteles, actividades del itinerario y reservas en DynamoDB.\n\n"
    "REGLAS DE ACTUACIÓN:\n"
    "1. CONSULTA DE VUELOS Y CLIMA: Cuando el usuario pida organizar unas vacaciones o consultar vuelos/clima:\n"
    "   - Invoca `ask_flights` para obtener los vuelos disponibles en tiempo real desde el servidor MCP.\n"
    "   - Invoca `ask_weather` para consultar el pronóstico meteorológico en tiempo real del destino.\n"
    "   - Presenta siempre las tarifas en Pesos Colombianos (COP) con formato legible (ej: $350.000 COP) e incluye aerolínea, número de vuelo, horario exacto de salida y llegada, escalas y duración.\n"
    "2. GESTIÓN DE VIAJES, ITINERARIOS Y RESERVAS EN DYNAMODB:\n"
    "   - Si el usuario solicita crear/guardar/registrar el viaje, organizar actividades/itinerario o registrar una reserva:\n"
    "     a) Usa `CreateTrip` indicando ciudad de origen, destino, fechas (`startDate`, `endDate`), número total de viajeros (`travelers` — si dice 'viajo con dos personas más' son 3 viajeros en total) y presupuesto en COP (`budgetCop`).\n"
    "     b) Usa `CreateItinerary` asociando el `tripId` creado y enviando en `daysJson` un arreglo JSON con cada día del viaje, horarios, actividades turísticas recomendadas y costos estimados en COP.\n"
    "     c) Usa `CreateReservation` vinculándola al `tripId` con estado 'Simulada', 'Pendiente' o 'Confirmada'. NUNCA pidas ni almacenes números de tarjetas bancarias, CVV ni pagos reales.\n"
    "   - Cuando el usuario pida consultar o modificar viajes, itinerarios o reservas, invoca `GetTrips`, `UpdateTrip`, `UpdateItinerary`, `GetReservations` o `UpdateReservation`.\n"
    "3. COMPARADOR DE PRESUPUESTOS (AGENT-DRIVEN UI):\n"
    "   - Cuando el usuario pida comparar, analizar o verificar el presupuesto de un viaje (o inmediatamente después de crear un viaje con su itinerario y reserva), invoca la herramienta `CompareBudget`.\n"
    "   - Al presentar el resultado de `CompareBudget`, incluye tu análisis financiero en texto Y ADEMÁS incluye el bloque JSON estructurado exacto devuelto por `CompareBudget` dentro de un bloque de código con la etiqueta `budget-json` (ejemplo: ```budget-json\\n{...el objeto comparison...}\\n```) para que el Frontend lo renderice como un componente visual interactivo (Agent-Driven UI).\n"
    "4. PREFERENCIAS Y MEMORIA: Si detectas preferencias del usuario en memoria (ej. aerolínea favorita, horarios), menciónalas expresamente.\n"
    "5. FORMATO DE RESPUESTA: Organiza tu respuesta con encabezados claros en Markdown. No incluyas etiquetas `<thinking>`.\n"
    "Responde siempre en español (o en el idioma del usuario)."
)


def build_agent(session_id: str = "default_session", actor_id: str = "default_user") -> Agent:
    session_manager = _build_session_manager(session_id=session_id, actor_id=actor_id)
    conversation_manager = None if session_manager else NullConversationManager()

    return Agent(
        name="Trip Planner Orchestrator",
        system_prompt=SYSTEM_PROMPT,
        model=load_model(),
        tools=[ask_flights, ask_weather, recall_summary, *ALL_BUSINESS_TOOLS],
        session_manager=session_manager,
        conversation_manager=conversation_manager,
        callback_handler=None,
    )


class ThinkingStreamFilter:
    """Filtra y remueve los bloques <thinking>...</thinking> del stream de salida."""
    def __init__(self):
        self.inside_thinking = False
        self.buffer = ""

    def process(self, chunk: str) -> str:
        self.buffer += chunk
        out = ""
        while self.buffer:
            if not self.inside_thinking:
                idx = self.buffer.find("<thinking")
                if idx != -1:
                    out += self.buffer[:idx]
                    gt = self.buffer.find(">", idx)
                    if gt != -1:
                        self.inside_thinking = True
                        self.buffer = self.buffer[gt + 1:]
                    else:
                        self.buffer = self.buffer[idx:]
                        break
                else:
                    last_lt = self.buffer.rfind("<")
                    if last_lt != -1 and "<thinking".startswith(self.buffer[last_lt:]):
                        out += self.buffer[:last_lt]
                        self.buffer = self.buffer[last_lt:]
                        break
                    out += self.buffer
                    self.buffer = ""
            else:
                end_idx = self.buffer.find("</thinking>")
                if end_idx != -1:
                    self.inside_thinking = False
                    self.buffer = self.buffer[end_idx + len("</thinking>"):].lstrip("\r\n ")
                else:
                    last_lt = self.buffer.rfind("<")
                    if last_lt != -1 and "</thinking>".startswith(self.buffer[last_lt:]):
                        self.buffer = self.buffer[last_lt:]
                        break
                    self.buffer = ""
        return out

    def flush(self) -> str:
        if not self.inside_thinking:
            res = self.buffer
            self.buffer = ""
            return res
        return ""


@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("El campo 'prompt' debe ser un string")

    session_id = (
        payload.get("session_id")
        or (getattr(context, "session_id", None) if context else None)
        or "default_session"
    )
    actor_id = (
        payload.get("actor_id")
        or (getattr(context, "actor_id", None) if context else None)
        or (getattr(context, "client_id", None) if context else None)
        or "default_user"
    )
    set_current_actor_id(actor_id)

    max_retries = 3
    for attempt in range(max_retries):
        try:
            agent = build_agent(session_id=session_id, actor_id=actor_id)
            emitted = False
            thinking_filter = ThinkingStreamFilter()
            async for event in agent.stream_async(prompt):
                if isinstance(event, dict) and "data" in event and isinstance(event["data"], str):
                    filtered = thinking_filter.process(event["data"])
                    if filtered:
                        emitted = True
                        yield filtered
            remaining = thinking_filter.flush()
            if remaining:
                emitted = True
                yield remaining
            if emitted:
                break
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str or "demand" in err_str.lower()) and attempt < max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            yield f"\n\n*(Aviso del servicio de IA: {err_str}. Por favor reintenta en un momento.)*"
            break


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(port=port, host="0.0.0.0")
