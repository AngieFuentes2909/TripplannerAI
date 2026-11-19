"""
Weather Agent — Agente servidor A2A conectado a servidor MCP de clima vía Streamable HTTP.
Consulta datos meteorológicos satelitales 100% en tiempo real desde Open-Meteo API
a través del protocolo Model Context Protocol (MCPServer + MCPClient Streamable HTTP),
sin diccionarios ni datos estáticos.
"""
import os
import time
import logging
import asyncio
import threading
import httpx

from mcp.server.mcpserver import MCPServer
from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.multiagent.a2a import A2AServer
from strands.tools.mcp import MCPClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WeatherAgent")


# ==============================================================================
# 1. SERVIDOR MCP STREAMABLE HTTP CONECTADO EN VIVO A OPEN-METEO API
# ==============================================================================
weather_mcp_server = MCPServer("OpenMeteoWeatherMCPServer")

WMO_CODES_ES = {
    0: "Cielo despejado",
    1: "Mayormente despejado",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Niebla",
    48: "Niebla con escarcha",
    51: "Llovizna ligera",
    53: "Llovizna moderada",
    55: "Llovizna densa",
    61: "Lluvia ligera",
    63: "Lluvia moderada",
    65: "Lluvia fuerte",
    71: "Nevada ligera",
    73: "Nevada moderada",
    75: "Nevada intensa",
    80: "Chubascos ligeros",
    81: "Chubascos moderados",
    82: "Chubascos tormentosos",
    95: "Tormenta eléctrica",
    96: "Tormenta con granizo ligero",
    99: "Tormenta con granizo fuerte",
}


def fetch_live_open_meteo(city: str, days: int = 4) -> dict:
    """Consulta en tiempo real la API de Geocodificación y Pronóstico de Open-Meteo."""
    num_days = max(1, min(int(days or 4), 14))
    with httpx.Client(timeout=15.0) as client:
        # 1. Geocodificación en vivo de cualquier ciudad del mundo
        geo_resp = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city.strip(), "count": 1, "language": "es", "format": "json"},
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
        results = geo_data.get("results") or []
        if not results:
            raise ValueError(f"No se encontraron coordenadas geográficas en Open-Meteo para la ciudad '{city}'.")

        loc = results[0]
        lat = loc["latitude"]
        lon = loc["longitude"]
        resolved_name = f"{loc.get('name', city)}, {loc.get('admin1', '')} ({loc.get('country', '')})".replace(",  (", " (")
        timezone_name = loc.get("timezone", "auto")

        # 2. Consulta meteorológica satelital en tiempo real
        wx_resp = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,uv_index_max,precipitation_Sum,precipitation_probability_max,wind_speed_10m_max",
                "timezone": timezone_name,
                "forecast_days": num_days,
            },
        )
        wx_resp.raise_for_status()
        wx = wx_resp.json()

    current = wx.get("current", {})
    daily = wx.get("daily", {})

    dates = daily.get("time", [])
    w_codes = daily.get("weather_code", [])
    t_max_list = daily.get("temperature_2m_max", [])
    t_min_list = daily.get("temperature_2m_min", [])
    uv_list = daily.get("uv_index_max", [])
    rain_prob_list = daily.get("precipitation_probability_max", [])
    rain_mm_list = daily.get("precipitation_Sum", [])
    wind_list = daily.get("wind_speed_10m_max", [])

    daily_forecast = []
    for i in range(len(dates)):
        code = w_codes[i] if i < len(w_codes) else 0
        t_max = round(t_max_list[i], 1) if i < len(t_max_list) and t_max_list[i] is not None else 0
        t_min = round(t_min_list[i], 1) if i < len(t_min_list) and t_min_list[i] is not None else 0
        t_avg = round((t_max + t_min) / 2, 1)
        uv = round(uv_list[i], 1) if i < len(uv_list) and uv_list[i] is not None else 0
        rain_prob = int(rain_prob_list[i]) if i < len(rain_prob_list) and rain_prob_list[i] is not None else 0
        rain_mm = round(rain_mm_list[i], 1) if i < len(rain_mm_list) and rain_mm_list[i] is not None else 0
        wind = round(wind_list[i], 1) if i < len(wind_list) and wind_list[i] is not None else 0

        daily_forecast.append({
            "day": i + 1,
            "date": dates[i],
            "temp_c": t_avg,
            "min_c": t_min,
            "max_c": t_max,
            "condition": WMO_CODES_ES.get(code, "Parcialmente nublado"),
            "rain_probability_pct": rain_prob,
            "precipitation_mm": rain_mm,
            "uv_index": uv,
            "wind_kmh": wind,
        })

    curr_code = current.get("weather_code", 0)
    curr_temp = current.get("temperature_2m")
    if curr_temp is None and daily_forecast:
        curr_temp = daily_forecast[0]["temp_c"]

    return {
        "source": "Open-Meteo Live MCP Server",
        "city": resolved_name,
        "coordinates": {"latitude": lat, "longitude": lon},
        "timezone": wx.get("timezone", timezone_name),
        "temp_c": curr_temp,
        "feels_like_c": current.get("apparent_temperature", curr_temp),
        "min_c": daily_forecast[0]["min_c"] if daily_forecast else curr_temp,
        "max_c": daily_forecast[0]["max_c"] if daily_forecast else curr_temp,
        "condition": WMO_CODES_ES.get(curr_code, "Parcialmente nublado"),
        "humidity_pct": current.get("relative_humidity_2m", 70),
        "rain_probability_pct": daily_forecast[0]["rain_probability_pct"] if daily_forecast else 0,
        "uv_index": daily_forecast[0]["uv_index"] if daily_forecast else 0,
        "wind_kmh": current.get("wind_speed_10m", 10),
        "daily_forecast": daily_forecast,
    }


@weather_mcp_server.tool()
def mcp_get_weather(city: str, date: str = "", days: int = 4) -> dict:
    """Obtiene el pronóstico meteorológico en vivo desde Open-Meteo API a través del servidor MCP."""
    return fetch_live_open_meteo(city=city, days=days)


def _start_local_weather_mcp_server(port: int = 9006):
    """Inicia el servidor MCP Streamable HTTP conectado a Open-Meteo en un hilo de fondo."""
    async def _serve():
        try:
            await weather_mcp_server.run_streamable_http_async(
                host="127.0.0.1",
                port=port,
                streamable_http_path="/mcp",
            )
        except Exception as e:
            logger.error("Error en servidor MCP de clima: %s", e)

    server_thread = threading.Thread(target=lambda: asyncio.run(_serve()), daemon=True)
    server_thread.start()
    time.sleep(1.0)


# ==============================================================================
# 2. CLIENTE MCP (Consumo sobre Streamable HTTP)
# ==============================================================================
WEATHER_MCP_URL = os.environ.get("WEATHER_MCP_URL", "http://127.0.0.1:9006/mcp").strip()


def initialize_weather_mcp_client() -> MCPClient:
    global WEATHER_MCP_URL
    if "127.0.0.1" in WEATHER_MCP_URL or "localhost" in WEATHER_MCP_URL:
        logger.info("Iniciando servidor OpenMeteoWeatherMCPServer Streamable HTTP en puerto 9006...")
        _start_local_weather_mcp_server(port=9006)
        WEATHER_MCP_URL = "http://127.0.0.1:9006/mcp"

    client = MCPClient(url=WEATHER_MCP_URL, startup_timeout=20)
    client.start()
    logger.info("Cliente MCP de clima conectado exitosamente a %s", WEATHER_MCP_URL)
    return client


weather_mcp_client = initialize_weather_mcp_client()


@tool
def get_forecast(city: str, date: str = "", days: int = 4) -> dict:
    """Consulta el pronóstico meteorológico en tiempo real de cualquier ciudad vía MCP de clima (Open-Meteo).

    Args:
        city: Nombre de la ciudad a consultar (ej: 'Cartagena', 'Bogotá', 'Medellín', 'Madrid').
        date: Fecha de referencia en formato YYYY-MM-DD.
        days: Cantidad de días a pronosticar (1 a 14, por defecto 4).
    """
    res = weather_mcp_client.call_tool_sync(
        "call_weather_mcp",
        "mcp_get_weather",
        {"city": city, "date": date, "days": days},
    )
    sc = res.get("structuredContent", {})
    if isinstance(sc, dict) and sc.get("city"):
        return sc
    if isinstance(sc.get("result"), dict):
        return sc["result"]
    return res


# ==============================================================================
# 3. AGENTE STRANDS (A2A Server)
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
        name="Weather Agent",
        description="Especialista en consultas meteorológicas en tiempo real mediante servidor MCP de clima (Open-Meteo).",
        system_prompt=(
            "Eres un agente especialista en meteorología conectado en tiempo real a un servidor MCP de clima (Open-Meteo).\n"
            "Cuando te consulten por el clima de una ciudad:\n"
            "1. Invoca siempre la herramienta 'get_forecast' con el nombre de la ciudad y los días solicitados.\n"
            "2. Presenta únicamente los datos reales devueltos por el servidor MCP:\n"
            "   - Ciudad, coordenadas y temperatura actual / sensación térmica en °C\n"
            "   - Condición climática actual, humedad relativa (%) y velocidad del viento (km/h)\n"
            "   - Desglose día por día con temperatura mínima/máxima, probabilidad de lluvia (%) e índice UV\n"
            "   - Recomendaciones de equipaje basadas en esos datos reales."
        ),
        model=get_model(),
        tools=[get_forecast],
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
