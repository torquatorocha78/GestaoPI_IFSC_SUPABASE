import os
import unicodedata
import streamlit as st
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests

# ============================================================
# CONFIGURAÇÃO SUPABASE
# ============================================================
# SUPABASE_URL pode ser informado como:
# https://xxxx.supabase.co
# ou até https://xxxx.supabase.co/rest/v1/
# O código abaixo corrige automaticamente o segundo caso.
# Streamlit Cloud disponibiliza os Secrets por st.secrets.
# Mantemos os.getenv como fallback para execução local.
try:
    SUPABASE_URL = str(st.secrets["SUPABASE_URL"]).strip().rstrip("/")
except Exception:
    SUPABASE_URL = os.getenv(
        "SUPABASE_URL",
        "https://ptxtclyfwlcwqgwzqieu.supabase.co",
    ).strip().rstrip("/")

if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-len("/rest/v1")].rstrip("/")

try:
    SUPABASE_KEY = str(st.secrets["SUPABASE_PUBLISHABLE_KEY"]).strip()
except Exception:
    SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()

try:
    SUPABASE_TABLE = str(st.secrets.get("SUPABASE_TABLE", "patentes")).strip() or "patentes"
except Exception:
    SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "patentes").strip() or "patentes"

SUPABASE_ANUIDADES_TABLE = "anuidades"


# ============================================================
# SUPABASE REST
# ============================================================
def _headers(prefer: Optional[str] = None) -> Dict[str, str]:
    if not SUPABASE_KEY:
        raise RuntimeError(
            "A chave SUPABASE_PUBLISHABLE_KEY não foi configurada nos Secrets do Streamlit."
        )

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


# ============================================================
# NORMALIZAÇÃO
# ============================================================
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
        try:
            return valor.date().isoformat()
        except Exception:
            pass

    try:
        return pd.to_datetime(
            str(valor).strip(), dayfirst=True, errors="raise"
        ).date().isoformat()
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


def _gestor_deve_pagar(gestor: Any) -> bool:
    chave = _normalizar_texto(gestor)
    return chave in {"ifsc", "instituto_federal_de_santa_catarina"}


def _status_bloqueia_pagamento(status: Any) -> bool:
    chave = _normalizar_texto(status)
    bloqueados = {
        "indeferido",
        "indeferimento",
        "arquivado",
        "desistencia",
        "desistencia_do_pedido",
    }
    return chave in bloqueados or any(
        termo in chave for termo in ["indefer", "arquivad", "desist"]
    )


def _deve_pagar(gestor: Any, status: Any) -> bool:
    return _gestor_deve_pagar(gestor) and not _status_bloqueia_pagamento(status)


# ============================================================
# PREPARAÇÃO DOS REGISTROS
# ============================================================
def _preparar_patentes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    aliases = {
        "numero_patente": ("numero_patente", "processo", "numero de patente", "patente"),
        "data_deposito": ("data_deposito", "deposito", "depósito", "data do deposito"),
        "data_concessao": ("data_concessao", "data da concessao", "data da concessão"),
        "descricao": ("descricao", "descrição", "resumo"),
        "titular": ("titular", "depositante", "depositante/ titular", "depositante titular"),
        "gestor": ("gestor",),
        "status": ("status", "status do pedido", "situacao", "situação"),
        "titulo": ("titulo", "título"),
        "inventores": ("inventores", "nome dos inventores", "nome do inventor"),
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

    for destino, nomes in aliases.items():
        if destino in df.columns:
            continue
        origem = _coluna_existente(df, *nomes)
        df[destino] = df[origem] if origem else None

    df["modalidade_pi"] = df["modalidade_pi"].apply(normalizar_modalidade)
    df["status"] = df["status"].apply(_normalizar_status)
    return df


# ============================================================
# PATENTES / PIs
# ============================================================
def init_database() -> None:
    # Apenas testa a conexão. A estrutura é criada pelo SQL no Supabase.
    obter_patentes()


def obter_patentes() -> pd.DataFrame:
    data = _request(
        "GET",
        f"{_endpoint()}?select=*&order=id.asc",
        headers=_headers(),
    )
    return _preparar_patentes(pd.DataFrame(data or []))


def _patente_url(patente_id: Any) -> str:
    return f"{_endpoint()}?id=eq.{quote(str(patente_id), safe='')}"


def _payload_patente(dados: Dict[str, Any]) -> Dict[str, Any]:
    gestor = dados.get("gestor")
    status = _normalizar_status(dados.get("status_patente", dados.get("status")))

    payload = {
        "numero_patente": dados.get("numero"),
        "data_deposito": dados.get("data_dep"),
        "data_concessao": dados.get("data_conc"),
        "descricao": dados.get("descricao"),
        "titular": dados.get("titular"),
        "gestor": gestor,
        "status": status,
        "titulo": dados.get("titulo"),
        "inventores": dados.get("inventores"),
        "campus": dados.get("campus"),
        "atributos": dados.get("atributos"),
        "id_externo": dados.get("id_externo"),
        "modalidade_pi": normalizar_modalidade(dados.get("modalidade_pi")),
        "ano": dados.get("ano"),
        "data_publicacao": dados.get("data_publicacao"),
        "data_exame": dados.get("data_exame"),
        "acordo_titularidade": dados.get("acordo_titularidade"),
        "procuracao": dados.get("procuracao"),
        "termo_cessao": dados.get("termo_cessao"),
        "ipc_classificacao": dados.get("ipc_classificacao"),
    }

    # O banco possui a coluna gerarada "pagar". Não enviamos o valor;
    # o próprio Supabase calcula com gestor + status.
    return {chave: _valor_limpo(valor) for chave, valor in payload.items()}


# ============================================================
# CRONOGRAMA DE PAGAMENTOS
# ============================================================
def _calcular_cronograma(data_dep: str, modalidade_pi: Any) -> List[Dict[str, Any]]:
    inicio = pd.to_datetime(data_dep)
    modalidade = normalizar_modalidade(modalidade_pi)

    if modalidade == "Software":
        itens = [(1, "Taxa única de depósito", 0)]
    elif modalidade == "Desenho Industrial":
        # Depósito + 4 quinquênios.
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


def _anuidades_patente_url(patente_id: Any) -> str:
    return (
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}"
        f"?patente_id=eq.{quote(str(patente_id), safe='')}"
    )


def _sincronizar_anuidades(patente_id: Any, data_dep: Any, modalidade_pi: Any) -> None:
    """Cria/atualiza o cronograma na tabela anuidades sem apagar pagamentos já registrados."""
    data_dep = _parse_data(data_dep)
    if not data_dep:
        return

    cronograma = _calcular_cronograma(data_dep, modalidade_pi)

    existentes = _request(
        "GET",
        f"{_anuidades_patente_url(patente_id)}&select=*",
        headers=_headers(),
    ) or []
    existentes_por_numero = {
        int(item["numero_anuidade"]): item
        for item in existentes
        if item.get("numero_anuidade") is not None
    }

    for item in cronograma:
        numero = int(item["numero_anuidade"])
        existente = existentes_por_numero.get(numero)

        payload = {
            "patente_id": patente_id,
            "numero_anuidade": numero,
            "descricao_pagamento": item["descricao_pagamento"],
            "data_inicio_ordinario": item["data_inicio_ordinario"],
            "data_fim_ordinario": item["data_fim_ordinario"],
            "data_inicio_extraordinario": item["data_inicio_extraordinario"],
            "data_fim_extraordinario": item["data_fim_extraordinario"],
            "modalidade_pi": item["modalidade_pi"],
        }

        # Não sobrescreve status/data de pagamento já registrados.
        if existente:
            _request(
                "PATCH",
                f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}?id=eq.{quote(str(existente['id']), safe='')}",
                headers=_headers("return=minimal"),
                json=payload,
            )
        else:
            _request(
                "POST",
                _endpoint(SUPABASE_ANUIDADES_TABLE),
                headers=_headers("return=minimal"),
                json=payload,
            )


def garantir_pagamentos_existentes() -> None:
    """Garante que PIs existentes tenham seus cronogramas na tabela anuidades."""
    df = obter_patentes()
    if df.empty:
        return

    for _, pi in df.iterrows():
        if pi.get("data_deposito"):
            _sincronizar_anuidades(
                pi["id"],
                pi.get("data_deposito"),
                pi.get("modalidade_pi"),
            )


def _sincronizar_apos_salvar(patente_id: Any, dados: Dict[str, Any]) -> None:
    _sincronizar_anuidades(
        patente_id,
        dados.get("data_dep"),
        dados.get("modalidade_pi"),
    )


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
    dados = locals()
    try:
        resultado = _request(
            "POST",
            _endpoint(),
            headers=_headers("return=representation"),
            json=_payload_patente(dados),
        )
        if not resultado:
            raise RuntimeError("Supabase não retornou o ID da PI cadastrada.")

        patente_id = resultado[0]["id"] if isinstance(resultado, list) else resultado["id"]
        _sincronizar_apos_salvar(patente_id, dados)
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

        # Para sincronizar precisamos da data/modalidade atual caso não tenham vindo no PATCH.
        atual = obter_patentes()
        linha = atual[atual["id"].astype(str) == str(patente_id)] if not atual.empty else pd.DataFrame()
        if not linha.empty:
            pi = linha.iloc[0]
            data_dep = dados.get("data_dep") or pi.get("data_deposito")
            modalidade = dados.get("modalidade_pi") or pi.get("modalidade_pi")
            _sincronizar_anuidades(patente_id, data_dep, modalidade)

        return True, "PI atualizada com sucesso no Supabase"
    except Exception as exc:
        return False, f"Erro ao atualizar PI: {exc}"


def salvar_patente_importada(dados: Dict[str, Any], cur: Any = None) -> Tuple[bool, str]:
    try:
        numero = quote(str(dados["numero"]), safe="")
        existente = _request(
            "GET",
            f"{_endpoint()}?select=id&numero_patente=eq.{numero}&limit=1",
            headers=_headers(),
        )
        payload = _payload_patente(dados)

        if existente:
            patente_id = existente[0]["id"]
            _request(
                "PATCH",
                _patente_url(patente_id),
                headers=_headers("return=minimal"),
                json=payload,
            )
            _sincronizar_anuidades(
                patente_id,
                dados.get("data_dep"),
                dados.get("modalidade_pi"),
            )
            return True, "PI existente atualizada no Supabase"

        resultado = _request(
            "POST",
            _endpoint(),
            headers=_headers("return=representation"),
            json=payload,
        )
        patente_id = resultado[0]["id"] if isinstance(resultado, list) else resultado["id"]
        _sincronizar_anuidades(
            patente_id,
            dados.get("data_dep"),
            dados.get("modalidade_pi"),
        )
        return True, "Nova PI importada para o Supabase"
    except Exception as exc:
        return False, str(exc)


# ============================================================
# ANUIDADES / PAGAMENTOS
# ============================================================
def _status_calculado_anuidade(row: pd.Series) -> str:
    if str(row.get("status", "")).lower() == "nao_pagar":
        return "nao_pagar"
    if row.get("data_pagamento") or str(row.get("status", "")).lower() == "pago":
        return "pago"

    hoje = date.today()
    try:
        fim_extra = pd.to_datetime(row["data_fim_extraordinario"]).date()
        inicio_ord = pd.to_datetime(row["data_inicio_ordinario"]).date()
        fim_ord = pd.to_datetime(row["data_fim_ordinario"]).date()
        inicio_extra = pd.to_datetime(row["data_inicio_extraordinario"]).date()

        if hoje > fim_extra:
            return "vermelho"
        if inicio_extra <= hoje <= fim_extra:
            return "extraordinario"
        if inicio_ord <= hoje <= fim_ord:
            return "ordinario"
        if hoje < inicio_ord:
            return "futuro"
    except Exception:
        pass

    return "pendente"


def obter_anuidades(patente_id: Any) -> pd.DataFrame:
    """Busca o cronograma real salvo no Supabase."""
    df = obter_patentes()
    if df.empty:
        return pd.DataFrame()

    match = df[df["id"].astype(str) == str(patente_id)]
    if match.empty:
        return pd.DataFrame()

    pi = match.iloc[0]
    data_dep = pi.get("data_deposito")
    modalidade = pi.get("modalidade_pi")
    if not data_dep:
        return pd.DataFrame()

    # Se a PI ainda não tiver cronograma, cria automaticamente.
    try:
        registros = _request(
            "GET",
            f"{_anuidades_patente_url(patente_id)}&select=*&order=numero_anuidade.asc",
            headers=_headers(),
        ) or []
    except Exception:
        registros = []

    if not registros:
        _sincronizar_anuidades(patente_id, data_dep, modalidade)
        registros = _request(
            "GET",
            f"{_anuidades_patente_url(patente_id)}&select=*&order=numero_anuidade.asc",
            headers=_headers(),
        ) or []

    resultado = pd.DataFrame(registros)
    if resultado.empty:
        return resultado

    # Regra de pagamento da PI.
    pode_pagar = _deve_pagar(pi.get("gestor"), pi.get("status"))
    if not pode_pagar:
        resultado["status"] = "nao_pagar"
    else:
        resultado["status"] = resultado.apply(_status_calculado_anuidade, axis=1)

    return resultado


def atualizar_status_anuidade(
    patente_id: Any,
    numero_anuidade: int,
    novo_status: str,
    data_pagamento: Optional[str] = None,
) -> None:
    """Registra pagamento ou marca a anuidade como não pagar."""
    status = _normalizar_texto(novo_status)
    if status not in {"pago", "nao_pagar", "pendente"}:
        raise ValueError("Status de pagamento inválido.")

    patente_id_q = quote(str(patente_id), safe="")
    numero_q = quote(str(int(numero_anuidade)), safe="")

    # Confere se o registro existe.
    existente = _request(
        "GET",
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}?patente_id=eq.{patente_id_q}&numero_anuidade=eq.{numero_q}&limit=1",
        headers=_headers(),
    ) or []

    if not existente:
        # Cria o cronograma se ainda não existir.
        df = obter_patentes()
        match = df[df["id"].astype(str) == str(patente_id)] if not df.empty else pd.DataFrame()
        if match.empty:
            raise RuntimeError("PI não encontrada.")
        pi = match.iloc[0]
        _sincronizar_anuidades(patente_id, pi.get("data_deposito"), pi.get("modalidade_pi"))
        existente = _request(
            "GET",
            f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}?patente_id=eq.{patente_id_q}&numero_anuidade=eq.{numero_q}&limit=1",
            headers=_headers(),
        ) or []

    if not existente:
        raise RuntimeError("Pagamento/anuidade não encontrado para esta PI.")

    registro_id = existente[0]["id"]
    payload = {"status": status}

    if status == "pago":
        payload["data_pagamento"] = _parse_data(data_pagamento) or date.today().isoformat()
    elif status == "nao_pagar":
        payload["data_pagamento"] = None
    elif status == "pendente":
        payload["data_pagamento"] = None

    _request(
        "PATCH",
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}?id=eq.{quote(str(registro_id), safe='')}",
        headers=_headers("return=minimal"),
        json=payload,
    )


def deletar_patente(patente_id: Any) -> None:
    _request(
        "DELETE",
        _patente_url(patente_id),
        headers=_headers("return=minimal"),
    )


# ============================================================
# IMPORTAÇÃO EXCEL
# ============================================================
def importar_excel(arquivo_excel) -> List[Tuple[str, bool, str]]:
    resultados = []
    try:
        df = pd.read_excel(arquivo_excel)
    except Exception as exc:
        return [("ERRO_GERAL", False, f"Falha ao ler a planilha: {exc}")]

    colunas = {_normalizar_texto(col): col for col in df.columns}

    def campo(*nomes: str) -> Optional[str]:
        for nome in nomes:
            coluna = colunas.get(_normalizar_texto(nome))
            if coluna is not None:
                return coluna
        return None

    mapa = {
        "id_externo": campo("id", "id externo", "id do sistema"),
        "numero": campo("processo", "numero_patente", "numero de patente", "patente"),
        "data_dep": campo("deposito", "depósito", "data_deposito", "data do deposito"),
        "data_conc": campo("data da concessao", "data da concessão", "data_concessao"),
        "titulo": campo("titulo", "título"),
        "descricao": campo("resumo", "descricao", "descrição"),
        "inventores": campo("nome dos inventores", "inventores", "nome do inventor"),
        "titular": campo("depositante/ titular", "depositante titular", "titular", "depositante"),
        "gestor": campo("gestor"),
        "status": campo("status do pedido", "status", "situacao", "situação"),
        "campus": campo("campus"),
        "atributos": campo("atributos", "atributo"),
        "modalidade_pi": campo("modalidade de pi", "modalidade pi", "modalidade", "tipo"),
        "ano": campo("ano"),
        "data_publicacao": campo("datada publicacao", "datada publicação", "data da publicacao", "data publicacao"),
        "data_exame": campo("data exame", "data_exame", "exame"),
        "acordo_titularidade": campo("acordo de titularidade", "acordo titularidade"),
        "procuracao": campo("procuracao", "procuração"),
        "termo_cessao": campo("termo de cessao", "termo de cessão", "termo cessao"),
        "ipc_classificacao": campo("ipc classificacao", "ipc classificação", "ipc- classificacao", "ipc"),
    }

    for idx, row in df.iterrows():
        numero = _valor_limpo(row.get(mapa["numero"])) if mapa["numero"] else None
        data_dep = _parse_data(row.get(mapa["data_dep"])) if mapa["data_dep"] else None

        if not numero or not data_dep:
            resultados.append(
                (str(numero or f"Linha {idx + 2}"), False, "Processo ou depósito ausente.")
            )
            continue

        ano_val = row.get(mapa["ano"]) if mapa["ano"] else None
        try:
            ano_val = int(float(ano_val)) if pd.notna(ano_val) else None
        except Exception:
            ano_val = None

        dados = {
            "numero": str(numero).strip(),
            "data_dep": data_dep,
            "data_conc": _parse_data(row.get(mapa["data_conc"])) if mapa["data_conc"] else None,
            "descricao": _valor_limpo(row.get(mapa["descricao"])) if mapa["descricao"] else None,
            "titular": _valor_limpo(row.get(mapa["titular"])) if mapa["titular"] else None,
            "gestor": _valor_limpo(row.get(mapa["gestor"])) if mapa["gestor"] else None,
            "status_patente": _normalizar_status(row.get(mapa["status"])) if mapa["status"] else "Ativo",
            "titulo": _valor_limpo(row.get(mapa["titulo"])) if mapa["titulo"] else None,
            "inventores": _valor_limpo(row.get(mapa["inventores"])) if mapa["inventores"] else None,
            "campus": _valor_limpo(row.get(mapa["campus"])) if mapa["campus"] else None,
            "atributos": _valor_limpo(row.get(mapa["atributos"])) if mapa["atributos"] else None,
            "id_externo": _valor_limpo(row.get(mapa["id_externo"])) if mapa["id_externo"] else None,
            "modalidade_pi": normalizar_modalidade(row.get(mapa["modalidade_pi"])) if mapa["modalidade_pi"] else "Patente",
            "ano": ano_val,
            "data_publicacao": _parse_data(row.get(mapa["data_publicacao"])) if mapa["data_publicacao"] else None,
            "data_exame": _parse_data(row.get(mapa["data_exame"])) if mapa["data_exame"] else None,
            "acordo_titularidade": _valor_limpo(row.get(mapa["acordo_titularidade"])) if mapa["acordo_titularidade"] else None,
            "procuracao": _valor_limpo(row.get(mapa["procuracao"])) if mapa["procuracao"] else None,
            "termo_cessao": _valor_limpo(row.get(mapa["termo_cessao"])) if mapa["termo_cessao"] else None,
            "ipc_classificacao": _valor_limpo(row.get(mapa["ipc_classificacao"])) if mapa["ipc_classificacao"] else None,
        }

        ok, msg = salvar_patente_importada(dados)
        resultados.append((dados["numero"], ok, msg))

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
        problemas.append(
            "Coluna 'Modalidade de PI' não encontrada; os registros serão tratados como Patente."
        )

    return problemas

