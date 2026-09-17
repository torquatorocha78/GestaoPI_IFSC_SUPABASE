import os
import tempfile
import hashlib
from typing import Any, Dict, List

import streamlit as st

import database as db

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.runnables import RunnableParallel, RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

os.environ["TOKENIZERS_PARALLELISM"] = "false"

MODEL_NAME = "openai/gpt-oss-20b"

# Modelo multilíngue: o anterior (msmarco-bert-base-dot-v5) é treinado só em inglês
# e usa produto escalar, o que piora a busca em documentos jurídicos em português.
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _get_groq_key() -> str:
    # Antes: se st.secrets existisse sem a chave, nunca caía para a variável de ambiente.
    chave = ""
    try:
        chave = str(st.secrets.get("GROQ_API_KEY", "") or "").strip()
    except Exception:
        chave = ""
    return chave or os.getenv("GROQ_API_KEY", "").strip()


@st.cache_resource(show_spinner=False)
def _carregar_embeddings():
    # Carrega o modelo uma única vez por servidor (antes recarregava a cada PDF).
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def _texto_limpo(valor: Any) -> str:
    valor = db._valor_limpo(valor)
    return "" if valor is None else str(valor)


def _indexar_pdf(pdf_bytes: bytes, chroma_dir: str):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        docs = PyPDFLoader(tmp_path).load()

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
        )
        chunks = splitter.split_documents(docs)
        if not chunks:
            raise ValueError(
                "Nenhum texto extraído do PDF (pode ser um PDF escaneado/imagem)."
            )

        return Chroma.from_documents(
            documents=chunks,
            embedding=_carregar_embeddings(),
            persist_directory=chroma_dir,
        )
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _formatar_docs(docs) -> str:
    partes = []
    for doc in docs:
        meta = doc.metadata or {}
        pagina = meta.get("page")
        pagina_texto = str(int(pagina) + 1) if isinstance(pagina, (int, float)) else "?"
        texto = doc.page_content.strip()
        partes.append(
            f"[Página {pagina_texto}]\n{texto[:1500]}"
        )
    return "\n\n".join(partes)


def _extrair_fontes(docs) -> List[Dict[str, Any]]:
    fontes = []
    vistas = set()

    for doc in docs:
        meta = doc.metadata or {}
        pagina = meta.get("page")
        pagina_texto = str(int(pagina) + 1) if isinstance(pagina, (int, float)) else "?"
        chave = pagina_texto

        if chave in vistas:
            continue

        vistas.add(chave)
        fontes.append({
            "pagina": pagina_texto,
            "fonte": "PDF enviado pelo usuário",
        })

    return fontes


def _texto_contexto_banco(df_pi, df_obrigacoes) -> str:
    partes = []

    if df_pi is not None and not df_pi.empty:
        row = df_pi.iloc[0].to_dict()

        # Campos da tabela patentes (a mesma usada no restante do app).
        campos = [
            "id", "id_externo", "modalidade_pi", "numero_patente", "titulo",
            "descricao", "titular", "gestor", "inventores", "campus", "status",
            "data_deposito", "data_concessao", "data_publicacao",
            "data_exame", "ano", "ipc_classificacao",
            "acordo_titularidade", "procuracao", "termo_cessao",
        ]

        linhas = []
        for campo in campos:
            valor = _texto_limpo(row.get(campo))
            if valor:
                linhas.append(f"{campo}: {valor}")

        if linhas:
            partes.append("CADASTRO DA PI NO SUPABASE:\n" + "\n".join(linhas))

        if df_obrigacoes is not None and not df_obrigacoes.empty:
            obrigacoes = []
            for _, r in df_obrigacoes.iterrows():
                obrigacoes.append(
                    " | ".join(
                        f"{campo}: {_texto_limpo(r.get(campo))}"
                        for campo in [
                            "numero_anuidade",
                            "descricao_pagamento",
                            "data_inicio_ordinario",
                            "data_fim_ordinario",
                            "data_inicio_extraordinario",
                            "data_fim_extraordinario",
                            "data_pagamento",
                            "status",
                        ]
                        if _texto_limpo(r.get(campo))
                    )
                )

            partes.append(
                "OBRIGAÇÕES FINANCEIRAS DA PI:\n"
                + "\n".join(obrigacoes)
            )

    return "\n\n".join(partes)


def render_assistente_juridico():
    """
    Página integrada ao app.py.
    Não usa st.set_page_config() e não cria um segundo menu lateral.
    """

    st.title("⚖️ Assistente Jurídico NIT")
    st.caption(
        "RAG com documentos PDF + GROQ + integração com o Supabase."
    )

    groq_key = _get_groq_key()

    if not groq_key:
        st.error(
            "GROQ_API_KEY não encontrada nos Secrets do Streamlit."
        )
        st.info(
            "No Streamlit Cloud: Settings → Secrets → "
            'GROQ_API_KEY = "sua-chave"'
        )
        return

    os.environ["GROQ_API_KEY"] = groq_key

    try:
        llm = ChatGroq(
            model=MODEL_NAME,
            temperature=0.2,
            max_tokens=2048,
        )
    except Exception as exc:
        st.error(f"Erro ao inicializar o GROQ: {exc}")
        return

    # Estado do PDF/RAG
    if "juridico_chroma_dir" not in st.session_state:
        st.session_state.juridico_chroma_dir = tempfile.mkdtemp(
            prefix="chroma_rag_nit_"
        )

    if "juridico_pdf_hash" not in st.session_state:
        st.session_state.juridico_pdf_hash = None

    if "juridico_vectordb" not in st.session_state:
        st.session_state.juridico_vectordb = None

    # ---------- seleção de PI do banco ----------
    st.subheader("1. Contexto institucional")
    usar_banco = st.checkbox(
        "Usar também os dados da PI e obrigações financeiras do Supabase",
        value=True,
    )

    df_ativos = None
    ativo_id = None

    if usar_banco:
        try:
            df_ativos = db.obter_patentes()

            if df_ativos.empty:
                st.info("Não há PIs cadastradas no Supabase.")
            else:
                opcoes = ["Nenhuma PI específica"]
                mapa = {}

                for _, row in df_ativos.iterrows():
                    texto = (
                        f"{_texto_limpo(row.get('numero_patente')) or '-'}"
                        f" — {_texto_limpo(row.get('titulo')) or 'Sem título'}"
                        f" [{row['id']}]"
                    )
                    opcoes.append(texto)
                    mapa[texto] = row["id"]

                escolha_pi = st.selectbox(
                    "PI para contexto da consulta (opcional)",
                    opcoes,
                )

                if escolha_pi != "Nenhuma PI específica":
                    ativo_id = mapa[escolha_pi]

        except Exception as exc:
            st.warning(
                f"Não foi possível carregar o contexto do Supabase: {exc}"
            )

    # ---------- PDF ----------
    st.subheader("2. Documento jurídico")
    pdf_file = st.file_uploader(
        "Envie um PDF jurídico",
        type=["pdf"],
        key="juridico_pdf_upload",
    )

    if pdf_file:
        pdf_bytes = pdf_file.getvalue()
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()

        if st.session_state.juridico_pdf_hash != pdf_hash:
            with st.spinner("Indexando o PDF no Chroma..."):
                try:
                    # Diretório novo para cada PDF: antes todos iam para a mesma
                    # coleção e os trechos de PDFs antigos se misturavam aos do novo.
                    st.session_state.juridico_chroma_dir = tempfile.mkdtemp(
                        prefix="chroma_rag_nit_"
                    )
                    st.session_state.juridico_vectordb = _indexar_pdf(
                        pdf_bytes,
                        st.session_state.juridico_chroma_dir,
                    )
                    st.session_state.juridico_pdf_hash = pdf_hash
                    st.session_state.juridico_pdf_nome = pdf_file.name
                    st.success(
                        f"PDF indexado: {pdf_file.name}"
                    )
                except Exception as exc:
                    st.error(f"Erro ao indexar o PDF: {exc}")
                    st.session_state.juridico_vectordb = None
                    st.session_state.juridico_pdf_hash = None
        else:
            st.success(
                f"PDF já indexado: {pdf_file.name}"
            )
    elif st.session_state.juridico_vectordb is not None:
        # PDF removido do uploader: não usar mais o índice antigo.
        st.session_state.juridico_vectordb = None
        st.session_state.juridico_pdf_hash = None
        st.session_state.pop("juridico_pdf_nome", None)

    st.subheader("3. Consulta")

    pergunta = st.text_area(
        "Escreva sua pergunta jurídica",
        height=120,
        placeholder=(
            "Ex.: Qual procedimento deve ser adotado pelo NIT "
            "neste caso, conforme o documento?"
        ),
        key="juridico_pergunta",
    )

    consultar = st.button(
        "🔎 Consultar Assistente Jurídico",
        type="primary",
        use_container_width=True,
    )

    if consultar:
        if not pergunta.strip():
            st.warning("Digite uma pergunta.")
        elif st.session_state.juridico_vectordb is None and not usar_banco:
            st.warning(
                "Envie um PDF ou habilite o contexto do Supabase."
            )
        else:
            docs = []
            contexto_pdf = ""

            if st.session_state.juridico_vectordb is not None:
                retriever = st.session_state.juridico_vectordb.as_retriever(
                    search_kwargs={"k": 5}
                )
                docs = retriever.invoke(pergunta)
                contexto_pdf = _formatar_docs(docs)

            contexto_banco = ""
            if usar_banco and ativo_id is not None:
                try:
                    df_pi = db.buscar_contexto_ativo_pi(
                        ativo_pi_id=ativo_id
                    )
                    df_obrigacoes = db.obter_obrigacoes_ativo(
                        ativo_id
                    )
                    contexto_banco = _texto_contexto_banco(
                        df_pi,
                        df_obrigacoes,
                    )
                except Exception as exc:
                    contexto_banco = (
                        f"Não foi possível recuperar o contexto do banco: {exc}"
                    )

            contexto = (
                "DOCUMENTO JURÍDICO:\n"
                + (contexto_pdf or "Nenhum PDF fornecido.")
                + "\n\n"
                + "CONTEXTO INSTITUCIONAL DO SUPABASE:\n"
                + (contexto_banco or "Nenhuma PI específica selecionada.")
            )

            system_block = """
Você é o Assistente Jurídico do NIT/IFSC.

Sua função é auxiliar a análise de documentos e procedimentos de
propriedade intelectual. Não substitua a análise jurídica humana.

REGRAS:
1. Priorize o conteúdo do documento fornecido.
2. Quando utilizar dados do Supabase, deixe claro que são dados cadastrais
   da instituição e não uma norma jurídica.
3. Não invente artigos, prazos, normas, decisões ou fatos.
4. Se a informação não estiver disponível no contexto, diga claramente.
5. Diferencie norma/documento jurídico de informação cadastral.
6. Responda em português, de forma técnica, objetiva e didática.
7. Estruture a resposta em:
   - Resumo
   - Fundamentação
   - Aplicação ao caso, quando possível
   - Próximos passos
8. Indique as páginas do PDF quando elas estiverem disponíveis.
"""

            prompt = ChatPromptTemplate.from_messages(
                [
                    SystemMessage(content=system_block),
                    (
                        "human",
                        "Pergunta:\n{question}\n\n"
                        "Contexto disponível:\n{context}\n\n"
                        "Responda com base exclusivamente no contexto "
                        "disponível e sinalize qualquer limitação."
                    ),
                ]
            )

            pipeline = (
                RunnableParallel(
                    context=lambda _: contexto,
                    question=RunnablePassthrough(),
                )
                | prompt
                | llm
                | StrOutputParser()
            )

            with st.spinner("Consultando GROQ..."):
                try:
                    resposta = pipeline.invoke(pergunta.strip())
                except Exception as exc:
                    st.error(f"Erro na consulta ao GROQ: {exc}")
                    resposta = None

            if resposta:
                st.session_state.juridico_ultima_resposta = resposta
                st.session_state.juridico_ultima_pergunta = pergunta.strip()

                fontes = _extrair_fontes(docs)
                paginas = ", ".join(
                    sorted(
                        {
                            str(f["pagina"])
                            for f in fontes
                            if f.get("pagina") not in (None, "?")
                        },
                        key=lambda x: int(x) if x.isdigit() else 999999,
                    )
                )

                ok_hist, msg_hist = db.registrar_consulta_juridica(
                    pergunta=pergunta.strip(),
                    resposta=resposta,
                    documento_nome=(
                        st.session_state.get("juridico_pdf_nome")
                        if pdf_file
                        else None
                    ),
                    paginas=paginas or None,
                    fontes=fontes,
                    ativo_pi_id=ativo_id,
                    modelo=MODEL_NAME,
                )

                st.markdown("### Resposta")
                st.write(resposta)

                if fontes:
                    st.markdown("### 📚 Fontes recuperadas")
                    for fonte in fontes:
                        st.write(
                            f"- Página {fonte['pagina']} — {fonte['fonte']}"
                        )

                if ok_hist:
                    st.success("✅ Consulta salva no histórico do Supabase.")
                else:
                    st.warning(msg_hist)

    # ---------- histórico ----------
    st.divider()
    st.subheader("🗂️ Histórico de consultas jurídicas")

    try:
        historico = db.obter_historico_consultas_juridicas(50)

        if historico.empty:
            st.info("Nenhuma consulta jurídica registrada ainda.")
        else:
            for _, row in historico.iterrows():
                data = _texto_limpo(row.get("created_at"))[:19].replace("T", " ")
                pergunta_hist = _texto_limpo(row.get("pergunta"))
                documento = _texto_limpo(row.get("documento_nome")) or "Sem PDF"
                paginas = _texto_limpo(row.get("paginas")) or "-"

                with st.expander(
                    f"{data} — {pergunta_hist[:100]}"
                ):
                    st.markdown(f"**Pergunta:** {pergunta_hist}")
                    st.markdown(f"**Documento:** {documento}")
                    st.markdown(f"**Páginas:** {paginas}")
                    st.markdown("**Resposta:**")
                    st.write(_texto_limpo(row.get("resposta")))

                    if st.button(
                        "🗑️ Excluir esta consulta",
                        key=f"del_juridico_{row.get('id')}",
                    ):
                        ok, msg = db.excluir_consulta_juridica(
                            row.get("id")
                        )
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    except Exception as exc:
        st.error(
            "O histórico ainda não está disponível. "
            f"Verifique se a tabela foi criada no Supabase: {exc}"
        )
