from io import BytesIO

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

import database as db
import utils


def _pdf_bytes_from_text(title, lines):
    buf = BytesIO()
    largura, altura = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, altura - 40, title)
    c.setFont("Helvetica", 9)
    y = altura - 70
    for line in lines:
        texto = "" if line is None else str(line)
        # Quebra linhas longas em vez de cortar a informação.
        partes = [texto[i:i + 120] for i in range(0, len(texto), 120)] or [""]
        for parte in partes:
            c.drawString(40, y, parte)
            y -= 14
            if y < 40:
                c.showPage()
                c.setFont("Helvetica", 9)
                y = altura - 40
    c.save()
    buf.seek(0)
    return buf.read()


def _texto(valor, padrao="-"):
    valor = db._valor_limpo(valor)
    return padrao if valor is None else str(valor)


def _mapa(df_patentes, mapa_anuidades):
    if mapa_anuidades is not None:
        return mapa_anuidades
    return db.obter_anuidades_lote(df_patentes)


def _vazio(df_patentes):
    return df_patentes is None or not hasattr(df_patentes, "empty") or df_patentes.empty


def gerar_relatorio_completo(df_patentes):
    if _vazio(df_patentes):
        return _pdf_bytes_from_text("Relatório Completo de Propriedade Intelectual", ["Nenhuma PI cadastrada."])

    lines = []
    for _, r in df_patentes.iterrows():
        modalidade = db.normalizar_modalidade(r.get("modalidade_pi"))
        lines.append(
            f"[{modalidade}] {_texto(r.get('numero_patente'))} - {_texto(r.get('titulo'))} - "
            f"Gestor: {_texto(r.get('gestor'), 'IFSC')} - Status: {_texto(r.get('status'))}"
        )
    return _pdf_bytes_from_text("Relatório Completo de Propriedade Intelectual", lines)


def gerar_relatorio_anuidades(df_patentes, mapa_anuidades=None):
    if _vazio(df_patentes):
        return _pdf_bytes_from_text("Relatório de Pagamentos e Prazos", ["Nenhuma PI cadastrada."])

    mapa = _mapa(df_patentes, mapa_anuidades)
    lines = []
    for _, r in df_patentes.iterrows():
        modalidade = db.normalizar_modalidade(r.get("modalidade_pi"))
        pagamentos = mapa.get(db.chave_pi(r.get("id")), pd.DataFrame())
        for _, pgto in pagamentos.iterrows():
            descricao = _texto(pgto.get("descricao_pagamento"), _texto(pgto.get("numero_anuidade")))
            lines.append(
                f"{_texto(r.get('numero_patente'))} ({modalidade}) - {descricao} - "
                f"fim ordinário: {utils.formatar_data(pgto.get('data_fim_ordinario'))} - "
                f"status: {_texto(pgto.get('status'))}"
            )

    if not lines:
        lines.append("Nenhum pagamento encontrado.")

    avisos = db.avisos_anuidades(mapa)
    if avisos:
        lines += ["", "ATENÇÃO: cronogramas exibidos apenas calculados (não gravados no banco)."]

    return _pdf_bytes_from_text("Relatório de Pagamentos e Prazos", lines)


def gerar_relatorio_alertas(df_patentes, mapa_anuidades=None):
    if _vazio(df_patentes):
        return _pdf_bytes_from_text("Relatório de Alertas", ["Nenhuma PI cadastrada."])

    mapa = _mapa(df_patentes, mapa_anuidades)
    lines = []
    for _, r in df_patentes.iterrows():
        modalidade = db.normalizar_modalidade(r.get("modalidade_pi"))
        pagamentos = mapa.get(db.chave_pi(r.get("id")), pd.DataFrame())
        for _, pgto in pagamentos.iterrows():
            if pgto.get("status") == "nao_pagar":
                continue
            status = utils.calcular_status_anuidade(
                pgto.get("data_inicio_ordinario"),
                pgto.get("data_fim_ordinario"),
                pgto.get("data_inicio_extraordinario"),
                pgto.get("data_fim_extraordinario"),
                db._valor_limpo(pgto.get("data_pagamento")),
            )
            if status in ("amarelo", "vermelho"):
                descricao = _texto(pgto.get("descricao_pagamento"), _texto(pgto.get("numero_anuidade")))
                lines.append(f"{_texto(r.get('numero_patente'))} ({modalidade}) - {descricao} - {status.upper()}")

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
    return df.to_csv(index=False).encode("utf-8-sig")
