# formict_report.py
"""
Módulo FORMICT – Relatórios de Propriedade Intelectual do IFSC.

Substitui o módulo de Análise IA e incorpora:
- filtros por ano-base/modalidade/status;
- alertas urgentes de anuidades;
- exportação Excel;
- exportação PDF;
- atualização de campos FORMICT no Supabase;
- consolidação de inventores, CPFs e cotitulares.

Requer:
    pandas
    openpyxl
    reportlab
"""

import io
import json
import re
from datetime import date

import pandas as pd
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
import database as db


def _txt(v):
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def _date(v):
    if not _txt(v):
        return None
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def _money(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _money_br(v):
    return f"R$ {_money(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cpf_list(pi):
    raw = pi.get("inventores_cpf")
    if not raw:
        # fallback: nomes armazenados no campo antigo
        return [{"nome": x.strip(), "cpf": ""} for x in re.split(r"\s*[/;]\s*", _txt(pi.get("inventores"))) if x.strip()]
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return [{"nome": _txt(pi.get("inventores")), "cpf": ""}]


def _cotitulares(pi):
    return _txt(pi.get("cotitulares"))


def preparar_formict(df, ano_base=None, modalidade="Todas", status="Todos"):
    if df is None or df.empty:
        return pd.DataFrame()

    out = df.copy()

    if ano_base is not None:
        col = "formict_ano_base"
        if col in out.columns:
            out = out[
                pd.to_numeric(out[col], errors="coerce").fillna(-1).astype(int)
                == int(ano_base)
            ]
        else:
            # fallback para ano da data de depósito/registro
            base = out.get("data_registro", out.get("data_deposito"))
            anos = pd.to_datetime(base, errors="coerce").dt.year
            out = out[anos == int(ano_base)]

    if modalidade != "Todas" and "modalidade_pi" in out.columns:
        out = out[
            out["modalidade_pi"].fillna("").astype(str).str.lower()
            == modalidade.lower()
        ]

    if status != "Todos" and "status" in out.columns:
        out = out[
            out["status"].fillna("").astype(str).str.lower()
            == status.lower()
        ]

    return out


def _linhas_exportacao(df):
    linhas = []
    for _, pi in df.iterrows():
        invs = _cpf_list(pi)
        linhas.append({
            "ID": pi.get("id"),
            "Número do Processo": _txt(pi.get("numero_patente")),
            "Título": _txt(pi.get("titulo")),
            "Modalidade": _txt(pi.get("modalidade_pi")),
            "Status": _txt(pi.get("status")),
            "Data do Depósito": _txt(pi.get("data_deposito")),
            "Data do Registro FORMICT": _txt(pi.get("data_registro")),
            "Ano-base FORMICT": pi.get("formict_ano_base"),
            "Custo de Registro": _money(pi.get("custo_registro")),
            "Custo Manutenção Ano-base": _money(pi.get("custo_manutencao_ano_base")),
            "Data Manutenção": _txt(pi.get("data_manutencao")),
            "TRL": _txt(pi.get("trl")),
            "Sigilo": _txt(pi.get("sigilo")),
            "Cotitularidade": _txt(pi.get("cotitularidade")),
            "Cotitulares": _cotitulares(pi),
            "Inventores": "; ".join(_txt(x.get("nome")) for x in invs),
            "CPF dos Inventores": "; ".join(
                f"{_txt(x.get('nome'))}: {_txt(x.get('cpf'))}" for x in invs
            ),
            "Gestor": _txt(pi.get("gestor")),
            "Campus": _txt(pi.get("campus")),
            "Titular": _txt(pi.get("titular")),
            "IPC/Classificação": _txt(pi.get("ipc_classificacao")),
            "CNAE - Seção": _txt(pi.get("cnae_secao")),
            "CNAE - Subclassificação": _txt(pi.get("cnae_subclassificacao")),
            "Território": _txt(pi.get("territorio")),
            "Observações": _txt(pi.get("observacoes_formict")),
        })
    return pd.DataFrame(linhas)


def exportar_excel(df):
    dados = _linhas_exportacao(df)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dados.to_excel(writer, index=False, sheet_name="FORMICT")
        # Aba normalizada de inventores
        inv_rows = []
        for _, pi in df.iterrows():
            for ordem, inv in enumerate(_cpf_list(pi), 1):
                inv_rows.append({
                    "Processo": _txt(pi.get("numero_patente")),
                    "Título": _txt(pi.get("titulo")),
                    "Ordem": ordem,
                    "Inventor": _txt(inv.get("nome")),
                    "CPF": _txt(inv.get("cpf")),
                })
        pd.DataFrame(inv_rows).to_excel(
            writer, index=False, sheet_name="Inventores"
        )
    output.seek(0)
    return output.getvalue()


def exportar_pdf(df, ano_base=None):
    dados = _linhas_exportacao(df)
    output = io.BytesIO()

    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=22,
        leftMargin=22,
        topMargin=22,
        bottomMargin=22,
    )
    styles = getSampleStyleSheet()
    titulo = ParagraphStyle(
        "TituloFORMICT",
        parent=styles["Title"],
        alignment=TA_CENTER,
        fontSize=16,
        leading=19,
    )
    pequeno = ParagraphStyle(
        "Pequeno",
        parent=styles["BodyText"],
        fontSize=7,
        leading=9,
    )

    story = [
        Paragraph(
            f"FORMICT – PROPRIEDADE INTELECTUAL – IFSC"
            + (f" – ANO-BASE {ano_base}" if ano_base else ""),
            titulo,
        ),
        Spacer(1, 10),
        Paragraph(
            f"Quantidade de ativos no relatório: {len(dados)}",
            styles["Normal"],
        ),
        Spacer(1, 8),
    ]

    if dados.empty:
        story.append(Paragraph("Nenhum registro encontrado.", styles["Normal"]))
    else:
        cols = [
            "Número do Processo", "Título", "Modalidade", "Status",
            "Data do Registro FORMICT", "Custo de Registro",
            "Custo Manutenção Ano-base", "Data Manutenção", "TRL",
            "Inventores", "CPF dos Inventores", "Cotitulares",
        ]
        header = [Paragraph(f"<b>{c}</b>", pequeno) for c in cols]
        table_data = [header]
        for _, row in dados.iterrows():
            vals = []
            for c in cols:
                v = row.get(c, "")
                if c.startswith("Custo"):
                    v = _money_br(v)
                vals.append(Paragraph(_txt(v).replace("&", "&amp;"), pequeno))
            table_data.append(vals)

        table = Table(
            table_data,
            repeatRows=1,
            colWidths=[75, 155, 65, 65, 65, 60, 75, 65, 40, 125, 125, 150],
        )
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)

    doc.build(story)
    output.seek(0)
    return output.getvalue()


def _alertas_anuidades(df):
    alertas = []
    hoje = date.today()

    if df is None or df.empty:
        return alertas

    for _, pi in df.iterrows():
        try:
            anu = db.obter_anuidades(pi.get("id"))
        except Exception:
            continue

        if anu is None or anu.empty:
            continue

        for _, a in anu.iterrows():
            if _txt(a.get("status")).lower() == "nao_pagar":
                continue
            if _txt(a.get("data_pagamento")):
                continue

            fim = _date(a.get("data_fim_ordinario"))
            if not fim:
                continue

            dias = (fim - hoje).days
            if dias < 0:
                nivel = "VENCIDO"
            elif dias <= 30:
                nivel = "URGENTE"
            elif dias <= 60:
                nivel = "ATENÇÃO"
            else:
                continue

            alertas.append({
                "Nível": nivel,
                "Processo": _txt(pi.get("numero_patente")),
                "Título": _txt(pi.get("titulo")),
                "Anuidade": a.get("numero_anuidade"),
                "Vencimento": fim.strftime("%d/%m/%Y"),
                "Dias restantes": dias,
            })

    return sorted(alertas, key=lambda x: x["Dias restantes"])


def render():
    st.title("📑 Relatórios FORMICT")
    st.caption(
        "Consolidação dos ativos de Propriedade Intelectual para apoiar o "
        "preenchimento do FORMICT/SisICT, com exportação Excel e PDF."
    )

    df = db.obter_patentes()

    if df is None or df.empty:
        st.info("Nenhuma PI cadastrada.")
        return

    anos = []
    if "formict_ano_base" in df.columns:
        anos = sorted(
            pd.to_numeric(df["formict_ano_base"], errors="coerce")
            .dropna().astype(int).unique().tolist()
        )
    if not anos:
        anos = sorted(
            pd.to_datetime(df.get("data_registro", df["data_deposito"]),
                           errors="coerce").dt.year.dropna().astype(int).unique().tolist()
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        ano_base = st.selectbox("Ano-base", ["Todos"] + anos)
    with col2:
        modalidades = ["Todas"]
        if "modalidade_pi" in df.columns:
            modalidades += sorted(
                x for x in df["modalidade_pi"].dropna().astype(str).unique()
                if x
            )
        modalidade = st.selectbox("Modalidade", modalidades)
    with col3:
        statuses = ["Todos"]
        if "status" in df.columns:
            statuses += sorted(
                x for x in df["status"].dropna().astype(str).unique()
                if x
            )
        status = st.selectbox("Status", statuses)

    ano_filtro = None if ano_base == "Todos" else int(ano_base)
    rel = preparar_formict(df, ano_filtro, modalidade, status)

    st.divider()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Ativos no filtro", len(rel))
    m2.metric(
        "Custo de registro",
        _money_br(rel["custo_registro"].sum()) if "custo_registro" in rel else "R$ 0,00",
    )
    m3.metric(
        "Manutenção ano-base",
        _money_br(rel["custo_manutencao_ano_base"].sum())
        if "custo_manutencao_ano_base" in rel else "R$ 0,00",
    )
    m4.metric(
        "Com TRL informado",
        int(rel["trl"].fillna("").astype(str).str.strip().ne("").sum())
        if "trl" in rel else 0,
    )

    st.subheader("📋 Ativos do FORMICT")
    tabela = _linhas_exportacao(rel)
    st.dataframe(tabela, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🚨 Alertas urgentes de manutenção")
    alertas = _alertas_anuidades(rel)
    if alertas:
        st.dataframe(pd.DataFrame(alertas), use_container_width=True, hide_index=True)
    else:
        st.success("Nenhum alerta de anuidade vencida ou nos próximos 30 dias.")

    st.divider()
    b1, b2 = st.columns(2)
    with b1:
        st.download_button(
            "📊 Baixar Excel FORMICT",
            exportar_excel(rel),
            "relatorio_formict.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with b2:
        st.download_button(
            "📄 Baixar PDF FORMICT",
            exportar_pdf(rel, ano_filtro),
            "relatorio_formict.pdf",
            "application/pdf",
            use_container_width=True,
        )
