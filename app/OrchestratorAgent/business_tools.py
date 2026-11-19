"""
Módulo de las 8 Tools de Negocio Obligatorias para el OrchestratorAgent (TripPlanner AI).
Cada Tool invoca su respectiva función en AWS Lambda conectada a Amazon DynamoDB:
  1. CreateTrip         -> Lambda: TripPlanner-CreateTrip
  2. GetTrips           -> Lambda: TripPlanner-GetTrips
  3. UpdateTrip         -> Lambda: TripPlanner-UpdateTrip
  4. CreateItinerary    -> Lambda: TripPlanner-CreateItinerary
  5. UpdateItinerary    -> Lambda: TripPlanner-UpdateItinerary
  6. CreateReservation  -> Lambda: TripPlanner-CreateReservation
  7. GetReservations    -> Lambda: TripPlanner-GetReservations
  8. UpdateReservation  -> Lambda: TripPlanner-UpdateReservation
Incluye respaldo directo a DynamoDB / almacenamiento local para desarrollo local sin interrupciones.
"""
import os
import json
import uuid
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from strands import tool

logger = logging.getLogger("TripPlannerTools")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
TRIPS_TABLE = os.environ.get("TRIPS_TABLE", "TripPlanner-Trips")
ITINERARIES_TABLE = os.environ.get("ITINERARIES_TABLE", "TripPlanner-Itineraries")
RESERVATIONS_TABLE = os.environ.get("RESERVATIONS_TABLE", "TripPlanner-Reservations")

LOCAL_DB_FILE = os.environ.get(
    "LOCAL_DB_FILE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "local_dynamodb_store.json")),
)

# Contexto activo del usuario por hilo/petición
_CURRENT_ACTOR_ID = "default_user"


def set_current_actor_id(actor_id: str) -> None:
    global _CURRENT_ACTOR_ID
    if actor_id:
        _CURRENT_ACTOR_ID = actor_id


def get_current_actor_id() -> str:
    return _CURRENT_ACTOR_ID or "default_user"


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(obj: Any) -> Any:
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, int) and not isinstance(obj, bool):
        return Decimal(obj)
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(v) for v in obj]
    return obj


def _from_decimal(obj: Any) -> Any:
    return json.loads(json.dumps(obj, cls=DecimalEncoder))


# ==============================================================================
# ACCESO A DYNAMODB + RESPALDO LOCAL (usado si la Lambda no está activa en local)
# ==============================================================================
class _DirectStore:
    def __init__(self):
        self._ddb = None

    def _get_ddb(self):
        if os.environ.get("USE_LOCAL_STORAGE", "false").lower() == "true":
            return None
        if self._ddb is None:
            try:
                import boto3
                self._ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
            except Exception:
                return None
        return self._ddb

    def _load_local(self) -> Dict[str, Dict[str, Any]]:
        try:
            if os.path.exists(LOCAL_DB_FILE):
                with open(LOCAL_DB_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {"trips": {}, "itineraries": {}, "reservations": {}}

    def _save_local(self, store: Dict[str, Dict[str, Any]]) -> None:
        try:
            os.makedirs(os.path.dirname(LOCAL_DB_FILE), exist_ok=True)
            with open(LOCAL_DB_FILE, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2, cls=DecimalEncoder)
        except Exception as e:
            logger.warning("No se pudo guardar store local: %s", e)

    def put(self, col: str, table: str, pk: str, item: Dict[str, Any]) -> Dict[str, Any]:
        ddb = self._get_ddb()
        if ddb:
            try:
                ddb.Table(table).put_item(Item=_to_decimal(item))
                # También sincronizar en local para que el servidor local lo vea de inmediato
                store = self._load_local()
                store.setdefault(col, {})[item[pk]] = _from_decimal(item)
                self._save_local(store)
                return _from_decimal(item)
            except Exception as e:
                logger.warning("DynamoDB put fallback (%s): %s", table, e)
        store = self._load_local()
        store.setdefault(col, {})[item[pk]] = _from_decimal(item)
        self._save_local(store)
        return _from_decimal(item)

    def get(self, col: str, table: str, pk: str, val: str) -> Optional[Dict[str, Any]]:
        ddb = self._get_ddb()
        if ddb:
            try:
                resp = ddb.Table(table).get_item(Key={pk: val})
                if "Item" in resp:
                    return _from_decimal(resp["Item"])
            except Exception:
                pass
        return self._load_local().get(col, {}).get(val)

    def list_all(self, col: str, table: str, user_id: Optional[str] = None, trip_id: Optional[str] = None) -> List[Dict[str, Any]]:
        ddb = self._get_ddb()
        if ddb:
            try:
                from boto3.dynamodb.conditions import Attr
                tbl = ddb.Table(table)
                if trip_id:
                    resp = tbl.scan(FilterExpression=Attr("tripId").eq(trip_id))
                elif user_id and user_id != "all":
                    resp = tbl.scan(FilterExpression=Attr("userId").eq(user_id))
                else:
                    resp = tbl.scan()
                items = [_from_decimal(x) for x in resp.get("Items", [])]
                items.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
                return items
            except Exception:
                pass
        vals = list(self._load_local().get(col, {}).values())
        if trip_id:
            vals = [x for x in vals if x.get("tripId") == trip_id]
        if user_id and user_id != "all":
            vals = [x for x in vals if x.get("userId") in (user_id, "default_user") or not x.get("userId")]
        vals.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return vals


_store = _DirectStore()


def _invoke_lambda_or_fallback(function_name: str, payload: Dict[str, Any], fallback_fn) -> Dict[str, Any]:
    """Invoca la función AWS Lambda de negocio; si no está desplegada en el entorno actual, ejecuta el fallback conectado a DynamoDB."""
    if os.environ.get("USE_LOCAL_STORAGE", "false").lower() != "true":
        try:
            import boto3
            lambda_client = boto3.client("lambda", region_name=AWS_REGION)
            response = lambda_client.invoke(
                FunctionName=function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            raw_payload = response["Payload"].read().decode("utf-8")
            parsed = json.loads(raw_payload)
            if isinstance(parsed, dict) and "body" in parsed and "statusCode" in parsed:
                body = parsed["body"]
                return json.loads(body) if isinstance(body, str) else body
            if isinstance(parsed, dict) and ("success" in parsed or "operation" in parsed):
                return parsed
        except Exception as e:
            logger.info("Usando ejecución directa DynamoDB para %s (%s)", function_name, e)

    return fallback_fn(payload)


# ==============================================================================
# IMPLEMENTACIÓN DE RESPALDO DIRECTO PARA CADA OPERACIÓN
# ==============================================================================
def _direct_create_trip(p: Dict[str, Any]) -> Dict[str, Any]:
    trip_id = p.get("tripId") or f"trip_{uuid.uuid4().hex[:8]}"
    now = _now_iso()
    item = {
        "tripId": trip_id,
        "userId": p.get("userId") or get_current_actor_id(),
        "title": p.get("title") or f"Viaje a {p.get('destination', 'Cartagena')} desde {p.get('origin', 'Bogotá')}",
        "origin": p.get("origin", "Bogotá"),
        "destination": p.get("destination", "Cartagena"),
        "startDate": p.get("startDate", "2026-11-20"),
        "endDate": p.get("endDate", "2026-11-23"),
        "travelers": int(p.get("travelers", 1) or 1),
        "budgetCop": int(float(p.get("budgetCop", 0) or 0)),
        "status": p.get("status", "Planificado"),
        "notes": p.get("notes", ""),
        "weatherSummary": p.get("weatherSummary", ""),
        "createdAt": now,
        "updatedAt": now,
    }
    saved = _store.put("trips", TRIPS_TABLE, "tripId", item)
    return {"success": True, "operation": "CreateTrip", "trip": saved, "message": f"Viaje creado con ID {trip_id}"}


def _direct_get_trips(p: Dict[str, Any]) -> Dict[str, Any]:
    trip_id = p.get("tripId")
    if trip_id:
        t = _store.get("trips", TRIPS_TABLE, "tripId", trip_id)
        if not t:
            return {"success": False, "trips": [], "message": f"Viaje {trip_id} no encontrado"}
        t["itineraries"] = _store.list_all("itineraries", ITINERARIES_TABLE, trip_id=trip_id)
        t["reservations"] = _store.list_all("reservations", RESERVATIONS_TABLE, trip_id=trip_id)
        return {"success": True, "trip": t, "trips": [t]}

    trips = _store.list_all("trips", TRIPS_TABLE, user_id=p.get("userId"))
    for t in trips:
        tid = t["tripId"]
        t["itineraries"] = _store.list_all("itineraries", ITINERARIES_TABLE, trip_id=tid)
        t["reservations"] = _store.list_all("reservations", RESERVATIONS_TABLE, trip_id=tid)
    return {"success": True, "count": len(trips), "trips": trips}


def _direct_update_trip(p: Dict[str, Any]) -> Dict[str, Any]:
    trip_id = p.get("tripId", "")
    existing = _store.get("trips", TRIPS_TABLE, "tripId", trip_id)
    if not existing:
        return {"success": False, "message": f"Viaje {trip_id} no encontrado"}
    for k in ["title", "origin", "destination", "startDate", "endDate", "travelers", "budgetCop", "status", "notes", "weatherSummary"]:
        if k in p and p[k] is not None:
            existing[k] = int(float(p[k])) if k in ("travelers", "budgetCop") else p[k]
    existing["updatedAt"] = _now_iso()
    saved = _store.put("trips", TRIPS_TABLE, "tripId", existing)
    return {"success": True, "trip": saved, "message": f"Viaje {trip_id} actualizado"}


def _direct_create_itinerary(p: Dict[str, Any]) -> Dict[str, Any]:
    trip_id = p.get("tripId")
    if not trip_id:
        trips = _store.list_all("trips", TRIPS_TABLE)
        trip_id = trips[0]["tripId"] if trips else f"trip_{uuid.uuid4().hex[:8]}"
    itin_id = p.get("itineraryId") or f"itin_{uuid.uuid4().hex[:8]}"
    days = p.get("days", [])
    if isinstance(days, str):
        try:
            days = json.loads(days)
        except Exception:
            days = [{"dayNumber": 1, "title": "Día 1", "activities": [{"time": "09:00", "activity": days, "costCop": 0}]}]
    total_cost = 0
    for d in days:
        if isinstance(d, dict):
            for a in d.get("activities", []):
                if isinstance(a, dict):
                    total_cost += int(float(a.get("costCop", 0) or 0))
    now = _now_iso()
    item = {
        "itineraryId": itin_id,
        "tripId": trip_id,
        "userId": p.get("userId") or get_current_actor_id(),
        "destination": p.get("destination", "Cartagena"),
        "summary": p.get("summary", f"Itinerario en {p.get('destination', 'Cartagena')}"),
        "days": days,
        "totalEstimatedCostCop": total_cost,
        "createdAt": now,
        "updatedAt": now,
    }
    saved = _store.put("itineraries", ITINERARIES_TABLE, "itineraryId", item)
    return {"success": True, "itinerary": saved, "message": f"Itinerario {itin_id} creado para el viaje {trip_id}"}


def _direct_update_itinerary(p: Dict[str, Any]) -> Dict[str, Any]:
    itin_id = p.get("itineraryId")
    existing = _store.get("itineraries", ITINERARIES_TABLE, "itineraryId", itin_id) if itin_id else None
    if not existing and p.get("tripId"):
        itins = _store.list_all("itineraries", ITINERARIES_TABLE, trip_id=p["tripId"])
        if itins:
            existing = itins[0]
    if not existing:
        return {"success": False, "message": "Itinerario no encontrado"}
    if "days" in p and p["days"] is not None:
        days = json.loads(p["days"]) if isinstance(p["days"], str) else p["days"]
        existing["days"] = days
    if "summary" in p and p["summary"]:
        existing["summary"] = p["summary"]
    existing["updatedAt"] = _now_iso()
    saved = _store.put("itineraries", ITINERARIES_TABLE, "itineraryId", existing)
    return {"success": True, "itinerary": saved, "message": f"Itinerario {existing['itineraryId']} actualizado"}


def _direct_create_reservation(p: Dict[str, Any]) -> Dict[str, Any]:
    res_id = p.get("reservationId") or f"res_{uuid.uuid4().hex[:8]}"
    trip_id = p.get("tripId")
    if not trip_id:
        trips = _store.list_all("trips", TRIPS_TABLE)
        trip_id = trips[0]["tripId"] if trips else "unassigned"
    now = _now_iso()
    item = {
        "reservationId": res_id,
        "tripId": trip_id,
        "userId": p.get("userId") or get_current_actor_id(),
        "type": p.get("type", "Vuelo"),
        "provider": p.get("provider", "Avianca"),
        "title": p.get("title") or f"Reserva {p.get('type', 'Vuelo')} - {p.get('provider', 'Avianca')}",
        "referenceCode": p.get("referenceCode") or f"TP-{uuid.uuid4().hex[:6].upper()}",
        "date": p.get("date", "2026-11-20"),
        "priceCop": int(float(p.get("priceCop", 0) or 0)),
        "passengers": int(p.get("passengers", 1) or 1),
        "status": p.get("status", "Simulada"),
        "details": p.get("details") if isinstance(p.get("details"), dict) else {"description": str(p.get("details", ""))},
        "createdAt": now,
        "updatedAt": now,
    }
    saved = _store.put("reservations", RESERVATIONS_TABLE, "reservationId", item)
    return {"success": True, "reservation": saved, "message": f"Reserva {res_id} ({item['referenceCode']}) creada con estado {item['status']}"}


def _direct_get_reservations(p: Dict[str, Any]) -> Dict[str, Any]:
    res_id = p.get("reservationId")
    if res_id:
        r = _store.get("reservations", RESERVATIONS_TABLE, "reservationId", res_id)
        return {"success": bool(r), "reservations": [r] if r else []}
    items = _store.list_all("reservations", RESERVATIONS_TABLE, user_id=p.get("userId"), trip_id=p.get("tripId"))
    if p.get("status"):
        items = [x for x in items if x.get("status", "").lower() == p["status"].lower()]
    return {"success": True, "count": len(items), "reservations": items}


def _direct_update_reservation(p: Dict[str, Any]) -> Dict[str, Any]:
    res_id = p.get("reservationId", "")
    existing = _store.get("reservations", RESERVATIONS_TABLE, "reservationId", res_id)
    if not existing:
        return {"success": False, "message": f"Reserva {res_id} no encontrada"}
    for k in ["tripId", "type", "provider", "title", "referenceCode", "date", "priceCop", "passengers", "status", "details"]:
        if k in p and p[k] is not None:
            existing[k] = int(float(p[k])) if k in ("priceCop", "passengers") else p[k]
    existing["updatedAt"] = _now_iso()
    saved = _store.put("reservations", RESERVATIONS_TABLE, "reservationId", existing)
    return {"success": True, "reservation": saved, "message": f"Reserva {res_id} actualizada a estado {existing['status']}"}


def _direct_compare_budget(p: Dict[str, Any]) -> Dict[str, Any]:
    trip_id = p.get("tripId")
    user_id = p.get("userId") or get_current_actor_id()
    trip = _store.get("trips", TRIPS_TABLE, "tripId", trip_id) if trip_id else None
    if not trip:
        trips = _store.list_all("trips", TRIPS_TABLE, user_id=user_id)
        if trips:
            trip = trips[0]
            trip_id = trip["tripId"]
    if not trip:
        return {"success": False, "operation": "CompareBudget", "message": "No se encontró un viaje activo para comparar el presupuesto."}

    budget_allocated = int(float(trip.get("budgetCop") or 0))
    travelers = max(1, int(trip.get("travelers") or 1))
    itins = _store.list_all("itineraries", ITINERARIES_TABLE, trip_id=trip_id)
    reservations = _store.list_all("reservations", RESERVATIONS_TABLE, trip_id=trip_id)
    active_res = [r for r in reservations if r.get("status") != "Cancelada"]

    flights_cop = sum(int(float(r.get("priceCop") or 0)) for r in active_res if str(r.get("type", "")).lower() == "vuelo")
    hotels_cop = sum(int(float(r.get("priceCop") or 0)) for r in active_res if str(r.get("type", "")).lower() == "hotel")
    transport_cop = sum(int(float(r.get("priceCop") or 0)) for r in active_res if str(r.get("type", "")).lower() == "transporte")
    res_act_cop = sum(int(float(r.get("priceCop") or 0)) for r in active_res if str(r.get("type", "")).lower() not in ("vuelo", "hotel", "transporte"))

    itin_act_cop = 0
    act_count = 0
    days_count = 0
    for it in itins:
        days = it.get("days") or []
        days_count += len(days)
        for d in days:
            if isinstance(d, dict):
                for a in d.get("activities") or []:
                    if isinstance(a, dict):
                        act_count += 1
                        itin_act_cop += int(float(a.get("costCop", a.get("cost", 0)) or 0))

    confirmed_cop = sum(int(float(r.get("priceCop") or 0)) for r in active_res if r.get("status") == "Confirmada")
    pending_cop = sum(int(float(r.get("priceCop") or 0)) for r in active_res if r.get("status") == "Pendiente")
    simulated_cop = sum(int(float(r.get("priceCop") or 0)) for r in active_res if r.get("status") == "Simulada")

    extra_hotel = int(float(p.get("estimatedHotelCop") or 0))
    extra_flight = int(float(p.get("estimatedFlightCop") or 0))
    total_act_cop = itin_act_cop + res_act_cop
    total_committed = flights_cop + hotels_cop + transport_cop + total_act_cop + extra_hotel + extra_flight
    diff = budget_allocated - total_committed
    pct = round((total_committed / budget_allocated) * 100, 1) if budget_allocated > 0 else 0.0

    if budget_allocated <= 0:
        level, title, msg = "SIN_PRESUPUESTO", "Presupuesto no definido", "Asigna un presupuesto en COP al viaje."
    elif diff < 0:
        level = "EXCEDIDO"
        title = "Alerta: Presupuesto Excedido"
        msg = f"Los costos superan el presupuesto en ${abs(diff):,} COP ({pct}% utilizado).".replace(",", ".")
    elif pct >= 80.0:
        level = "PRECAUCION"
        title = "Margen Ajustado (Precaución)"
        msg = f"Has utilizado el {pct}% del presupuesto. Saldo disponible: ${diff:,} COP.".replace(",", ".")
    else:
        level = "OPTIMO"
        title = "Presupuesto Saludable (Margen Óptimo)"
        msg = f"Utilización del {pct}%. Saldo disponible: ${diff:,} COP (${int(diff/travelers):,} COP por viajero).".replace(",", ".")

    comparison = {
        "tripId": trip_id,
        "tripTitle": trip.get("title", f"Viaje a {trip.get('destination', '')}"),
        "origin": trip.get("origin", "Bogotá"),
        "destination": trip.get("destination", "Cartagena"),
        "travelers": travelers,
        "currency": "COP",
        "budgetAllocatedCop": budget_allocated,
        "totalCommittedCop": total_committed,
        "differenceCop": diff,
        "isWithinBudget": diff >= 0,
        "usagePercentage": pct,
        "perTravelerAllocatedCop": int(round(budget_allocated / travelers)),
        "perTravelerCommittedCop": int(round(total_committed / travelers)),
        "categories": {
            "flightsCop": flights_cop + extra_flight,
            "hotelsCop": hotels_cop + extra_hotel,
            "activitiesCop": total_act_cop,
            "transportCop": transport_cop,
        },
        "reservationsByStatus": {
            "confirmedCop": confirmed_cop,
            "pendingCop": pending_cop,
            "simulatedCop": simulated_cop,
            "totalReservationsCount": len(active_res),
        },
        "itineraryMetrics": {
            "daysCount": days_count,
            "activitiesCount": act_count,
            "itineraryActivitiesCop": itin_act_cop,
        },
        "alert": {"level": level, "title": title, "message": msg},
    }
    return {"success": True, "operation": "CompareBudget", "message": msg, "comparison": comparison}


# ==============================================================================
# DEFINICIÓN DE LAS 8 @tool PARA STRANDS AGENT (ORCHESTRATOR)
# ==============================================================================

@tool
def CreateTrip(
    origin: str,
    destination: str,
    startDate: str,
    endDate: str,
    travelers: int = 1,
    budgetCop: int = 0,
    title: str = "",
    notes: str = "",
    weatherSummary: str = "",
) -> str:
    """Crea y persiste un nuevo viaje del usuario en Amazon DynamoDB mediante la Lambda TripPlanner-CreateTrip.
    Úsalo cuando el usuario solicite crear, guardar o registrar un viaje o vacaciones.

    Args:
        origin: Ciudad de origen (ej: 'Bogotá').
        destination: Ciudad de destino (ej: 'Cartagena').
        startDate: Fecha de inicio en formato YYYY-MM-DD (ej: '2026-11-20').
        endDate: Fecha de regreso en formato YYYY-MM-DD (ej: '2026-11-23').
        travelers: Número total de viajeros (ej: 3).
        budgetCop: Presupuesto total en Pesos Colombianos COP (ej: 5000000).
        title: Título descriptivo del viaje (ej: 'Vacaciones de 4 días en Cartagena').
        notes: Notas o preferencias adicionales del viaje.
        weatherSummary: Resumen del clima esperado en el destino.
    """
    payload = {
        "userId": get_current_actor_id(),
        "origin": origin,
        "destination": destination,
        "startDate": startDate,
        "endDate": endDate,
        "travelers": travelers,
        "budgetCop": budgetCop,
        "title": title or f"Vacaciones en {destination} ({travelers} viajeros)",
        "notes": notes,
        "weatherSummary": weatherSummary,
    }
    res = _invoke_lambda_or_fallback("TripPlanner-CreateTrip", payload, _direct_create_trip)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def GetTrips(tripId: str = "") -> str:
    """Consulta los viajes guardados del usuario en Amazon DynamoDB mediante la Lambda TripPlanner-GetTrips.
    Incluye los itinerarios y reservas asociadas a cada viaje.

    Args:
        tripId: ID opcional de un viaje específico (ej: 'trip_a1b2c3d4'). Si se deja vacío, lista todos los viajes.
    """
    payload: Dict[str, Any] = {}
    if tripId:
        payload["tripId"] = tripId
    res = _invoke_lambda_or_fallback("TripPlanner-GetTrips", payload, _direct_get_trips)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def UpdateTrip(
    tripId: str,
    title: str = "",
    startDate: str = "",
    endDate: str = "",
    travelers: int = 0,
    budgetCop: int = 0,
    status: str = "",
    notes: str = "",
) -> str:
    """Actualiza los datos o estado de un viaje existente en Amazon DynamoDB mediante la Lambda TripPlanner-UpdateTrip.

    Args:
        tripId: ID del viaje a actualizar (obligatorio).
        title: Nuevo título del viaje (opcional).
        startDate: Nueva fecha de inicio YYYY-MM-DD (opcional).
        endDate: Nueva fecha de fin YYYY-MM-DD (opcional).
        travelers: Nuevo número de viajeros (opcional).
        budgetCop: Nuevo presupuesto en COP (opcional).
        status: Nuevo estado: 'Planificado', 'Confirmado', 'En Curso', 'Completado' o 'Cancelado' (opcional).
        notes: Notas actualizadas (opcional).
    """
    payload: Dict[str, Any] = {"tripId": tripId}
    if title:
        payload["title"] = title
    if startDate:
        payload["startDate"] = startDate
    if endDate:
        payload["endDate"] = endDate
    if travelers > 0:
        payload["travelers"] = travelers
    if budgetCop > 0:
        payload["budgetCop"] = budgetCop
    if status:
        payload["status"] = status
    if notes:
        payload["notes"] = notes
    res = _invoke_lambda_or_fallback("TripPlanner-UpdateTrip", payload, _direct_update_trip)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def CreateItinerary(
    tripId: str,
    destination: str,
    daysJson: str,
    summary: str = "",
) -> str:
    """Crea y guarda el itinerario turístico día por día asociado a un viaje mediante la Lambda TripPlanner-CreateItinerary.

    Args:
        tripId: ID del viaje al que pertenece el itinerario (ej: 'trip_a1b2c3d4').
        destination: Ciudad de destino (ej: 'Cartagena').
        daysJson: Cadena JSON con la lista de días. Formato: '[{"dayNumber": 1, "date": "2026-11-20", "title": "Llegada y Ciudad Amurallada", "activities": [{"time": "10:00", "activity": "Recorrido Centro Histórico y Castillo San Felipe", "location": "Centro Histórico", "costCop": 180000}]}]'
        summary: Resumen general del itinerario.
    """
    try:
        days_list = json.loads(daysJson) if isinstance(daysJson, str) else daysJson
    except Exception:
        days_list = [{"dayNumber": 1, "title": "Itinerario General", "activities": [{"time": "09:00", "activity": str(daysJson), "costCop": 0}]}]

    payload = {
        "tripId": tripId,
        "userId": get_current_actor_id(),
        "destination": destination,
        "days": days_list,
        "summary": summary or f"Itinerario turístico en {destination}",
    }
    res = _invoke_lambda_or_fallback("TripPlanner-CreateItinerary", payload, _direct_create_itinerary)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def UpdateItinerary(
    itineraryId: str,
    daysJson: str,
    summary: str = "",
    tripId: str = "",
) -> str:
    """Modifica las actividades o días de un itinerario existente en Amazon DynamoDB mediante la Lambda TripPlanner-UpdateItinerary.

    Args:
        itineraryId: ID del itinerario a modificar (ej: 'itin_1234abcd').
        daysJson: Cadena JSON actualizada con la lista de días y actividades.
        summary: Nuevo resumen del itinerario (opcional).
        tripId: ID del viaje asociado (opcional si se desconoce itineraryId).
    """
    try:
        days_list = json.loads(daysJson) if isinstance(daysJson, str) else daysJson
    except Exception:
        days_list = [{"dayNumber": 1, "title": "Itinerario Actualizado", "activities": [{"time": "09:00", "activity": str(daysJson), "costCop": 0}]}]

    payload: Dict[str, Any] = {"itineraryId": itineraryId, "days": days_list}
    if summary:
        payload["summary"] = summary
    if tripId:
        payload["tripId"] = tripId
    res = _invoke_lambda_or_fallback("TripPlanner-UpdateItinerary", payload, _direct_update_itinerary)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def CreateReservation(
    tripId: str,
    type: str,
    provider: str,
    title: str,
    date: str,
    priceCop: int,
    passengers: int = 1,
    status: str = "Simulada",
    details: str = "",
) -> str:
    """Registra una reserva (Vuelo, Hotel, Actividad o Transporte) asociada a un viaje en Amazon DynamoDB mediante la Lambda TripPlanner-CreateReservation.

    Args:
        tripId: ID del viaje al que se asocia la reserva (ej: 'trip_a1b2c3d4').
        type: Tipo de reserva: 'Vuelo', 'Hotel', 'Actividad' o 'Transporte'.
        provider: Proveedor o aerolínea (ej: 'Avianca', 'Wingo', 'LATAM', 'Hotel Caribe').
        title: Descripción corta de la reserva (ej: 'Vuelo AV9520 Bogotá -> Cartagena (3 pasajeros)').
        date: Fecha del servicio en formato YYYY-MM-DD.
        priceCop: Valor total de la reserva en Pesos Colombianos (COP).
        passengers: Cantidad de personas incluidas en la reserva.
        status: Estado de la reserva: 'Simulada', 'Pendiente' o 'Confirmada'.
        details: Detalles de horario, número de vuelo o notas de la reserva.
    """
    payload = {
        "tripId": tripId,
        "userId": get_current_actor_id(),
        "type": type,
        "provider": provider,
        "title": title,
        "date": date,
        "priceCop": priceCop,
        "passengers": passengers,
        "status": status,
        "details": {"description": details},
    }
    res = _invoke_lambda_or_fallback("TripPlanner-CreateReservation", payload, _direct_create_reservation)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def GetReservations(tripId: str = "", status: str = "") -> str:
    """Consulta las reservas registradas en Amazon DynamoDB mediante la Lambda TripPlanner-GetReservations.

    Args:
        tripId: Filtrar opcionalmente por ID de viaje.
        status: Filtrar opcionalmente por estado ('Simulada', 'Pendiente', 'Confirmada').
    """
    payload: Dict[str, Any] = {}
    if tripId:
        payload["tripId"] = tripId
    if status:
        payload["status"] = status
    res = _invoke_lambda_or_fallback("TripPlanner-GetReservations", payload, _direct_get_reservations)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def UpdateReservation(
    reservationId: str,
    status: str = "",
    priceCop: int = 0,
    date: str = "",
    title: str = "",
    details: str = "",
) -> str:
    """Actualiza una reserva o cambia su estado ('Simulada', 'Pendiente', 'Confirmada', 'Cancelada') mediante la Lambda TripPlanner-UpdateReservation.

    Args:
        reservationId: ID de la reserva a actualizar (obligatorio, ej: 'res_1234abcd').
        status: Nuevo estado de la reserva ('Simulada', 'Pendiente', 'Confirmada', 'Cancelada').
        priceCop: Nuevo precio en COP (opcional).
        date: Nueva fecha YYYY-MM-DD (opcional).
        title: Nuevo título de la reserva (opcional).
        details: Nuevos detalles (opcional).
    """
    payload: Dict[str, Any] = {"reservationId": reservationId}
    if status:
        payload["status"] = status
    if priceCop > 0:
        payload["priceCop"] = priceCop
    if date:
        payload["date"] = date
    if title:
        payload["title"] = title
    if details:
        payload["details"] = {"description": details}
    res = _invoke_lambda_or_fallback("TripPlanner-UpdateReservation", payload, _direct_update_reservation)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


@tool
def CompareBudget(
    tripId: str = "",
    estimatedHotelCop: int = 0,
    estimatedFlightCop: int = 0,
) -> str:
    """Funcionalidad Comparador de Presupuestos: Compara el presupuesto asignado al viaje en DynamoDB
    frente a los costos registrados/estimados de vuelos, hoteles, actividades del itinerario y reservas asociadas,
    calculando diferencias, totales por categoría, costo por viajero y alertas de margen (sin pedir datos de tarjetas bancarias ni CVV).

    Args:
        tripId: ID del viaje a evaluar (opcional; si se omite evalúa el viaje más reciente del usuario).
        estimatedHotelCop: Costo hipotético adicional de hotel en COP para simular escenarios (opcional).
        estimatedFlightCop: Costo hipotético adicional de vuelos en COP para simular escenarios (opcional).
    """
    payload: Dict[str, Any] = {"userId": get_current_actor_id()}
    if tripId:
        payload["tripId"] = tripId
    if estimatedHotelCop > 0:
        payload["estimatedHotelCop"] = estimatedHotelCop
    if estimatedFlightCop > 0:
        payload["estimatedFlightCop"] = estimatedFlightCop
    res = _invoke_lambda_or_fallback("TripPlanner-CompareBudget", payload, _direct_compare_budget)
    return json.dumps(res, ensure_ascii=False, cls=DecimalEncoder)


ALL_BUSINESS_TOOLS = [
    CreateTrip,
    GetTrips,
    UpdateTrip,
    CreateItinerary,
    UpdateItinerary,
    CreateReservation,
    GetReservations,
    UpdateReservation,
    CompareBudget,
]
