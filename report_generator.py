from io import BytesIO

import pandas as pd
from reportlab.pdfgen import canvas

import database as db
import utils


def _pdf_bytes_from_text(title, lines):
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, 800, title)
    c.setFont("Helvetica", 9)
    y = 770
    for line in lines:
        c.drawString(50, y, str(line)[:130])
        y -= 16
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 9)
            y = 800
    c.save()
    buf.seek(0)
    return buf.read()


def gerar_relatorio_completo(df_patentes):
    lines = []
    for _, r in df_patentes.iterrows():
        modalidade = db.normalizar_modalidade(r.get("modalidade_pi"))
        lines.append(f"[{modalidade}] {r.get('numero_patente')} - {r.get('titulo') or '-'} - Gestor: {r.get('gestor') or 'IFSC'}")
    return _pdf_bytes_from_text("Relatório Completo de Propriedade Intelectual", lines)


def gerar_relatorio_anuidades(df_patentes):
    lines = []
    for _, r in df_patentes.iterrows():
        modalidade = db.normalizar_modalidade(r.get("modalidade_pi"))
        for _, pgto in db.obter_anuidades(r["id"]).iterrows():
            descricao = pgto.get("descricao_pagamento") or pgto.get("numero_anuidade")
            lines.append(
                f"{r.get('numero_patente')} ({modalidade}) - {descricao} - "
                f"fim ordinário: {utils.formatar_data(pgto.get('data_fim_ordinario'))} - "
                f"status: {pgto.get('status')}"
            )
    return _pdf_bytes_from_text("Relatório de Pagamentos e Prazos", lines)


def gerar_relatorio_alertas(df_patentes):
    lines = []
    for _, r in df_patentes.iterrows():
        modalidade = db.normalizar_modalidade(r.get("modalidade_pi"))
        for _, pgto in db.obter_anuidades(r["id"]).iterrows():
            if pgto.get("status") == "nao_pagar":
                continue
            status = utils.calcular_status_anuidade(
                pgto.get("data_inicio_ordinario"),
                pgto.get("data_fim_ordinario"),
                pgto.get("data_inicio_extraordinario"),
                pgto.get("data_fim_extraordinario"),
                pgto.get("data_pagamento"),
            )
            if status in ("amarelo", "vermelho"):
                descricao = pgto.get("descricao_pagamento") or pgto.get("numero_anuidade")
                lines.append(f"{r.get('numero_patente')} ({modalidade}) - {descricao} - {status.upper()}")
    if not lines:
        lines.append("Nenhum alerta encontrado.")
    return _pdf_bytes_from_text("Relatório de Alertas", lines)


def exportar_para_excel(df_patentes):
    buf = BytesIO()
    df = df_patentes.copy() if hasattr(df_patentes, "copy") else pd.DataFrame(df_patentes)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="propriedade_intelectual")
    buf.seek(0)
    return buf.getvalue()


def exportar_para_csv(df_patentes):
    df = df_patentes.copy() if hasattr(df_patentes, "copy") else pd.DataFrame(df_patentes)
    return df.to_csv(index=False).encode("utf-8")
