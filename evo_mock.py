# evo_mock.py
from datetime import datetime, timedelta
import itertools
import uuid

# Catálogo simulado
SEDES = [
    "Donado 2244",
    "La Pampa 4309"
]
ACTIVIDADES = ["Funcional", "Cross", "Yoga"]

# Generamos un “calendario” simple: hoy y mañana, 19:00 y 20:00 por sede/actividad
def _generate_classes():
    base = datetime.now().replace(minute=0, second=0, microsecond=0)
    dias = [base + timedelta(days=0), base + timedelta(days=1)]
    horas = ["19:00", "20:00"]
    classes = []
    for sede, act, dia, hora in itertools.product(SEDES, ACTIVIDADES, dias, horas):
        classes.append({
            "class_id": f"{sede[:1]}-{act[:2]}-{dia.strftime('%m%d')}-{hora.replace(':','')}",
            "sede": sede,
            "actividad": act,
            "fecha": dia.strftime("%Y-%m-%d"),
            "hora": hora,
            "cupos": 5  # fijo para demo
        })
    return classes

CLASSES = _generate_classes()

# Estado en memoria (por sesión)
SESS_BOOKINGS = {}  # { session_id: [ {booking_id, class_id, estado} ] }

def list_sedes():
    return SEDES

def list_actividades():
    return ACTIVIDADES

def list_clases(sede: str, actividad: str, fecha: str):
    return [c for c in CLASSES if c["sede"] == sede and c["actividad"] == actividad and c["fecha"] == fecha]

def reservar(session_id: str, class_id: str):
    booking_id = str(uuid.uuid4())[:8].upper()
    SESS_BOOKINGS.setdefault(session_id, [])
    SESS_BOOKINGS[session_id].append({
        "booking_id": booking_id,
        "class_id": class_id,
        "estado": "confirmado"
    })
    return booking_id

def mis_turnos(session_id: str):
    return SESS_BOOKINGS.get(session_id, [])

def cancelar(session_id: str, booking_id: str) -> bool:
    arr = SESS_BOOKINGS.get(session_id, [])
    for b in arr:
        if b["booking_id"] == booking_id and b["estado"] == "confirmado":
            b["estado"] = "cancelado"
            return True
    return False

def get_class(class_id: str):
    for c in CLASSES:
        if c["class_id"] == class_id:
            return c
    return None