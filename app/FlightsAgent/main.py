"""
Flights Agent — Agente servidor A2A conectado en tiempo real al servidor MCP de vuelos (https://ignav.com/mcp) vía Streamable HTTP.
Sin datos estáticos ni mocks: todas las consultas de aeropuertos y vuelos se ejecutan exclusivamente contra el servidor MCP.
"""
import os
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
    local_env = os.path.join(os.path.dirname(__file__), "..", "..", "agentcore", ".env.local")
    if os.path.exists(local_env):
        load_dotenv(local_env)
except ImportError:
    pass

from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.multiagent.a2a import A2AServer
from strands.tools.mcp import MCPClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FlightsAgent")


# ==============================================================================
# 1. CLIENTE MCP (Consumo Real sobre Streamable HTTP -> https://ignav.com/mcp)
# ==============================================================================
TRAVEL_MCP_URL = os.environ.get("TRAVEL_MCP_URL", "https://ignav.com/mcp").strip()
TRAVEL_MCP_API_KEY = (
    os.environ.get("TRAVEL_MCP_API_KEY")
    or os.environ.get("SMITHERY_API_KEY")
    or "ignav_fy74UtSIEoLc7G0Y-waC9mgIESf16QGJ"
).strip()


def initialize_mcp_client() -> MCPClient:
    """Inicializa la conexión de larga duración del MCPClient sobre Streamable HTTP hacia el servidor MCP real."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if TRAVEL_MCP_API_KEY:
        headers["Authorization"] = f"Bearer {TRAVEL_MCP_API_KEY}"
        headers["x-api-key"] = TRAVEL_MCP_API_KEY

    logger.info("Conectando MCPClient de vuelos a: %s (Streamable HTTP)", TRAVEL_MCP_URL)
    client = MCPClient(
        url=TRAVEL_MCP_URL,
        headers=headers,
        startup_timeout=25,
    )
    client.start()
    logger.info("Conexión MCP de vuelos iniciada con éxito en %s", TRAVEL_MCP_URL)
    return client


mcp_client = initialize_mcp_client()


@tool
def search_airports(query: str) -> str:
    """Busca en el servidor MCP el código de aeropuerto IATA (ej: 'BOG', 'CTG') para una ciudad dada.

    Args:
        query: Nombre de la ciudad o aeropuerto (ej: 'Bogotá', 'Cartagena', 'Medellín').
    """
    res = mcp_client.call_tool_sync("call_airports", "search_airports", {"query": query.strip()})
    sc = res.get("structuredContent", {})
    airports = sc.get("result", [])
    if not airports:
        return f"No se encontraron aeropuertos en el servidor MCP para la consulta '{query}'."
    out = []
    for a in airports:
        out.append(f"{a.get('city')}: código IATA '{a.get('code')}' ({a.get('name')})")
    return "\n".join(out)


@tool
def search_flights(origin: str, destination: str, departure_date: str) -> str:
    """Busca vuelos en tiempo real en el servidor MCP entre dos aeropuertos con códigos IATA para una fecha.
    Devuelve los vuelos reales con aerolínea, número de vuelo, horario de salida, horario de llegada, duración y precio.

    Args:
        origin: Código IATA de origen (ej: 'BOG').
        destination: Código IATA de destino (ej: 'CTG').
        departure_date: Fecha de salida en formato YYYY-MM-DD (ej: '2026-11-20').
    """
    orig = origin.strip().upper()
    dest = destination.strip().upper()
    dep_date = departure_date.strip()

    airline_urls = {
        "wingo": "https://www.wingo.com",
        "latam": "https://www.latamairlines.com",
        "avianca": "https://www.avianca.com",
        "jetsmart": "https://jetsmart.com",
        "copa": "https://www.copaair.com",
    }

    res = mcp_client.call_tool_sync(
        "call_flights",
        "search_flights",
        {"origin": orig, "destination": dest, "departure_date": dep_date},
    )
    sc = res.get("structuredContent", {})
    itins = sc.get("itineraries", [])
    if not itins:
        return f"El servidor MCP no reportó itinerarios disponibles para la ruta {orig} -> {dest} en la fecha {dep_date}."

    lines = [f"Vuelos en tiempo real obtenidos del servidor MCP ({TRAVEL_MCP_URL}) para {orig} -> {dest} el {dep_date}:"]
    for i, it in enumerate(itins[:6]):
        price_obj = it.get("price", {})
        amount = price_obj.get("amount")
        currency = price_obj.get("currency", "USD")
        cop_est = int(amount * 4000) if currency == "USD" and amount else amount

        outbound = it.get("outbound", {})
        carrier = outbound.get("carrier", "Aerolínea")
        segments = outbound.get("segments", [])
        fl_num = "N/A"
        dep_time = "N/A"
        arr_time = "N/A"
        dur_str = "N/A"
        stops_label = "Directo"
        if segments:
            first_seg = segments[0]
            last_seg = segments[-1]
            carrier = first_seg.get("operating_carrier_name") or carrier
            fl_nums = [
                f"{s.get('marketing_carrier_code', '')} {s.get('flight_number', '')}".strip()
                for s in segments
            ]
            fl_num = " / ".join([fn for fn in fl_nums if fn]) or "N/A"
            dep_raw = first_seg.get("departure_time_local", "")
            arr_raw = last_seg.get("arrival_time_local", "")
            dep_date_part = dep_raw.split("T")[0] if "T" in dep_raw else ""
            arr_date_part = arr_raw.split("T")[0] if "T" in arr_raw else ""
            dep_time = dep_raw.split("T")[1][:5] if "T" in dep_raw else dep_raw
            arr_time = arr_raw.split("T")[1][:5] if "T" in arr_raw else arr_raw
            if dep_date_part and arr_date_part and arr_date_part > dep_date_part:
                arr_time = f"{arr_time} (+1d)"

            total_dur = outbound.get("duration_minutes")
            if not isinstance(total_dur, int):
                total_dur = sum(int(s.get("duration_minutes") or 0) for s in segments)
            if isinstance(total_dur, int) and total_dur > 0:
                dur_str = f"{total_dur // 60}h {total_dur % 60}m" if total_dur >= 60 else f"{total_dur}m"

            if len(segments) > 1:
                via_airports = [s.get("arrival_airport", "") for s in segments[:-1] if s.get("arrival_airport")]
                n_stops = len(segments) - 1
                stops_word = "escala" if n_stops == 1 else "escalas"
                stops_label = f"{n_stops} {stops_word} (vía {', '.join(via_airports)})"

        url = "https://www.google.com/travel/flights"
        for k, v in airline_urls.items():
            if k in carrier.lower():
                url = v
                break

        cop_text = f"${cop_est:,.0f} COP".replace(",", ".") if cop_est else f"{amount} {currency}"
        lines.append(
            f"{i+1}. **{carrier}** (Vuelos: {fl_num} · {stops_label})\n"
            f"   - Horario: Salida {dep_time} -> Llegada {arr_time} (Duración total: {dur_str})\n"
            f"   - Tarifa: {cop_text} ({amount} {currency})\n"
            f"   - Sitio web oficial: [{carrier}]({url})"
        )
    return "\n\n".join(lines)


# ==============================================================================
# 2. AGENTE STRANDS (A2A Server)
# ==============================================================================
def get_model():
    model_name = os.environ.get("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return BedrockModel(
        model_id=model_name,
        region_name=region,
        temperature=0.3,
        max_tokens=4096,
    )


def create_agent(context_id: str) -> Agent:
    return Agent(
        name="Flights Agent",
        description="Busca vuelos en tiempo real utilizando el servidor MCP de viajes (https://ignav.com/mcp).",
        system_prompt=(
            "Eres un agente especialista en búsqueda y cotización de vuelos conectado en vivo al servidor MCP de vuelos.\n"
            "Instrucciones clave:\n"
            "1. Si recibes nombres de ciudad en vez del código IATA (ej: 'Bogotá' o 'Cartagena'), "
            "invoca 'search_airports' para obtener sus códigos IATA desde el MCP.\n"
            "2. Invoca 'search_flights' con los códigos IATA y la fecha (YYYY-MM-DD).\n"
            "3. Presenta exclusivamente los vuelos reales devueltos por el MCP, detallando aerolínea, número de vuelo, horario exacto de salida y llegada, duración y tarifa en Pesos Colombianos (COP)."
        ),
        model=get_model(),
        tools=[search_airports, search_flights],
        callback_handler=None,
    )


port = int(os.environ.get("PORT", 9000))
public_url = os.environ.get("PUBLIC_URL") or f"http://127.0.0.1:{port}"

a2a_server = A2AServer(
    agent_factory=create_agent,
    host="0.0.0.0",
    port=port,
    http_url=public_url,
    enable_a2a_compliant_streaming=True,
)

if __name__ == "__main__":
    a2a_server.serve()
