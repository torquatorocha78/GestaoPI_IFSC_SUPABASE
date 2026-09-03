import pandas as pd

import database as db
import utils


def _modalidade(row):
    return db.normalizar_modalidade(row.get("modalidade_pi"))


def analisar_pergunta(df_patentes, pergunta):
    pergunta_lower = pergunta.lower()
    if df_patentes.empty:
        return "Não há propriedades intelectuais cadastradas."

    modalidades = df_patentes["modalidade_pi"].apply(db.normalizar_modalidade)

    if "software" in pergunta_lower or "programa" in pergunta_lower:
        total = int((modalidades == "Software").sum())
        return f"💻 **Softwares cadastrados:** {total}"

    if "desenho" in pergunta_lower or "industrial" in pergunta_lower:
        total = int((modalidades == "Desenho Industrial").sum())
        return f"🎨 **Desenhos Industriais cadastrados:** {total}"

    if "patente" in pergunta_lower:
        total = int((modalidades == "Patente").sum())
        return f"📊 **Patentes cadastradas:** {total}"

    if "vencida" in pergunta_lower or "vencido" in pergunta_lower or "atraso" in pergunta_lower:
        vencidos = 0
        for _, pi in df_patentes.iterrows():
            for _, pgto in db.obter_anuidades(pi["id"]).iterrows():
                if pgto.get("status") == "nao_pagar":
                    continue
                status = utils.calcular_status_anuidade(
                    pgto["data_inicio_ordinario"],
                    pgto["data_fim_ordinario"],
                    pgto["data_inicio_extraordinario"],
                    pgto["data_fim_extraordinario"],
                    pgto.get("data_pagamento"),
                )
                vencidos += 1 if status == "vermelho" else 0
        return f"🚨 **Pagamentos vencidos:** {vencidos}"

    if "quantas" in pergunta_lower or "total" in pergunta_lower or "ativos" in pergunta_lower:
        resumo = modalidades.value_counts()
        linhas = "\n".join(f"- **{tipo}:** {qtd}" for tipo, qtd in resumo.items())
        return f"📊 **Total geral:** {len(df_patentes)} registros.\n\n{linhas}"

    return "Posso analisar totais por patente, desenho industrial, software, gestor e pagamentos vencidos."


def gerar_estatisticas(df_patentes):
    if df_patentes.empty:
        return "Nenhuma PI cadastrada."
    modalidades = df_patentes["modalidade_pi"].apply(db.normalizar_modalidade)
    linhas = ["### 📊 Estatísticas Gerais de PI", f"**Total de PIs:** {len(df_patentes)}", ""]
    for tipo, qtd in modalidades.value_counts().items():
        linhas.append(f"- **{tipo}:** {qtd}")
    return "\n".join(linhas)


def patentes_por_gestor(df_patentes):
    if df_patentes.empty:
        return "Nenhuma PI cadastrada."
    gestores = df_patentes["gestor"].fillna("IFSC").replace("", "IFSC").str.upper().value_counts()
    linhas = ["### 🎯 PIs por Gestor", ""]
    for gestor, qtd in gestores.items():
        linhas.append(f"- **{gestor}:** {qtd}")
    return "\n".join(linhas)


def gerar_alertas(df_patentes):
    linhas = ["### ⚠️ Alertas de Pagamentos", ""]
    total = 0
    for _, pi in df_patentes.iterrows():
        modalidade = _modalidade(pi)
        pagamentos = db.obter_anuidades(pi["id"])
        for _, pgto in pagamentos.iterrows():
            if pgto.get("status") == "nao_pagar":
                continue
            status = utils.calcular_status_anuidade(
                pgto["data_inicio_ordinario"],
                pgto["data_fim_ordinario"],
                pgto["data_inicio_extraordinario"],
                pgto["data_fim_extraordinario"],
                pgto.get("data_pagamento"),
            )
            if status in ("vermelho", "amarelo"):
                dias = utils.obter_dias_restantes(pgto["data_fim_ordinario"], pgto.get("data_pagamento"))
                descricao = pgto.get("descricao_pagamento") or pgto.get("numero_anuidade")
                linhas.append(f"- **{pi['numero_patente']}** ({modalidade}) - {descricao}: {status.upper()} - {dias} dia(s)")
                total += 1
    if total == 0:
        linhas.append("✅ Nenhum alerta urgente.")
    return "\n".join(linhas)
