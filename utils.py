from datetime import datetime, timedelta
import pandas as pd

def _para_data(valor):
    if valor is None or pd.isna(valor) or valor == "":
        return None
    if hasattr(valor, "date") and not isinstance(valor, str):
        return valor.date()
    try:
        return pd.to_datetime(valor).date()
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
    return max(0, (fim_ord - datetime.now().date()).days) if fim_ord else "-"


def formatar_data(data):
    dt = _para_data(data)
    return dt.strftime("%d/%m/%Y") if dt else "-"


def obter_cor_status(status):
    return {
        "verde": "#00CC00",
        "amarelo": "#FFCC00",
        "vermelho": "#FF0000",
        "pago": "#0099FF",
        "nao_pagar": "#CCCCCC",
        "pendente": "#999999",
    }.get(status, "#CCCCCC")


def criar_emoji_status(status):
    return {
        "verde": "✅",
        "amarelo": "⚠️",
        "vermelho": "❌",
        "pago": "💰",
        "nao_pagar": "⛔",
        "pendente": "⏳",
    }.get(status, "❓")
