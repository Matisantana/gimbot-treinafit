# advisor.py

import difflib
import unicodedata
import re
from dataclasses import dataclass, field
from evo_mock import SEDES, ACTIVIDADES   # <-- usamos las sedes/actividades del mock

# ------------------ utils de texto (tolerante a errores) ------------------

def _norm(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    # remover tildes
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s

def fuzzy_choice(user_text: str, options: list[str], cutoff: float = 0.6) -> str | None:
    """Devuelve la opción más parecida a lo que escribió el usuario (o None)."""
    if not user_text:
        return None
    norm_opts = {_norm(opt): opt for opt in options}
    match = difflib.get_close_matches(_norm(user_text), list(norm_opts.keys()), n=1, cutoff=cutoff)
    return norm_opts[match[0]] if match else None

def yn(user_text: str) -> bool | None:
    """Sí/No tolerante."""
    yes = ["si", "sí", "ok", "dale", "confirmo", "confirmar", "yes", "s"]
    no  = ["no", "n", "cancelar", "nah", "paso"]
    t = _norm(user_text)
    if t in yes:
        return True
    if t in no:
        return False
    return None

def parse_option_12(s: str) -> int | None:
    """
    Devuelve 1 o 2 si el texto es exactamente opción 1/2 con adornos típicos:
    '1', '1)', '1 .', '1-', ' 2 )', etc. Si no matchea, devuelve None.
    """
    t = _norm(s)
    m = re.match(r'^([12])(?:\s*[\)\.\-]?\s*)$', t)
    return int(m.group(1)) if m else None

# ------------------ contexto de sesión ------------------

@dataclass
class SessionCtx:
    name: str | None = None
    goal: str | None = None
    motivation: str | None = None
    relapse_reason: str | None = None
    flow: str = "idle"     # idle | reservar_* | cancelar | mis_turnos
    step: str = "start"    # pasos internos de cada flow
    tmp: dict = field(default_factory=dict)

# ------------------ mensajes base ------------------

def first_message() -> str:
    return (
        "¡Hola! Soy **Luka**, asesor de Treina Fit 🙌\n"
        "Quiero ayudarte a mantenerte constante y motivado.\n"
        "Para empezar, decime tu **nombre**."
    )

def menu_msg(ctx: SessionCtx, refuerzo: bool = False) -> str:
    ref = ""
    if refuerzo and ctx.motivation == "alta":
        ref = "¡Bien ahí! Vamos a mantener esa racha 🔥\n"
    if refuerzo and ctx.motivation == "media":
        ref = "¿Que anda pasando? podemos probar bajando el ritmo\n"
    if refuerzo and ctx.motivation == "baja":
        ref = "¡Arriba ese ánimo!, vamos a hacerlo simple y progresivo para retomar 💙\n"
    return (
        f"{ref}"
        "Puedo ayudarte con:\n"
        "1) **Reservar** una clase\n"
        "2) **Cancelar** una reserva\n"
        "3) Ver **mis turnos**\n"
        "También podemos revisar tu plan cuando quieras: escribí *plan*."
    )

def sugerir_plan(ctx: SessionCtx) -> str:
    motivo = ctx.relapse_reason or "varios motivos"
    sugerencia = (
        f"Entiendo lo de *{motivo}*. Te propongo esto:\n"
        "- Semana 1: 2 clases cortas (40') sin presión.\n"
        "- Semana 2: subimos a 3, mezclando fuerza + movilidad.\n"
        "- Ajuste de alimentación simple (agua + proteína suficiente).\n"
        "Si te va, ahora **reservamos** la primera así arrancás 😉 Escribí *reservar*."
    )
    return sugerencia + "\n\n" + menu_msg(ctx)

# ------------------ router principal ------------------

def route(ctx: SessionCtx, user_text: str) -> str:
    t = (user_text or "").strip()

    # onboarding
    if ctx.step == "start":
        if len(t) < 2:
            return "Decime tu **nombre** así te hablo bien 🙂"
        ctx.name = t.title()
        ctx.step = "ask_goal"
        return (f"¡Genial, {ctx.name}! ¿Cuál es tu **objetivo principal** ahora? "
                "(Ej: bajar grasa, ganar masa, rendir en fútbol, salud)")

    if ctx.step == "ask_goal":
        ctx.goal = t
        ctx.step = "ask_motivation"
        return ("Anotado 💾. Siendo sincero/a, ¿cómo te sentís de **motivación** esta semana?\n"
                "Escribí: *Alta*, *Media* o *Baja*.")

    if ctx.step == "ask_motivation":
        mopt = fuzzy_choice(t, ["alta", "media", "baja"], cutoff=0.6)
        if not mopt:
            return "Decime si tu motivación está *Alta*, *Media* o *Baja*."
        ctx.motivation = mopt
        if mopt == "baja":
            ctx.step = "ask_relapse"
            return ("Gracias por contarlo. ¿Qué te está tirando abajo?\n"
                    "Ej: poco tiempo, dolor/lesión, no veo resultados, me aburro, tema $$, otra cosa…")
        ctx.step = "menu"
        return menu_msg(ctx, refuerzo=True)

    if ctx.step == "ask_relapse":
        ctx.relapse_reason = t
        ctx.step = "menu"
        return sugerir_plan(ctx)

    # Menú general y flujos
    low = t.lower()

    if low in ["menu", "menú", "ayuda", "opciones"]:
        ctx.flow, ctx.step = "idle", "menu"
        return menu_msg(ctx)

    if low.startswith("reserv") or low in ["1", "turno", "sacar turno"]:
        ctx.flow, ctx.step = "reservar_sede", "reservar_sede"
        return ("Perfecto 💪. ¿En qué **sede** te queda mejor?\n"
                f"1) {SEDES[0]}\n"
                f"2) {SEDES[1]}\n"
                "Podés responder 1) / 2) o escribir el nombre (ej: *Donado* / *La Pampa*).")

    if low.startswith("cancel") or low in ["2", "dar de baja"]:
        ctx.flow, ctx.step = "cancelar", "cancelar"
        return "Te muestro tus **próximos turnos**. Decime el **ID** del que querés cancelar."

    if "mis turnos" in low or low in ["3", "turnos"]:
        ctx.flow, ctx.step = "mis_turnos", "mis_turnos"
        return "Estos son tus turnos (simulados)."

    # Pasos del flujo de reserva
    if ctx.flow.startswith("reservar"):
        return handle_reserva(ctx, low)

    # Por defecto
    return menu_msg(ctx)

# ------------------ flujo de reserva ------------------

def handle_reserva(ctx: SessionCtx, low: str) -> str:
    # SEDE
    if ctx.step == "reservar_sede":
        chosen = None

        # 1) primero intentamos opción numérica exacta (acepta '1', '1)', '1 .', etc. pero NO '11')
        opt = parse_option_12(low)
        if opt == 1:
            chosen = SEDES[0]
        elif opt == 2:
            chosen = SEDES[1]
        else:
            # 2) alias rápidos por texto
            norm = _norm(low)
            alias = {
                "donado": SEDES[0],
                "donado 2244": SEDES[0],
                "la pampa": SEDES[1],
                "pampa": SEDES[1],
                "la pampa 4309": SEDES[1],
                "pampa 4309": SEDES[1],
            }
            chosen = alias.get(norm)
            # 3) fuzzy si no hubo alias
            if not chosen:
                chosen = fuzzy_choice(low, SEDES, cutoff=0.5)

        if not chosen:
            return (
                "Elegí una sede:\n"
                f"1) {SEDES[0]}\n"
                f"2) {SEDES[1]}\n"
                "Podés escribir 1) / 2) o parte del nombre (ej: *Donado* / *La Pampa*)."
            )

        ctx.tmp["sede"] = chosen
        ctx.step = "reservar_actividad"
        return f"¡Perfecto! Elegiste **{chosen}**. ¿Qué **actividad** querés? (Funcional / Cross / Yoga)"

    # ACTIVIDAD
    elif ctx.step == "reservar_actividad":
        act = fuzzy_choice(low, ACTIVIDADES, cutoff=0.6)
        if not act:
            return "Decime **Funcional**, **Cross** o **Yoga**."
        ctx.tmp["actividad"] = act
        ctx.step = "reservar_fecha"
        return "¿Para **qué día**? Escribí *hoy* o *mañana*."

    # FECHA
    elif ctx.step == "reservar_fecha":
        fz = fuzzy_choice(low, ["hoy", "mañana", "manana"], cutoff=0.6)
        if not fz:
            return "Decime *hoy* o *mañana*."
        ctx.tmp["fecha"] = "hoy" if fz == "hoy" else "mañana"
        ctx.step = "reservar_horario"
        return "Genial. Horarios disponibles: **19:00** o **20:00**. ¿Cuál te va?"

    # HORA
    elif ctx.step == "reservar_horario":
        hr = fuzzy_choice(low, ["19:00", "1900", "20:00", "2000"], cutoff=0.6)
        if not hr:
            return "Elegí **19:00** o **20:00**."
        hh = "19:00" if hr.startswith("19") else "20:00"
        ctx.tmp["hora"] = hh
        ctx.step = "reservar_confirmar"
        return (f"Confirmo: {ctx.tmp['actividad']} en {ctx.tmp['sede']} "
                f"**{ctx.tmp['fecha']}** a las **{ctx.tmp['hora']}**. ¿Reservo? (sí/no)")

    # CONFIRMAR
    elif ctx.step == "reservar_confirmar":
        y = yn(low)
        if y is None:
            return "¿Confirmo la reserva? (sí/no)"
        if y:
            ctx.step = "menu"
            return "¡Listo! Estoy reservando… ✅"
        else:
            ctx.flow, ctx.step = "idle", "menu"
            return "Cancelado. Volvemos al menú."

    return "Seguimos con la reserva. Decime lo último que te pedí 🙂"