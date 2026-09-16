import streamlit as st
import pandas as pd
from datetime import datetime

import ai_analyzer
import database as db
import report_generator
import utils


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Gestão de PI do IFSC",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CONEXÃO COM BANCO
# ============================================================

try:
    db.init_database()
except Exception as exc:
    st.error(f"Não foi possível conectar ao Supabase: {exc}")
    st.stop()


# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def ano_clean(valor):
    """Retorna o ano como inteiro de forma segura, evitando erros com NaN/None."""
    if valor is None or pd.isna(valor) or str(valor).strip() == "":
        return datetime.now().year
    try:
        return int(float(valor))
    except (ValueError, TypeError):
        return datetime.now().year

def status_pagamento(row):
    if row.get("status") == "nao_pagar":
        return "nao_pagar"

    return utils.calcular_status_anuidade(
        row.get("data_inicio_ordinario"),
        row.get("data_fim_ordinario"),
        row.get("data_inicio_extraordinario"),
        row.get("data_fim_extraordinario"),
        row.get("data_pagamento"),
    )


def label_pagamento(modalidade):
    if modalidade == "Software":
        return "Taxa"

    if modalidade == "Desenho Industrial":
        return "Pagamento"

    return "Anuidade"


def montar_linhas_dashboard(df_pis, modalidade):
    hoje = datetime.now().date()
    linhas = []

    for _, pi in df_pis.iterrows():

        pagamentos = db.obter_anuidades(pi["id"])

        for _, pgto in pagamentos.iterrows():

            if pgto.get("status") == "nao_pagar":
                continue

            if pgto.get("data_pagamento"):
                continue

            inicio_ord = utils._para_data(
                pgto.get("data_inicio_ordinario")
            )

            fim_ord = utils._para_data(
                pgto.get("data_fim_ordinario")
            )

            if not inicio_ord or not fim_ord:
                continue

            if not (inicio_ord <= hoje <= fim_ord):
                continue

            dias = (fim_ord - hoje).days

            status = "amarelo" if dias <= 30 else "verde"

            linhas.append({
                "ID": pi.get("id_externo") or pi["id"],
                "Processo": pi["numero_patente"],
                "Título": pi.get("titulo") or "-",
                label_pagamento(modalidade):
                    pgto.get("descricao_pagamento")
                    or pgto.get("numero_anuidade"),
                "Fim Prazo Ordinário":
                    utils.formatar_data(
                        pgto.get("data_fim_ordinario")
                    ),
                "Dias p/ Vencer": dias,
                "Status":
                    f"{utils.criar_emoji_status(status)} "
                    f"{status.upper()}",
                "Gestor": pi.get("gestor") or "N/A",
                "Campus": pi.get("campus") or "-",
            })

    return linhas


def dashboard_modalidade(titulo, modalidade):

    st.title(titulo)

    df = db.obter_patentes()

    if df.empty:
        st.info("Nenhuma PI cadastrada ainda.")
        return

    df_tipo = df[
        df["modalidade_pi"]
        .apply(db.normalizar_modalidade)
        == modalidade
    ].copy()

    linhas = montar_linhas_dashboard(
        df_tipo,
        modalidade
    )

    df_dash = pd.DataFrame(linhas)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "📚 Total",
            len(df_tipo)
        )

    with col2:
        st.metric(
            "📅 Em prazo ordinário",
            len(df_dash)
        )

    with col3:
        st.metric(
            "✅ Normal",
            0
            if df_dash.empty
            else int(
                df_dash["Status"]
                .str.contains("✅")
                .sum()
            )
        )

    with col4:
        st.metric(
            "⚠️ Atenção",
            0
            if df_dash.empty
            else int(
                df_dash["Status"]
                .str.contains("⚠️")
                .sum()
            )
        )

    st.divider()

    subtitulo = {
        "Patente":
            "Anuidades de patentes em prazo ordinário",

        "Desenho Industrial":
            "Depósito e quinquênios de desenhos industriais em prazo ordinário",

        "Software":
            "Taxas únicas de software em prazo ordinário",
    }[modalidade]

    st.subheader(subtitulo)

    if df_dash.empty:
        st.info(
            "Nenhum pagamento desta modalidade "
            "está em prazo ordinário neste momento."
        )
        return

    def colorir(row):

        if "⚠️" in str(row["Status"]):
            return [
                "background-color: #ffffcc"
            ] * len(row)

        return [
            "background-color: #ccffcc"
        ] * len(row)

    st.dataframe(
        df_dash
        .sort_values("Dias p/ Vencer")
        .style
        .apply(colorir, axis=1),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# ESTILO
# ============================================================

st.markdown(
    """
    <style>
        .title-ifsc {
            text-align: center;
            color: #003366;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<h1 class="title-ifsc">'
    '🏛️ Gestão de Propriedade Intelectual do IFSC'
    '</h1>',
    unsafe_allow_html=True,
)

st.markdown(
    '<p style="text-align: center; color: #666;">'
    'Patentes, Desenhos Industriais e Softwares'
    '</p>',
    unsafe_allow_html=True,
)

st.divider()


# ============================================================
# MENU
# ============================================================

st.sidebar.title("⚙️ Navegação")

pagina = st.sidebar.radio(
    "Selecione uma página:",
    [
        "📊 Dashboard Patentes",
        "🎨 Dashboard Desenhos Industriais",
        "💻 Dashboard Softwares",
        "➕ Adicionar PI",
        "📁 Gerenciar PIs",
        "📤 Importar Excel",
        "🤖 Análise IA",
        "📄 Gerar Relatórios",
    ],
)


# ============================================================
# DASHBOARD PATENTES
# ============================================================

if pagina == "📊 Dashboard Patentes":

    dashboard_modalidade(
        "📊 Dashboard de Patentes",
        "Patente"
    )


# ============================================================
# DASHBOARD DESENHOS INDUSTRIAIS
# ============================================================

elif pagina == "🎨 Dashboard Desenhos Industriais":

    dashboard_modalidade(
        "🎨 Dashboard de Desenhos Industriais",
        "Desenho Industrial"
    )


# ============================================================
# DASHBOARD SOFTWARES
# ============================================================

elif pagina == "💻 Dashboard Softwares":

    dashboard_modalidade(
        "💻 Dashboard de Softwares",
        "Software"
    )


# ============================================================
# ADICIONAR PI
# ============================================================

elif pagina == "➕ Adicionar PI":

    st.title(
        "➕ Adicionar Propriedade Intelectual"
    )

    with st.form("form_nova_pi"):

        tab1, tab2, tab3 = st.tabs(
            [
                "📌 Informações Básicas",
                "⚖️ Documentos e Atribuições",
                "📅 Prazos e Datas",
            ]
        )

        # ----------------------------------------------------
        # ABA 1
        # ----------------------------------------------------

        with tab1:

            col1, col2 = st.columns(2)

            with col1:

                id_externo = st.text_input(
                    "ID do Sistema (opcional)"
                )

                numero_patente = st.text_input(
                    "Número do Processo (obrigatório)"
                )

                titulo = st.text_input(
                    "Título"
                )

                gestor = st.text_input(
                    "Gestor",
                    value="IFSC"
                )

            with col2:

                modalidade = st.selectbox(
                    "Modalidade de PI",
                    [
                        "Patente",
                        "Desenho Industrial",
                        "Software",
                    ],
                )

                status_patente = st.selectbox(
                    "Status do Pedido",
                    [
                        "Ativo",
                        "Patente Concedida",
                        "Tramitando Normal",
                        "Indeferimento",
                        "Recurso contra indeferimento",
                        "Pedido de exame",
                        "Arquivado",
                        "Desistência",
                    ],
                )

                titular = st.text_input(
                    "Depositante / Titular"
                )

                inventores = st.text_area(
                    "Nome dos Inventores"
                )

                campus = st.text_input(
                    "Campus"
                )

        # ----------------------------------------------------
        # ABA 2
        # ----------------------------------------------------

        with tab2:

            col3, col4 = st.columns(2)

            with col3:

                ipc_classificacao = st.text_input(
                    "IPC / Classificação"
                )

                acordo_titularidade = st.text_input(
                    "Acordo de Titularidade"
                )

                procuracao = st.text_input(
                    "Procuração"
                )

            with col4:

                termo_cessao = st.text_input(
                    "Termo de Cessão"
                )

                atributos = st.text_area(
                    "Atributos Complementares"
                )

        # ----------------------------------------------------
        # ABA 3
        # ----------------------------------------------------

        with tab3:

            col5, col6 = st.columns(2)

            with col5:

                data_deposito = st.date_input(
                    "Data do Depósito (obrigatório)"
                )

                ano = st.number_input(
                    "Ano do Depósito",
                    min_value=1990,
                    max_value=2100,
                    value=datetime.now().year,
                )

                data_publicacao = st.date_input(
                    "Data da Publicação",
                    value=None,
                )

            with col6:

                data_concessao = st.date_input(
                    "Data da Concessão",
                    value=None,
                )

                data_exame = st.date_input(
                    "Data do Exame",
                    value=None,
                )

        descricao = st.text_area(
            "Resumo / Descrição"
        )

        enviar = st.form_submit_button(
            "✅ Cadastrar PI",
            use_container_width=True,
            type="primary",
        )

        if enviar:

            if not numero_patente or not data_deposito:

                st.error(
                    "Preencha o número do processo "
                    "e a data do depósito."
                )

            else:

                ok, msg = db.adicionar_patente(
                    numero=numero_patente,
                    data_dep=data_deposito.strftime(
                        "%Y-%m-%d"
                    ),
                    data_conc=(
                        data_concessao.strftime("%Y-%m-%d")
                        if data_concessao
                        else None
                    ),
                    descricao=descricao,
                    titular=titular,
                    gestor=gestor,
                    status_patente=status_patente,
                    titulo=titulo,
                    inventores=inventores,
                    campus=campus,
                    atributos=atributos,
                    id_externo=id_externo,
                    modalidade_pi=modalidade,
                    ano=int(ano) if ano else None,
                    data_publicacao=(
                        data_publicacao.strftime("%Y-%m-%d")
                        if data_publicacao
                        else None
                    ),
                    data_exame=(
                        data_exame.strftime("%Y-%m-%d")
                        if data_exame
                        else None
                    ),
                    acordo_titularidade=
                        acordo_titularidade,
                    procuracao=procuracao,
                    termo_cessao=termo_cessao,
                    ipc_classificacao=
                        ipc_classificacao,
                )

                if ok:
                    st.success(msg)
                else:
                    st.error(msg)


# ============================================================
# GERENCIAR PIs
# ============================================================

elif pagina == "📁 Gerenciar PIs":

    st.title(
        "📁 Gerenciar Propriedades Intelectuais"
    )

    df = db.obter_patentes()

    if df.empty:

        st.info(
            "Nenhuma PI cadastrada."
        )

    else:

        filtro_tipo = st.selectbox(
            "Filtrar modalidade:",
            [
                "Todas",
                "Patente",
                "Desenho Industrial",
                "Software",
            ],
        )

        busca = st.text_input(
            "🔍 Filtrar por processo, título, "
            "inventor, gestor, campus ou classificação:"
        )

        df_filtrado = df.copy()

        if filtro_tipo != "Todas":

            df_filtrado = df_filtrado[
                df_filtrado["modalidade_pi"]
                .apply(db.normalizar_modalidade)
                == filtro_tipo
            ]

        if busca:

            termo = busca.lower()

            mascara = pd.Series(
                False,
                index=df_filtrado.index
            )

            for coluna in [
                "numero_patente",
                "titulo",
                "inventores",
                "gestor",
                "campus",
                "ipc_classificacao",
                "id_externo",
            ]:

                if coluna in df_filtrado:

                    mascara = (
                        mascara
                        |
                        df_filtrado[coluna]
                        .fillna("")
                        .astype(str)
                        .str.lower()
                        .str.contains(
                            termo,
                            regex=False
                        )
                    )

            df_filtrado = df_filtrado[mascara]

        if df_filtrado.empty:

            st.warning(
                "Nenhuma PI correspondente "
                "aos filtros aplicados."
            )

            st.stop()

        opcoes = {
            f"{row['numero_patente']} - "
            f"{row.get('titulo') or 'Sem título'}":
                row["id"]

            for _, row in df_filtrado.iterrows()
        }

        escolha = st.selectbox(
            "Selecione uma PI para detalhar:",
            list(opcoes.keys())
        )

        pi_id = opcoes[escolha]

        pi = df[
            df["id"] == pi_id
        ].iloc[0]

        modalidade = db.normalizar_modalidade(
            pi.get("modalidade_pi")
        )

        st.subheader(
            "📋 Detalhes da PI"
        )

        col1, col2, col3, col4 = st.columns(4)

        with col1:

            st.metric(
                "🔑 ID",
                pi.get("id_externo") or "N/A"
            )

            st.metric(
                "🏛️ Processo",
                pi["numero_patente"]
            )

        with col2:

            st.metric(
                "📅 Depósito",
                utils.formatar_data(
                    pi["data_deposito"]
                )
            )

            st.metric(
                "📅 Concessão",
                utils.formatar_data(
                    pi["data_concessao"]
                )
            )

        with col3:

            st.metric(
                "🔬 Modalidade",
                modalidade
            )

            st.metric(
                "🎯 Status",
                pi.get("status") or "Ativo"
            )

        with col4:

            st.metric(
                "👤 Titular",
                pi.get("titular") or "N/A"
            )

            st.metric(
                "🏫 Campus",
                pi.get("campus") or "N/A"
            )

        if pi.get("descricao"):

            st.info(
                f"**Resumo / Descrição:**\n"
                f"{pi['descricao']}"
            )

        # ----------------------------------------------------
        # EDITAR PI
        # ----------------------------------------------------

        with st.expander(
            "✏️ Editar dados desta PI"
        ):

            with st.form(
                f"form_editar_{pi_id}"
            ):

                col_a, col_b = st.columns(2)

                with col_a:

                    edit_id_externo = st.text_input(
                        "ID Externo",
                        value=text_clean(
                            pi.get("id_externo")
                        ),
                    )

                    edit_numero = st.text_input(
                        "Número do Processo",
                        value=text_clean(
                            pi.get("numero_patente")
                        ),
                    )

                    edit_titulo = st.text_input(
                        "Título",
                        value=text_clean(
                            pi.get("titulo")
                        ),
                    )

                    edit_modalidade = st.selectbox(
                        "Modalidade de PI",
                        [
                            "Patente",
                            "Desenho Industrial",
                            "Software",
                        ],
                        index=[
                            "Patente",
                            "Desenho Industrial",
                            "Software",
                        ].index(modalidade),
                    )

                    edit_data_dep = st.date_input(
                        "Data do Depósito",
                        value=utils._para_data(
                            pi.get("data_deposito")
                        ),
                    )

                    edit_data_conc = st.date_input(
                        "Data de Concessão",
                        value=utils._para_data(
                            pi.get("data_concessao")
                        ),
                    )

                    edit_ano = st.number_input(
                        "Ano",
                        value=(
                            int(pi.get("ano"))
                            if pi.get("ano")
                            else datetime.now().year
                        ),
                    )

                with col_b:

                    edit_titular = st.text_area(
                        "Depositante / Titular",
                        value=text_clean(
                            pi.get("titular")
                        ),
                        height=80,
                    )

                    edit_inventores = st.text_area(
                        "Inventores",
                        value=text_clean(
                            pi.get("inventores")
                        ),
                        height=80,
                    )

                    edit_gestor = st.text_input(
                        "Gestor",
                        value=text_clean(
                            pi.get("gestor")
                        ),
                    )

                    edit_status = st.text_input(
                        "Status",
                        value=text_clean(
                            pi.get("status")
                        ),
                    )

                    edit_campus = st.text_input(
                        "Campus",
                        value=text_clean(
                            pi.get("campus")
                        ),
                    )

                    edit_ipc = st.text_input(
                        "IPC / Classificação",
                        value=text_clean(
                            pi.get("ipc_classificacao")
                        ),
                    )

                edit_descricao = st.text_area(
                    "Resumo / Descrição",
                    value=text_clean(
                        pi.get("descricao")
                    ),
                    height=120,
                )

                salvar = st.form_submit_button(
                    "💾 Salvar alterações",
                    use_container_width=True,
                    type="primary",
                )

                if salvar:

                    ok, msg = db.atualizar_patente(
                        patente_id=pi_id,
                        numero=edit_numero,
                        data_dep=(
                            edit_data_dep.strftime(
                                "%Y-%m-%d"
                            )
                            if edit_data_dep
                            else None
                        ),
                        data_conc=(
                            edit_data_conc.strftime(
                                "%Y-%m-%d"
                            )
                            if edit_data_conc
                            else None
                        ),
                        descricao=edit_descricao,
                        titular=edit_titular,
                        gestor=edit_gestor,
                        status_patente=edit_status,
                        titulo=edit_titulo,
                        inventores=edit_inventores,
                        campus=edit_campus,
                        atributos=pi.get(
                            "atributos"
                        ),
                        id_externo=edit_id_externo,
                        modalidade_pi=edit_modalidade,
                        ano=(
                            int(edit_ano)
                            if edit_ano
                            else None
                        ),
                        data_publicacao=pi.get(
                            "data_publicacao"
                        ),
                        data_exame=pi.get(
                            "data_exame"
                        ),
                        acordo_titularidade=pi.get(
                            "acordo_titularidade"
                        ),
                        procuracao=pi.get(
                            "procuracao"
                        ),
                        termo_cessao=pi.get(
                            "termo_cessao"
                        ),
                        ipc_classificacao=edit_ipc,
                    )

                    if ok:

                        st.success(msg)
                        st.rerun()

                    else:

                        st.error(msg)

        # ----------------------------------------------------
        # PAGAMENTOS
        # ----------------------------------------------------

        st.divider()

        st.subheader(
            f"💰 Pagamentos - {modalidade}"
        )

        pagamentos = db.obter_anuidades(
            pi_id
        )

        if pagamentos.empty:

            st.warning(
                "Nenhum pagamento encontrado "
                "para esta PI."
            )

        else:

            linhas = []

            for _, pgto in pagamentos.iterrows():

                status = status_pagamento(
                    pgto
                )

                linhas.append({
                    "Pagamento":
                        pgto.get(
                            "descricao_pagamento"
                        )
                        or pgto["numero_anuidade"],

                    "Início Ordinário":
                        utils.formatar_data(
                            pgto[
                                "data_inicio_ordinario"
                            ]
                        ),

                    "Fim Ordinário":
                        utils.formatar_data(
                            pgto[
                                "data_fim_ordinario"
                            ]
                        ),

                    "Dias Restantes":
                        utils.obter_dias_restantes(
                            pgto[
                                "data_fim_ordinario"
                            ],
                            pgto.get(
                                "data_pagamento"
                            ),
                        ),

                    "Status":
                        f"{utils.criar_emoji_status(status)} "
                        f"{status.upper()}",

                    "Data Pagamento":
                        utils.formatar_data(
                            pgto.get(
                                "data_pagamento"
                            )
                        ),
                })

            st.dataframe(
                pd.DataFrame(linhas),
                use_container_width=True,
                hide_index=True,
            )

            col1, col2, col3, col4 = st.columns(4)

            with col1:

                opcoes_pagamento = {
                    f"{row['numero_anuidade']} - "
                    f"{row.get('descricao_pagamento') or label_pagamento(modalidade)}":
                        int(row["numero_anuidade"])

                    for _, row
                    in pagamentos.iterrows()
                }

                num_pagamento = st.selectbox(
                    "Selecione o pagamento",
                    list(opcoes_pagamento.keys())
                )

            with col2:

                data_pagamento = st.date_input(
                    "Data do Pagamento",
                    key="data_pag"
                )

            with col3:

                if st.button(
                    "✅ Registrar Pagamento",
                    use_container_width=True
                ):

                    try:

                        db.atualizar_status_anuidade(
                            pi_id,
                            opcoes_pagamento[
                                num_pagamento
                            ],
                            "pago",
                            data_pagamento.strftime(
                                "%Y-%m-%d"
                            ),
                        )

                        st.success(
                            "Pagamento registrado "
                            "com sucesso."
                        )

                        st.rerun()

                    except Exception as exc:

                        st.error(str(exc))

            with col4:

                if st.button(
                    "🚫 Marcar Não Pagar",
                    use_container_width=True
                ):

                    try:

                        db.atualizar_status_anuidade(
                            pi_id,
                            opcoes_pagamento[
                                num_pagamento
                            ],
                            "nao_pagar",
                        )

                        st.success(
                            "Pagamento marcado "
                            "como não pagar."
                        )

                        st.rerun()

                    except Exception as exc:

                        st.error(str(exc))

        # ----------------------------------------------------
        # DELETAR
        # ----------------------------------------------------

        st.divider()

        if st.button(
            "🗑️ Deletar PI",
            use_container_width=True,
            type="secondary",
        ):

            if st.checkbox(
                "Tenho certeza que desejo deletar "
                "esta PI definitivamente?"
            ):

                db.deletar_patente(
                    pi_id
                )

                st.success(
                    "PI deletada com sucesso."
                )

                st.rerun()


# ============================================================
# IMPORTAR EXCEL
# ============================================================

elif pagina == "📤 Importar Excel":

    st.title(
        "📥 Importar Ativos de PI via Planilha"
    )

    st.markdown(
        """
        Esta ferramenta permite importar múltiplas
        Propriedades Intelectuais diretamente de uma
        planilha Excel.

        **Tipos aceitos:**
        - Patente
        - Software
        - Desenho Industrial

        As obrigações financeiras serão geradas
        automaticamente pelo banco após a importação.
        """
    )

    arquivo_excel = st.file_uploader(
        "Selecione a planilha (.xls ou .xlsx)",
        type=["xls", "xlsx"],
        key="importacao_pi",
    )

    if arquivo_excel is not None:

        try:

            # ------------------------------------------------
            # LEITURA DA PLANILHA
            # ------------------------------------------------

            nome_arquivo = (
                arquivo_excel.name.lower()
            )

            if nome_arquivo.endswith(".xls"):

                df_excel = pd.read_excel(
                    arquivo_excel,
                    engine="xlrd",
                )

            else:

                df_excel = pd.read_excel(
                    arquivo_excel,
                    engine="openpyxl",
                )

            if df_excel.empty:

                st.warning(
                    "A planilha está vazia."
                )

                st.stop()

            st.success(
                f"Planilha carregada com sucesso: "
                f"{len(df_excel)} registro(s) encontrado(s)."
            )

            # ------------------------------------------------
            # PRÉ-VISUALIZAÇÃO
            # ------------------------------------------------

            st.subheader(
                "👀 Pré-visualização"
            )

            st.dataframe(
                df_excel.head(10),
                use_container_width=True,
                hide_index=True,
            )

            colunas = (
                df_excel.columns
                .tolist()
            )

            if not colunas:

                st.error(
                    "A planilha não possui colunas."
                )

                st.stop()

            # ------------------------------------------------
            # MAPEAMENTO
            # ------------------------------------------------

            st.divider()

            st.subheader(
                "🔗 Mapeamento das Colunas"
            )

            st.info(
                "Selecione qual coluna da sua planilha "
                "corresponde a cada campo do sistema."
            )

            def encontrar_coluna(
                possibilidades
            ):

                for coluna in colunas:

                    coluna_norm = (
                        str(coluna)
                        .strip()
                        .lower()
                        .replace("_", " ")
                    )

                    for termo in possibilidades:

                        if termo in coluna_norm:
                            return coluna

                return colunas[0]

            with st.expander(
                "⚙️ Configurar mapeamento das colunas",
                expanded=True,
            ):

                col1, col2 = st.columns(2)

                # --------------------------------------------
                # COLUNA ESQUERDA
                # --------------------------------------------

                with col1:

                    col_tipo = st.selectbox(
                        "Tipo de PI *",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                [
                                    "tipo pi",
                                    "tipo",
                                    "modalidade",
                                    "modalidade pi",
                                ]
                            )
                        ),
                    )

                    col_processo = st.selectbox(
                        "Número do Processo *",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                [
                                    "número do processo",
                                    "numero do processo",
                                    "numero processo",
                                    "numero patente",
                                    "processo",
                                ]
                            )
                        ),
                    )

                    col_titulo = st.selectbox(
                        "Título",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                [
                                    "título",
                                    "titulo",
                                ]
                            )
                        ),
                    )

                    col_deposito = st.selectbox(
                        "Data de Depósito *",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                [
                                    "data de depósito",
                                    "data de deposito",
                                    "depósito",
                                    "deposito",
                                ]
                            )
                        ),
                    )

                    col_linguagem = st.selectbox(
                        "Linguagem",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                [
                                    "linguagem",
                                    "linguagem do software",
                                ]
                            )
                        ),
                    )

                # --------------------------------------------
                # COLUNA DIREITA
                # --------------------------------------------

                with col2:

                    col_campus = st.selectbox(
                        "Campus",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                ["campus"]
                            )
                        ),
                    )

                    col_gestor = st.selectbox(
                        "Gestor",
                        colunas,
                        index=colunas.index(
                            ["gestor"]
                        )
                    )

                    col_status = st.selectbox(
                        "Status",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                ["status"]
                            )
                        ),
                    )

                    col_titular = st.selectbox(
                        "Titular / Depositante",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                [
                                    "titular",
                                    "depositante",
                                ]
                            )
                        ),
                    )

                    col_inventores = st.selectbox(
                        "Inventores",
                        colunas,
                        index=colunas.index(
                            encontrar_coluna(
                                [
                                    "inventores",
                                    "inventor",
                                ]
                            )
                        ),
                    )

            # ------------------------------------------------
            # BOTÃO DE IMPORTAÇÃO
            # ------------------------------------------------

            st.divider()

            if st.button(
                "📥 Confirmar e Processar Importação",
                type="primary",
                use_container_width=True,
            ):

                ativos_para_salvar = []
                erros_validacao = []

                with st.spinner(
                    "Validando e preparando os dados..."
                ):

                    for index, row in df_excel.iterrows():

                        linha_excel = index + 2

                        # ------------------------------------
                        # FUNÇÃO PARA LIMPAR VALORES
                        # ------------------------------------

                        def valor_limpo(coluna):

                            valor = row.get(
                                coluna
                            )

                            if pd.isna(valor):
                                return None

                            valor = str(
                                valor
                            ).strip()

                            if (
                                not valor
                                or valor.lower() == "nan"
                            ):
                                return None

                            return valor

                        # ------------------------------------
                        # TIPO
                        # ------------------------------------

                        tipo_original = valor_limpo(
                            col_tipo
                        )

                        if not tipo_original:

                            erros_validacao.append(
                                f"Linha {linha_excel}: "
                                "Tipo de PI não informado."
                            )

                            continue

                        tipo_normalizado = (
                            tipo_original
                            .strip()
                            .lower()
                            .replace("_", " ")
                        )

                        if "software" in tipo_normalizado:

                            tipo_pi = "Software"

                        elif "desenho" in tipo_normalizado:

                            tipo_pi = "Desenho Industrial"

                        elif "patente" in tipo_normalizado:

                            tipo_pi = "Patente"

                        else:

                            erros_validacao.append(
                                f"Linha {linha_excel}: "
                                f"Tipo de PI "
                                f"'{tipo_original}' inválido."
                            )

                            continue

                        # ------------------------------------
                        # PROCESSO
                        # ------------------------------------

                        numero_processo = valor_limpo(
                            col_processo
                        )

                        if not numero_processo:

                            erros_validacao.append(
                                f"Linha {linha_excel}: "
                                "Número do processo "
                                "não informado."
                            )

                            continue

                        # ------------------------------------
                        # DATA DE DEPÓSITO
                        # ------------------------------------

                        valor_data = row.get(
                            col_deposito
                        )

                        if pd.isna(valor_data):

                            erros_validacao.append(
                                f"Linha {linha_excel}: "
                                "Data de depósito "
                                "não informada."
                            )

                            continue

                        try:

                            data_deposito = (
                                pd.to_datetime(
                                    valor_data,
                                    dayfirst=True,
                                    errors="raise",
                                )
                                .strftime(
                                    "%Y-%m-%d"
                                )
                            )

                        except Exception:

                            erros_validacao.append(
                                f"Linha {linha_excel}: "
                                f"Data de depósito "
                                f"inválida: "
                                f"'{valor_data}'."
                            )

                            continue

                        # ------------------------------------
                        # LINGUAGEM
                        # ------------------------------------

                        linguagem = valor_limpo(
                            col_linguagem
                        )

                        if (
                            tipo_pi == "Software"
                            and not linguagem
                        ):

                            erros_validacao.append(
                                f"Linha {linha_excel}: "
                                "Para Software, a "
                                "Linguagem é obrigatória."
                            )

                            continue

                        # ------------------------------------
                        # DEMAIS CAMPOS
                        # ------------------------------------

                        titulo = valor_limpo(
                            col_titulo
                        )

                        campus = valor_limpo(
                            col_campus
                        )

                        gestor = valor_limpo(
                            col_gestor
                        )

                        titular = valor_limpo(
                            col_titular
                        )

                        inventores = valor_limpo(
                            col_inventores
                        )

                        status = valor_limpo(
                            col_status
                        )

                        if not status:
                            status = "Ativo"

                        # ------------------------------------
                        # REGISTRO
                        # ------------------------------------

                        ativo = {
                            "tipo_pi": tipo_pi,

                            "numero_processo":
                                numero_processo,

                            "titulo":
                                titulo,

                            "campus":
                                campus,

                            "status":
                                status,

                            "data_deposito":
                                data_deposito,

                            "gestor":
                                gestor,

                            "titular":
                                titular,

                            "inventores":
                                inventores,

                            "linguagem":
                                (
                                    linguagem
                                    if tipo_pi == "Software"
                                    else None
                                ),
                        }

                        ativos_para_salvar.append(
                            ativo
                        )

                # ==================================================
                # RESULTADO DA VALIDAÇÃO
                # ==================================================

                if erros_validacao:

                    st.error(
                        f"❌ Foram encontrados "
                        f"{len(erros_validacao)} "
                        f"problema(s)."
                    )

                    for erro in erros_validacao[:20]:

                        st.warning(
                            erro
                        )

                    if len(erros_validacao) > 20:

                        st.info(
                            f"... e mais "
                            f"{len(erros_validacao) - 20} "
                            f"problema(s)."
                        )

                elif not ativos_para_salvar:

                    st.warning(
                        "Nenhum registro válido "
                        "foi encontrado na planilha."
                    )

                else:

                    # ------------------------------------------
                    # PRÉVIA DOS REGISTROS
                    # ------------------------------------------

                    st.info(
                        f"📦 {len(ativos_para_salvar)} "
                        "registro(s) pronto(s) "
                        "para importação."
                    )

                    with st.expander(
                        "🔎 Conferir dados que serão importados"
                    ):

                        st.dataframe(
                            pd.DataFrame(
                                ativos_para_salvar
                            ),
                            use_container_width=True,
                            hide_index=True,
                        )

                    # ------------------------------------------
                    # ENVIA PARA SUPABASE
                    # ------------------------------------------

                    with st.spinner(
                        "Salvando dados no Supabase..."
                    ):

                        try:

                            # IMPORTANTE:
                            # importar_ativos_lote()
                            # retorna:
                            #
                            # (sucesso, mensagem)
                            #
                            # e NÃO um dicionário.

                            sucesso, mensagem = (
                                db.importar_ativos_lote(
                                    ativos_para_salvar
                                )
                            )

                            if sucesso:

                                st.success(
                                    mensagem
                                )

                                st.balloons()

                            else:

                                st.error(
                                    f"❌ Falha na importação: "
                                    f"{mensagem}"
                                )

                        except Exception as exc:

                            st.error(
                                f"❌ Erro ao importar dados: "
                                f"{exc}"
                            )

        except Exception as exc:

            st.error(
                f"❌ Erro ao ler a planilha: "
                f"{exc}"
            )


# ============================================================
# ANÁLISE IA
# ============================================================

elif pagina == "🤖 Análise IA":

    st.title(
        "🤖 Análise Inteligente de PI"
    )

    df = db.obter_patentes()

    pergunta = st.text_input(
        "Faça uma pergunta sobre suas PIs:"
    )

    if (
        st.button(
            "🔍 Analisar",
            use_container_width=True
        )
        and pergunta
    ):

        st.info(
            ai_analyzer.analisar_pergunta(
                df,
                pergunta
            )
        )

    col1, col2, col3 = st.columns(3)

    with col1:

        if st.button(
            "📈 Estatísticas Gerais",
            use_container_width=True
        ):

            st.markdown(
                ai_analyzer.gerar_estatisticas(
                    df
                )
            )

    with col2:

        if st.button(
            "🎯 PIs por Gestor",
            use_container_width=True
        ):

            st.markdown(
                ai_analyzer.patentes_por_gestor(
                    df
                )
            )

    with col3:

        if st.button(
            "⚠️ Alertas Urgentes",
            use_container_width=True
        ):

            st.markdown(
                ai_analyzer.gerar_alertas(
                    df
                )
            )


# ============================================================
# RELATÓRIOS
# ============================================================

elif pagina == "📄 Gerar Relatórios":

    st.title(
        "📄 Geração de Relatórios"
    )

    df = db.obter_patentes()

    col1, col2, col3 = st.columns(3)

    with col1:

        pdf = (
            report_generator
            .gerar_relatorio_completo(df)
        )

        st.download_button(
            "📥 Baixar Relatório Completo",
            pdf,
            "relatorio_completo.pdf",
            "application/pdf",
        )

    with col2:

        pdf = (
            report_generator
            .gerar_relatorio_anuidades(df)
        )

        st.download_button(
            "📥 Baixar Relatório de Pagamentos",
            pdf,
            "relatorio_pagamentos.pdf",
            "application/pdf",
        )

    with col3:

        pdf = (
            report_generator
            .gerar_relatorio_alertas(df)
        )

        st.download_button(
            "📥 Baixar Relatório de Alertas",
            pdf,
            "relatorio_alertas.pdf",
            "application/pdf",
        )

    st.divider()

    st.download_button(
        "📥 Exportar Excel",
        report_generator.exportar_para_excel(df),
        "propriedade_intelectual_export.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.download_button(
        "📥 Exportar CSV",
        report_generator.exportar_para_csv(df),
        "propriedade_intelectual_export.csv",
        "text/csv",
    )
