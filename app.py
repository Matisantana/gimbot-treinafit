from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path
from dotenv import load_dotenv
import os, json, uuid
from datetime import datetime, timedelta

from advisor import SessionCtx, route, first_message, menu_msg
import evo_mock as evo

# ---------------- base setup ----------------
load_dotenv()
BASE_DIR = Path(__file__).parent
app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DATA_PATH = BASE_DIR / "data" / "faqs.json"
with open(DATA_PATH, "r", encoding="utf-8-sig") as f:
    FAQS = json.load(f)

# ---------------- sesiones en memoria ----------------
SESSIONS: dict[str, SessionCtx] = {}
CHAT_LOG: dict[str, list[dict]] = {}  # para tu UI: [{user:..}|{bot:..}]

def get_session_id(request: Request) -> str:
    sid = request.cookies.get("session_id")
    if not sid:
        sid = str(uuid.uuid4())
    return sid

def get_ctx(session_id: str) -> SessionCtx:
    if session_id not in SESSIONS:
        SESSIONS[session_id] = SessionCtx()
        CHAT_LOG[session_id] = [{"bot": first_message()}]
    return SESSIONS[session_id]

def add_msg(session_id: str, role: str, text: str):
    CHAT_LOG.setdefault(session_id, [])
    CHAT_LOG[session_id].append({role: text})

# ---------------- helpers demo ----------------
import difflib, unicodedata

def _norm(s: str) -> str:
    if not s: return ""
    s = s.strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s

def buscar_faq(texto: str) -> str | None:
    t = _norm(texto)
    # 1) match directo por inclusión
    for item in FAQS:
        if _norm(item["q"]) in t:
            return item["a"]
    # 2) fuzzy contra todas las claves q
    keys = [_norm(item["q"]) for item in FAQS]
    hit = difflib.get_close_matches(t, keys, n=1, cutoff=0.65)
    if hit:
        idx = keys.index(hit[0])
        return FAQS[idx]["a"]
    return None

def resolve_fecha(keyword: str) -> str:
    base = datetime.now()
    if keyword.lower() == "hoy":
        return base.strftime("%Y-%m-%d")
    return (base + timedelta(days=1)).strftime("%Y-%m-%d")

# ---------------- web UI ----------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    sid = get_session_id(request)
    ctx = get_ctx(sid)
    messages = CHAT_LOG.get(sid, [{"bot": first_message()}])
    resp = templates.TemplateResponse("chat.html", {"request": request, "messages": messages})
    resp.set_cookie("session_id", sid, max_age=60*60*24*7, httponly=True)
    return resp

@app.get("/chat")
def chat_get():
    return RedirectResponse(url="/", status_code=307)

@app.post("/chat", response_class=HTMLResponse)
def chat_post(request: Request, message: str = Form(...)):
    sid = get_session_id(request)
    ctx = get_ctx(sid)
    user_text = (message or "").strip()
    add_msg(sid, "user", user_text)

    # 1) si estamos dentro del flow de reserva/cancelación, lo resolvemos acá con el mock EVO
    reply = handle_business_flows(sid, ctx, user_text)

    # 2) si el flow no respondió (None), pasamos al asesor (route)
    if reply is None:
        # antes, probamos FAQ simples para no abrumar
        faq = buscar_faq(user_text)
        if faq:
            reply = faq + "\n\n" + "¿Querés que te ayude a **reservar** algo? (escribí *reservar*)"
        else:
            reply = route(ctx, user_text)

    add_msg(sid, "bot", reply)
    resp = templates.TemplateResponse("chat.html", {"request": request, "messages": CHAT_LOG[sid]})
    resp.set_cookie("session_id", sid, max_age=60*60*24*7, httponly=True)
    return resp

# ---------------- flujo de negocio (simulación EVO) ----------------
def handle_business_flows(sid: str, ctx: SessionCtx, user_text: str) -> str | None:
    t = (user_text or "").strip().lower()

    # MIS TURNOS
    if ctx.flow == "mis_turnos" and ctx.step == "mis_turnos":
        bookings = evo.mis_turnos(sid)
        if not bookings:
            ctx.flow, ctx.step = "idle", "menu"
            return "No tenés reservas por ahora. ¿Querés **reservar** una? (escribí *reservar*)"
        listado = []
        for b in bookings:
            c = evo.get_class(b["class_id"])
            if not c: 
                continue
            listado.append(f"- ID **{b['booking_id']}** · {c['actividad']} · {c['sede']} · {c['fecha']} {c['hora']} · {b['estado']}")
        ctx.flow, ctx.step = "idle", "menu"
        return "Tus turnos:\n" + "\n".join(listado) + "\n\n" + menu_msg(ctx)

    # CANCELAR
    if ctx.flow == "cancelar" and ctx.step == "cancelar":
        # si el usuario envía un ID, intentamos cancelar
        if len(t) >= 6 and not t.startswith(("cancelar","2")):
            ok = evo.cancelar(sid, t.strip())
            ctx.flow, ctx.step = "idle", "menu"
            if ok:
                return f"Listo, cancelé la reserva **{t}** ❌\n\n" + menu_msg(ctx)
            else:
                return "Ese ID no existe o ya estaba cancelado. " + menu_msg(ctx)
        # si aún no envió un ID, mostramos lista
        bookings = evo.mis_turnos(sid)
        if not bookings:
            ctx.flow, ctx.step = "idle", "menu"
            return "No encontré turnos para cancelar. " + menu_msg(ctx)
        listado = []
        for b in bookings:
            c = evo.get_class(b["class_id"])
            if not c: continue
            if b["estado"] == "confirmado":
                listado.append(f"- **{b['booking_id']}** · {c['actividad']} {c['fecha']} {c['hora']} ({c['sede']})")
        if not listado:
            ctx.flow, ctx.step = "idle", "menu"
            return "No tenés turnos activos. " + menu_msg(ctx)
        return "Decime el **ID** a cancelar:\n" + "\n".join(listado)

    # RESERVA – pasos guiados con advisor
    if ctx.flow.startswith("reservar"):
        # cuando advisor llega a confirmar, acá ejecutamos la simulación
        if ctx.step == "reservar_confirmar" and t in ["si", "sí", "ok", "dale", "confirmo", "confirmar"]:
            # traducir fecha “hoy/mañana”
            fecha = resolve_fecha(ctx.tmp["fecha"])
            # listar y buscar la clase exacta
            posibles = evo.list_clases(ctx.tmp["sede"], ctx.tmp["actividad"], fecha)
            clase = next((c for c in posibles if c["hora"] == ctx.tmp["hora"]), None)
            if not clase:
                ctx.flow, ctx.step = "idle", "menu"
                return "Uff, no encontré cupo justo en ese horario. Probá otro 🙂\n" + menu_msg(ctx)
            booking_id = evo.reservar(sid, clase["class_id"])
            ctx.flow, ctx.step = "idle", "menu"
            return (f"**Reserva confirmada** ✅\n"
                    f"ID: **{booking_id}**\n"
                    f"{clase['actividad']} · {clase['sede']} · {clase['fecha']} {clase['hora']}\n\n"
                    "Te voy a **recordar** unas horas antes 😉\n" + menu_msg(ctx))

        # listado de opciones cuando pide horario
        if ctx.step == "reservar_horario" and t not in ["19:00","1900","20:00","2000"]:
            # mostramos ofertas reales del mock para ese día
            fecha = resolve_fecha(ctx.tmp.get("fecha","hoy"))
            arr = evo.list_clases(ctx.tmp.get("sede","Centro"), ctx.tmp.get("actividad","Funcional"), fecha)
            if not arr:
                return "No hay cupos ese día. Probá *hoy* o *mañana*."
            horarios = ", ".join(sorted({c["hora"] for c in arr}))
            return f"Disponibles para {fecha}: **{horarios}**. Elegí uno."

    # No hay nada que responder en flows → devolvemos None (responde el asesor)
    return None