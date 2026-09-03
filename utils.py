from datetime import datetime, timedelta

import pandas as pd
from dateutil.parser import parse


def _para_data(valor):
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass
    if hasattr(valor, "date") and not isinstance(valor, str):
        return valor.date()
    if isinstance(valor, str):
        valor = valor.strip()
        if not valor:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(valor, fmt).date()
            except Exception:
                pass
        try:
            return parse(valor, dayfirst=True).date()
        except Exception:
            return None
    try:
        data = pd.to_datetime(valor)
        return None if pd.isna(data) else data.date()
    except Exception:
        return None


def calcular_status_anuidade(data_inicio_ord, data_fim_ord, data_inicio_extraord, data_fim_extraord, data_pagamento=None):
    hoje = datetime.now().date()
    if _para_data(data_pagamento):
        return "pago"

    inicio_ord = _para_data(data_inicio_ord)
    fim_ord = _para_data(data_fim_ord)
    inicio_extra = _para_data(data_inicio_extraord)
    fim_extra = _para_data(data_fim_extraord)

    if not inicio_ord or not fim_ord:
        return "pendente"
    if inicio_ord <= hoje <= fim_ord:
        return "amarelo" if hoje >= fim_ord - timedelta(days=30) else "verde"
    if inicio_extra and fim_extra and inicio_extra <= hoje <= fim_extra:
        return "vermelho"
    if fim_extra and hoje > fim_extra:
        return "vermelho"
    return "verde"


def obter_dias_restantes(data_fim_ord, data_pagamento=None):
    if _para_data(data_pagamento):
        return 0
    fim_ord = _para_data(data_fim_ord)
    if not fim_ord:
        return "-"
    return max(0, (fim_ord - datetime.now().date()).days)


def formatar_data(data):
    data = _para_data(data)
    return data.strftime("%d/%m/%Y") if data else "-"


def obter_cor_status(status):
    cores = {
        "verde": "#00CC00",
        "amarelo": "#FFCC00",
        "vermelho": "#FF0000",
        "pago": "#0099FF",
        "nao_pagar": "#CCCCCC",
        "pendente": "#999999",
    }
    return cores.get(status, "#CCCCCC")


def criar_emoji_status(status):
    emojis = {
        "verde": "✅",
        "amarelo": "⚠️",
        "vermelho": "❌",
        "pago": "💰",
        "nao_pagar": "⛔",
        "pendente": "⏳",
    }
    return emojis.get(status, "❓")
