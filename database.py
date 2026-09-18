import os
import json
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests

def _get_secret(nome: str, padrao: str = "") -> str:
    """Lê primeiro variável de ambiente e depois st.secrets, quando disponível."""
    valor = os.getenv(nome)
    if valor:
        return valor
    try:
        import streamlit as st
        return str(st.secrets.get(nome, padrao))
    except Exception:
        return padrao


SUPABASE_URL = _get_secret(
    "SUPABASE_URL",
    "https://ptxtclyfwlcwqgwzqieu.supabase.co",
).rstrip("/")

# Aceita os nomes mais comuns usados no Streamlit/Supabase.
SUPABASE_KEY = (
    _get_secret("SUPABASE_KEY")
    or _get_secret("SUPABASE_PUBLISHABLE_KEY")
    or _get_secret("SUPABASE_ANON_KEY")
)

SUPABASE_TABLE = _get_secret("SUPABASE_TABLE", "patentes")


def _headers(prefer: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def _endpoint(table: str = SUPABASE_TABLE) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def _supabase_error(response: requests.Response) -> str:
    try:
        detalhe = response.json()
    except Exception:
        detalhe = response.text
    return f"Supabase retornou {response.status_code}: {detalhe}"


def _request(method: str, url: str, **kwargs: Any) -> Any:
    try:
        response = requests.request(method, url, timeout=30, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(f"Não foi possível conectar ao Supabase: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(_supabase_error(response))
    if not response.text:
        return None
    try:
        return response.json()
    except Exception:
        return response.text


def _normalizar_texto(valor: Any) -> str:
    texto = "" if valor is None or pd.isna(valor) else str(valor).strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    for char in ["/", "\\", "-", ".", "(", ")", ":", ";", "_"]:
        texto = texto.replace(char, " ")
    return "_".join(texto.split())


def normalizar_modalidade(modalidade: Any) -> str:
    chave = _normalizar_texto(modalidade)
    if "software" in chave or "programa" in chave:
        return "Software"
    if "desenho" in chave or chave in {"di", "desenho_industrial"}:
        return "Desenho Industrial"
    return "Patente"


def _valor_limpo(valor: Any) -> Optional[Any]:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


def _parse_data(valor: Any) -> Optional[str]:
    valor = _valor_limpo(valor)
    if valor is None:
        return None
    if hasattr(valor, "date") and not isinstance(valor, str):
        return valor.date().isoformat()
    try:
        return pd.to_datetime(str(valor).strip(), dayfirst=True, errors="raise").date().isoformat()
    except Exception:
        return str(valor).strip() or None


def _normalizar_status(status: Any) -> str:
    status = _valor_limpo(status)
    if not status:
        return "Ativo"
    chave = _normalizar_texto(status)
    mapa = {
        "patente_concedida": "Patente Concedida",
        "concedido": "Patente Concedida",
        "concessao": "Patente Concedida",
        "tramitando_normal": "Tramitando Normal",
        "indeferimento": "Indeferimento",
        "infederimento": "Indeferimento",
        "recurso_contra_indeferimento": "Recurso contra indeferimento",
        "pedido_de_exame": "Pedido de exame",
        "transferida_a_titularidade": "Transferida a titularidade",
        "arquivado": "Arquivado",
        "desistencia": "Desistência",
    }
    return mapa.get(chave, str(status).strip())


def _coluna_existente(df: pd.DataFrame, *nomes: str) -> Optional[str]:
    normalizadas = {_normalizar_texto(col): col for col in df.columns}
    for nome in nomes:
        coluna = normalizadas.get(_normalizar_texto(nome))
        if coluna is not None:
            return coluna
    return None


def _preparar_patentes(df: pd.DataFrame) -> pd.DataFrame:
    """Converte o schema atual do Supabase para o schema esperado pelo app.py."""
    if df.empty:
        return df

    aliases = {
        "numero_patente": ("numero_patente", "pedido", "processo", "numero de patente", "patente"),
        "data_deposito": ("data_deposito", "deposito", "depósito", "data do deposito"),
        "data_concessao": ("data_concessao", "data da concessao", "data da concessão"),
        "descricao": ("descricao", "descrição", "resumo"),
        "titular": ("titular", "depositante_titular", "depositante", "depositante/ titular"),
        "gestor": ("gestor",),
        "status": ("status", "status do pedido", "situacao", "situação"),
        "titulo": ("titulo", "título"),
        "inventores": ("inventores", "nome_inventores", "nome dos inventores", "nome do inventor"),
        "campus": ("campus",),
        "atributos": ("atributos", "atributo"),
        "id_externo": ("id_externo", "id do sistema"),
        "modalidade_pi": ("modalidade_pi", "modalidade de pi", "modalidade", "tipo"),
        "ano": ("ano",),
        "data_publicacao": ("data_publicacao", "data da publicacao", "data da publicação", "datada publicacao"),
        "data_exame": ("data_exame", "data exame", "exame"),
        "acordo_titularidade": ("acordo_titularidade", "acordo de titularidade"),
        "procuracao": ("procuracao", "procuração"),
        "termo_cessao": ("termo_cessao", "termo de cessao", "termo de cessão"),
        "ipc_classificacao": ("ipc_classificacao", "ipc classificacao", "ipc classificação", "ipc"),
    }

    # Campos adicionais do FORMICT
    aliases.update({
        "inventores_cpf": ("inventores_cpf", "cpf inventores", "cpf dos inventores"),
        "trl": ("trl",),
        "observacoes_formict": ("observacoes_formict", "observações formict", "observacoes formict"),
        "cnae_secao": ("cnae_secao", "setor economico", "setor econômico"),
        "cnae_subclassificacao": ("cnae_subclassificacao", "subclassificacao cnae", "subclassificação cnae"),
        "territorio": ("territorio", "território"),
        "sigilo": ("sigilo",),
        "cotitularidade": ("cotitularidade",),
        "cotitulares": ("cotitulares",),
        "custo_registro": ("custo_registro", "custo de registro"),
        "data_registro": ("data_registro", "data de registro", "data registro"),
        "custo_manutencao_ano_base": ("custo_manutencao_ano_base", "custo manutencao ano base", "custo manutenção ano-base"),
        "data_manutencao": ("data_manutencao", "data manutencao", "data manutenção"),
        "formict_ano_base": ("formict_ano_base", "ano base formict", "ano-base formict"),
    })

    for destino, nomes in aliases.items():
        if destino in df.columns:
            continue
        origem = _coluna_existente(df, *nomes)
        df[destino] = df[origem] if origem else None

    if "id" not in df.columns:
        df["id"] = range(1, len(df) + 1)

    df["modalidade_pi"] = df["modalidade_pi"].apply(normalizar_modalidade)
    df["status"] = df["status"].fillna("Ativo").replace("", "Ativo")

    # Mantém também os campos específicos existentes no schema atual.
    for coluna in ("linguagem", "campo_aplicacao", "tipo_programa"):
        if coluna not in df.columns:
            df[coluna] = None

    return df


def init_database() -> None:
    obter_patentes()


def obter_patentes() -> pd.DataFrame:
    data = _request(
        "GET",
        f"{_endpoint()}?select=*&order=id.asc",
        headers=_headers(),
    )
    df = pd.DataFrame(data or [])
    return _preparar_patentes(df)


def _patente_url(patente_id: Any) -> str:
    return f"{_endpoint()}?id=eq.{quote(str(patente_id), safe='')}"


def _payload_patente(dados: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "pedido": dados.get("numero") or dados.get("numero_patente"),
        "data_deposito": _parse_data(dados.get("data_dep") or dados.get("data_deposito")),
        "data_concessao": _parse_data(dados.get("data_conc") or dados.get("data_concessao")),
        "resumo": dados.get("descricao") or dados.get("resumo"),
        "depositante_titular": dados.get("titular") or dados.get("depositante_titular"),
        "gestor": dados.get("gestor"),
        "status": _normalizar_status(dados.get("status_patente") or dados.get("status")),
        "titulo": dados.get("titulo"),
        "nome_inventores": dados.get("inventores") or dados.get("nome_inventores"),
        "modalidade_pi": normalizar_modalidade(dados.get("modalidade_pi")),
        "ano": dados.get("ano"),
        "data_publicacao": _parse_data(dados.get("data_publicacao")),
        "data_exame": _parse_data(dados.get("data_exame")),
        "acordo_titularidade": dados.get("acordo_titularidade"),
        "ipc_classificacao": dados.get("ipc_classificacao"),
        "linguagem": dados.get("linguagem"),
        "campo_aplicacao": dados.get("campo_aplicacao"),
        "tipo_programa": dados.get("tipo_programa"),
        "inventores_cpf": dados.get("inventores_cpf"),
        "trl": dados.get("trl"),
        "observacoes_formict": dados.get("observacoes_formict"),
        "cnae_secao": dados.get("cnae_secao"),
        "cnae_subclassificacao": dados.get("cnae_subclassificacao"),
        "territorio": dados.get("territorio"),
        "sigilo": dados.get("sigilo"),
        "cotitularidade": dados.get("cotitularidade"),
        "cotitulares": dados.get("cotitulares"),
        "custo_registro": dados.get("custo_registro"),
        "data_registro": _parse_data(dados.get("data_registro")),
        "custo_manutencao_ano_base": dados.get("custo_manutencao_ano_base"),
        "data_manutencao": _parse_data(dados.get("data_manutencao")),
        "formict_ano_base": dados.get("formict_ano_base"),
    }
    return {chave: _valor_limpo(valor) for chave, valor in payload.items() if valor is not None}


def _calcular_cronograma(data_dep: str, modalidade_pi: Any) -> List[Dict[str, Any]]:
    inicio = pd.to_datetime(data_dep)
    modalidade = normalizar_modalidade(modalidade_pi)

    if modalidade == "Software":
        itens = [(1, "Taxa única de depósito", 0)]
    elif modalidade == "Desenho Industrial":
        itens = [(1, "Taxa de depósito", 0)]
        itens += [(i + 1, f"{i}º quinquênio", i * 5) for i in range(1, 5)]
    else:
        itens = [(i, f"{i}ª anuidade", i - 1) for i in range(1, 21)]

    cronograma = []
    for numero, descricao, anos in itens:
        ini_ord = inicio + pd.DateOffset(years=anos)
        fim_ord = ini_ord + pd.DateOffset(months=3)
        ini_ext = fim_ord + pd.DateOffset(days=1)
        fim_ext = ini_ext + pd.DateOffset(months=6)
        cronograma.append({
            "id": f"{numero}",
            "patente_id": None,
            "numero_anuidade": numero,
            "descricao_pagamento": descricao,
            "data_inicio_ordinario": ini_ord.date().isoformat(),
            "data_fim_ordinario": fim_ord.date().isoformat(),
            "data_inicio_extraordinario": ini_ext.date().isoformat(),
            "data_fim_extraordinario": fim_ext.date().isoformat(),
            "data_pagamento": None,
            "status": "pendente",
            "modalidade_pi": modalidade,
        })
    return cronograma


def garantir_pagamentos_existentes() -> None:
    return None


def adicionar_patente(
    numero: str,
    data_dep: str,
    data_conc: Optional[str],
    descricao: Optional[str],
    titular: Optional[str],
    gestor: Optional[str] = None,
    status_patente: str = "Ativo",
    titulo: Optional[str] = None,
    inventores: Optional[str] = None,
    campus: Optional[str] = None,
    atributos: Optional[str] = None,
    id_externo: Optional[str] = None,
    modalidade_pi: Optional[str] = None,
    ano: Optional[int] = None,
    data_publicacao: Optional[str] = None,
    data_exame: Optional[str] = None,
    acordo_titularidade: Optional[str] = None,
    procuracao: Optional[str] = None,
    termo_cessao: Optional[str] = None,
    ipc_classificacao: Optional[str] = None,
) -> Tuple[bool, str]:
    try:
        _request(
            "POST",
            _endpoint(),
            headers=_headers("return=minimal"),
            json=_payload_patente(locals()),
        )
        return True, "PI cadastrada com sucesso no Supabase"
    except Exception as exc:
        return False, f"Erro ao cadastrar PI: {exc}"


def atualizar_patente(patente_id: Any, **dados: Any) -> Tuple[bool, str]:
    try:
        _request(
            "PATCH",
            _patente_url(patente_id),
            headers=_headers("return=minimal"),
            json=_payload_patente(dados),
        )
        return True, "PI atualizada com sucesso no Supabase"
    except Exception as exc:
        return False, f"Erro ao atualizar PI: {exc}"


def salvar_patente_importada(dados: Dict[str, Any], cur: Any = None) -> Tuple[bool, str]:
    try:
        numero = quote(str(dados["numero"]), safe="")
        existente = _request(
            "GET",
            f"{_endpoint()}?select=*&pedido=eq.{numero}&limit=1",
            headers=_headers(),
        )
        payload = _payload_patente(dados)

        # Nunca apaga dados já existentes quando a planilha deixar um campo vazio.
        if existente:
            atual = existente[0]
            payload = {k: v for k, v in payload.items() if v is not None and str(v).strip() != ""}
            # Para campos básicos, só atualiza o que veio preenchido.
            _request(
                "PATCH",
                _patente_url(atual["id"]),
                headers=_headers("return=minimal"),
                json=payload,
            )
            return True, "PI existente e atualizada no SUPABASE"

        _request(
            "POST",
            _endpoint(),
            headers=_headers("return=minimal"),
            json=payload,
        )
        return True, "Nova PI importada para o SUPABASE"
    except Exception as exc:
        return False, str(exc)


def obter_anuidades(patente_id: Any) -> pd.DataFrame:
    df = obter_patentes()
    if df.empty:
        return pd.DataFrame()

    match = df[df["id"].astype(str) == str(patente_id)]
    if match.empty:
        return pd.DataFrame()

    pi = match.iloc[0]
    data_dep = pi.get("data_deposito")
    if not data_dep:
        return pd.DataFrame()

    pagamentos = _calcular_cronograma(data_dep, pi.get("modalidade_pi"))
    for pagamento in pagamentos:
        pagamento["patente_id"] = patente_id

    resultado = pd.DataFrame(pagamentos)
    if resultado.empty:
        return resultado

    hoje = date.today()

    def normalizar_status(row: pd.Series) -> str:
        if row.get("status") == "nao_pagar":
            return "nao_pagar"
        if row.get("data_pagamento") or row.get("status") == "pago":
            return "pago"
        try:
            if pd.to_datetime(row["data_fim_extraordinario"]).date() < hoje:
                return "vermelho"
        except Exception:
            pass
        return "pendente"

    resultado["status"] = resultado.apply(normalizar_status, axis=1)
    return resultado


def atualizar_status_anuidade(
    patente_id: Any,
    numero_anuidade: int,
    novo_status: str,
    data_pagamento: Optional[str] = None,
) -> None:
    """Persiste o pagamento quando a tabela anuidades tiver as colunas usadas pelo app."""
    payload = {
        "patente_id": patente_id,
        "numero_anuidade": numero_anuidade,
        "status": novo_status,
        "data_pagamento": _parse_data(data_pagamento),
    }
    try:
        _request(
            "POST",
            f"{SUPABASE_URL}/rest/v1/anuidades?on_conflict=patente_id,numero_anuidade",
            headers=_headers("resolution=merge-duplicates,return=minimal"),
            json=payload,
        )
    except Exception as exc:
        raise RuntimeError(
            "Não foi possível salvar o status da anuidade no Supabase. "
            "Verifique se a tabela anuidades criada no Supabase contém "
            "patente_id, numero_anuidade, status e data_pagamento. "
            f"Detalhe: {exc}"
        ) from exc


def deletar_patente(patente_id: Any) -> None:
    _request("DELETE", _patente_url(patente_id), headers=_headers("return=minimal"))


def importar_excel(arquivo_excel) -> List[Tuple[str, bool, str]]:
    resultados = []
    try:
        df = pd.read_excel(arquivo_excel)
    except Exception as exc:
        return [("ERRO_GERAL", False, f"Falha ao ler a planilha: {exc}")]

    colunas = {_normalizar_texto(col): col for col in df.columns}
    def campo(*nomes: str) -> Optional[str]:
        for nome in nomes:
            c = colunas.get(_normalizar_texto(nome))
            if c is not None: return c
        return None

    mapa = {
        "numero": campo("processo", "pedido", "numero_patente", "numero de patente", "patente"),
        "data_dep": campo("deposito", "depósito", "data_deposito", "data do deposito"),
        "data_conc": campo("data concessao", "data da concessao", "data da concessão", "data_concessao"),
        "titulo": campo("titulo", "título"),
        "descricao": campo("descricao", "descrição", "resumo"),
        "inventores": campo("inventores", "nome dos inventores", "nome dos inventores"),
        "inventores_cpf": campo("cpf inventores", "cpf dos inventores", "inventores cpf"),
        "titular": campo("titular", "depositante titular", "depositante/ titular", "depositante"),
        "gestor": campo("gestor"),
        "status": campo("status", "status do pedido", "situacao", "situação"),
        "campus": campo("campus"),
        "atributos": campo("atributos", "atributo"),
        "modalidade_pi": campo("modalidade", "modalidade pi", "modalidade de pi", "tipo"),
        "ano": campo("ano"),
        "data_publicacao": campo("data publicacao", "data da publicacao", "datada publicacao"),
        "data_exame": campo("data exame", "data_exame", "exame"),
        "acordo_titularidade": campo("acordo de titularidade", "acordo titularidade"),
        "procuracao": campo("procuracao", "procuração"),
        "termo_cessao": campo("termo de cessao", "termo de cessão", "termo cessao"),
        "ipc_classificacao": campo("ipc classificacao", "ipc classificação", "ipc", "ipc / classificacao"),
        "trl": campo("trl"),
        "observacoes_formict": campo("observacoes", "observações", "observacoes formict", "observações formict"),
        "cnae_secao": campo("cnae secao", "setor economico", "setor econômico"),
        "cnae_subclassificacao": campo("cnae subclassificacao", "subclassificacao cnae", "subclassificação cnae"),
        "territorio": campo("territorio", "território"),
        "sigilo": campo("sigilo"),
        "cotitularidade": campo("cotitularidade"),
        "cotitulares": campo("cotitulares"),
        "custo_registro": campo("custo registro", "custo de registro", "custo_registro"),
        "data_registro": campo("data registro", "data de registro", "data_registro"),
        "custo_manutencao_ano_base": campo("custo manutencao ano base", "custo manutenção ano-base", "custo_manutencao_ano_base"),
        "data_manutencao": campo("data manutencao", "data manutenção", "data_manutencao"),
        "formict_ano_base": campo("ano base", "ano-base", "formict ano base"),
    }

    for idx, row in df.iterrows():
        numero = _valor_limpo(row.get(mapa["numero"])) if mapa["numero"] else None
        data_dep = _parse_data(row.get(mapa["data_dep"])) if mapa["data_dep"] else None
        if not numero or not data_dep:
            resultados.append((str(numero or f"Linha {idx + 2}"), False, "Processo ou depósito ausente.")); continue
        def val(k):
            c=mapa.get(k); return _valor_limpo(row.get(c)) if c else None
        try: ano_val=int(float(val("ano"))) if val("ano") is not None else None
        except Exception: ano_val=None
        try: formict_ano=int(float(val("formict_ano_base"))) if val("formict_ano_base") is not None else None
        except Exception: formict_ano=None
        def money(k):
            v=val(k)
            if v is None:return None
            try:return float(str(v).replace("R$","").replace(".","").replace(",","."))
            except:return v
        dados={
            "numero":str(numero).strip(), "data_dep":data_dep, "data_conc":_parse_data(val("data_conc")),
            "descricao":val("descricao"), "titular":val("titular"), "gestor":val("gestor"),
            "status_patente":_normalizar_status(val("status") or "Ativo"), "titulo":val("titulo"), "inventores":val("inventores"),
            "inventores_cpf":val("inventores_cpf"), "campus":val("campus"), "atributos":val("atributos"),
            "modalidade_pi":normalizar_modalidade(val("modalidade_pi") or "Patente"), "ano":ano_val,
            "data_publicacao":_parse_data(val("data_publicacao")), "data_exame":_parse_data(val("data_exame")),
            "acordo_titularidade":val("acordo_titularidade"), "procuracao":val("procuracao"), "termo_cessao":val("termo_cessao"),
            "ipc_classificacao":val("ipc_classificacao"), "trl":val("trl"), "observacoes_formict":val("observacoes_formict"),
            "cnae_secao":val("cnae_secao"), "cnae_subclassificacao":val("cnae_subclassificacao"), "territorio":val("territorio"),
            "sigilo":val("sigilo"), "cotitularidade":val("cotitularidade"), "cotitulares":val("cotitulares"),
            "custo_registro":money("custo_registro"), "data_registro":_parse_data(val("data_registro")),
            "custo_manutencao_ano_base":money("custo_manutencao_ano_base"), "data_manutencao":_parse_data(val("data_manutencao")),
            "formict_ano_base":formict_ano,
        }
        ok,msg=salvar_patente_importada(dados); resultados.append((dados["numero"],ok,msg))
    return resultados


def analisar_inconsistencias_excel(arquivo_excel) -> List[str]:
    df = pd.read_excel(arquivo_excel)
    colunas = {_normalizar_texto(col): col for col in df.columns}
    problemas = []
    if not any(c in colunas for c in ["processo", "numero_patente", "patente"]):
        problemas.append("Coluna obrigatória 'Processo' não foi encontrada.")
    if not any(c in colunas for c in ["deposito", "data_deposito"]):
        problemas.append("Coluna obrigatória 'Depósito' não foi encontrada.")
    if not any(c in colunas for c in ["modalidade_de_pi", "modalidade_pi", "modalidade", "tipo"]):
        problemas.append("Coluna 'Modalidade de PI' não encontrada; os registros serão tratados como Patente.")
    return problemas
