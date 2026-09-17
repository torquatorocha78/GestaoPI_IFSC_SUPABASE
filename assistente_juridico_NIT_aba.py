"""
Assistente Jurídico do NIT/IFSC
Módulo RAG para ser executado como uma única página/aba do app principal.

Mantém a lógica do programa original:
Groq + LangChain + Chroma + HuggingFace Embeddings + PDF.

Uso no app.py:
    import assistente_juridico_NIT
    ...
    assistente_juridico_NIT.render_assistente_juridico()
"""

import hashlib
import os
import tempfile

import streamlit as st

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


SYSTEM_BLOCK = """Você é um assistente jurídico do NIT/IFSC.

Sua função é auxiliar tecnicamente a equipe do NIT na análise de documentos
jurídicos, contratos, pareceres, decisões, leis, regulamentos e demais
documentos fornecidos pelo usuário.

Use prioritariamente o conteúdo recuperado dos documentos fornecidos.
Não invente informações, artigos, cláusulas, decisões ou fundamentos.

Quando a informação solicitada não estiver suficientemente sustentada pelos
documentos recuperados, diga claramente que não foi localizada no material
fornecido e indique o que deve ser verificado.

Quando houver conflito entre documentos recuperados, sinalize o conflito e
identifique os respectivos documentos/páginas.

A resposta deve ser técnica, objetiva e didática, organizada em:
1. Resumo
2. Fundamentação
3. Análise
4. Próximos passos

Sempre que possível, indique a página do documento utilizada.
Deixe claro que a resposta é um apoio à análise jurídica e não substitui
a análise profissional responsável pelo caso concreto.
"""


def _criar_banco_vetorial(pdf_bytes: bytes, diretorio: str) -> Chroma:
    """Cria o índice vetorial do PDF enviado."""
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

        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/msmarco-bert-base-dot-v5"
        )

        return Chroma.from_documents(
            documents=chunks,
            embedding=embeddings,
            persist_directory=diretorio,
        )
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _formatar_docs(docs) -> str:
    """Formata os trechos recuperados para o prompt."""
    out = []

    for doc in docs:
        meta = doc.metadata or {}
        pagina = meta.get("page")

        if pagina is None:
            pagina_texto = "?"
        else:
            # PyPDFLoader normalmente usa índice iniciado em 0.
            pagina_texto = str(int(pagina) + 1)

        conteudo = (doc.page_content or "").strip()
        if len(conteudo) > 1000:
            conteudo = conteudo[:1000] + "…"

        out.append(f'[p. {pagina_texto}] "{conteudo}"')

    return "\n\n".join(out)


def _obter_api_key() -> str:
    """Obtém a chave Groq sem gravá-la no código."""
    try:
        valor = st.secrets.get("GROQ_API_KEY", "")
        if valor:
            return str(valor).strip()
    except Exception:
        pass

    return st.session_state.get("nit_groq_api_key", "").strip()


def _inicializar_rag(pdf_bytes: bytes):
    """Cria/recria o índice somente quando o PDF muda."""
    hash_pdf = hashlib.sha256(pdf_bytes).hexdigest()

    if st.session_state.get("nit_pdf_hash") == hash_pdf:
        return st.session_state.get("nit_vectordb")

    diretorio = tempfile.mkdtemp(prefix="chroma_rag_nit_")

    with st.spinner("Indexando o documento jurídico no RAG..."):
        vectordb = _criar_banco_vetorial(pdf_bytes, diretorio)

    st.session_state.nit_pdf_hash = hash_pdf
    st.session_state.nit_vectordb = vectordb
    st.session_state.nit_chroma_dir = diretorio

    return vectordb


def render_assistente_juridico():
    """
    Renderiza exclusivamente o conteúdo da aba do Assistente Jurídico.

    Não chama st.set_page_config(), não cria sidebar própria e não interfere
    nas demais páginas do app principal.
    """
    st.title("⚖️ Assistente Jurídico do NIT")
    st.caption("RAG jurídico com Groq + LangChain + Chroma")

    st.info(
        "Envie um ou mais documentos jurídicos em PDF e faça perguntas "
        "baseadas no conteúdo disponibilizado."
    )

    col1, col2 = st.columns([2, 1])

    with col1:
        pdf_file = st.file_uploader(
            "📄 Envie um PDF jurídico",
            type=["pdf"],
            key="nit_pdf_uploader",
            help=(
                "Ex.: contrato, parecer, decisão, lei, resolução, "
                "regulamento ou outro documento jurídico."
            ),
        )

    with col2:
        api_key = st.text_input(
            "🔐 GROQ API Key",
            value=_obter_api_key(),
            type="password",
            key="nit_groq_api_key_input",
        )

    if not api_key:
        st.warning(
            "Informe a GROQ API Key para utilizar o Assistente Jurídico."
        )
        return

    os.environ["GROQ_API_KEY"] = api_key.strip()

    if pdf_file is None:
        st.warning("Envie um PDF para habilitar o RAG.")
        return

    try:
        pdf_bytes = pdf_file.getvalue()
        vectordb = _inicializar_rag(pdf_bytes)

        if vectordb is None:
            st.error("Não foi possível criar o índice vetorial.")
            return

        st.success(f"Documento indexado: {pdf_file.name}")

        retriever = vectordb.as_retriever(
            search_kwargs={"k": 3}
        )

        pergunta = st.text_area(
            "⚖️ Pergunta jurídica",
            height=120,
            placeholder=(
                "Ex.: Quais são as obrigações previstas na cláusula de "
                "propriedade intelectual?"
            ),
            key="nit_pergunta_juridica",
        )

        if st.button(
            "🔎 Perguntar ao Assistente Jurídico",
            type="primary",
            use_container_width=True,
            key="nit_btn_perguntar",
        ):
            if not pergunta.strip():
                st.warning("Digite uma pergunta.")
                return

            llm = ChatGroq(
                model="openai/gpt-oss-20b",
                temperature=0.2,
                max_tokens=2048,
            )

            qa_prompt = ChatPromptTemplate.from_messages(
                [
                    SystemMessage(content=SYSTEM_BLOCK),
                    (
                        "human",
                        "Pergunta: {question}\n\n"
                        "Contexto recuperado dos documentos:\n"
                        "{context}\n\n"
                        "Responda em português, de forma técnica, objetiva "
                        "e didática. Não invente informações.",
                    ),
                ]
            )

            rag_pipeline = (
                RunnableParallel(
                    context=retriever | _formatar_docs,
                    question=RunnablePassthrough(),
                )
                | qa_prompt
                | llm
                | StrOutputParser()
            )

            with st.spinner("Analisando os documentos..."):
                answer = rag_pipeline.invoke(pergunta)

            st.markdown("### 📋 Resposta")
            st.markdown(answer)

    except Exception as exc:
        st.error(
            "Erro ao executar o Assistente Jurídico. "
            f"Detalhes: {exc}"
        )
