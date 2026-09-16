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
    SUPABASE_KEY = str(
        st.secrets["SUPABASE_PUBLISHABLE_KEY"]
    ).strip()
except Exception:
    SUPABASE_KEY = os.getenv(
        "SUPABASE_PUBLISHABLE_KEY",
        ""
    ).strip()

try:
    SUPABASE_TABLE = (
        str(
            st.secrets.get(
                "SUPABASE_TABLE",
                "ativos_pi"
            )
        ).strip()
        or "ativos_pi"
    )
except Exception:
    SUPABASE_TABLE = (
        os.getenv(
            "SUPABASE_TABLE",
            "ativos_pi"
        ).strip()
        or "ativos_pi"
    )

SUPABASE_ANUIDADES_TABLE = "obrigacoes_financeiras"


# ============================================================
# SUPABASE REST
# ============================================================
def _headers(prefer: Optional[str] = None) -> Dict[str, str]:
    if not SUPABASE_KEY:
        raise RuntimeError(
            "A chave SUPABASE_PUBLISHABLE_KEY não foi "
            "configurada nos Secrets do Streamlit."
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

    return (
        f"Supabase retornou {response.status_code}: "
        f"{detalhe}"
    )


def _request(
    method: str,
    url: str,
    **kwargs: Any
) -> Any:

    try:
        response = requests.request(
            method,
            url,
            timeout=30,
            **kwargs
        )

    except requests.RequestException as exc:

        raise RuntimeError(
            f"Não foi possível conectar ao Supabase: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise RuntimeError(
            _supabase_error(response)
        )

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

    texto = (
        ""
        if valor is None or pd.isna(valor)
        else str(valor).strip().lower()
    )

    texto = "".join(
        c
        for c in unicodedata.normalize(
            "NFKD",
            texto
        )
        if not unicodedata.combining(c)
    )

    for char in [
        "/",
        "\\",
        "-",
        ".",
        "(",
        ")",
        ":",
        ";",
        "_",
    ]:
        texto = texto.replace(char, " ")

    return "_".join(texto.split())


def normalizar_modalidade(modalidade: Any) -> str:

    chave = _normalizar_texto(modalidade)

    if "software" in chave or "programa" in chave:
        return "Software"

    if (
        "desenho" in chave
        or chave in {
            "di",
            "desenho_industrial"
        }
    ):
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

    if hasattr(valor, "date") and not isinstance(
        valor,
        str
    ):
        try:
            return valor.date().isoformat()
        except Exception:
            pass

    try:
        return pd.to_datetime(
            str(valor).strip(),
            dayfirst=True,
            errors="raise"
        ).date().isoformat()

    except Exception:

        return (
            str(valor).strip()
            or None
        )


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
        "recurso_contra_indeferimento":
            "Recurso contra indeferimento",
        "pedido_de_exame": "Pedido de exame",
        "transferida_a_titularidade":
            "Transferida a titularidade",
        "arquivado": "Arquivado",
        "desistencia": "Desistência",
    }

    return mapa.get(
        chave,
        str(status).strip()
    )


def _coluna_existente(
    df: pd.DataFrame,
    *nomes: str
) -> Optional[str]:

    normalizadas = {
        _normalizar_texto(col): col
        for col in df.columns
    }

    for nome in nomes:

        coluna = normalizadas.get(
            _normalizar_texto(nome)
        )

        if coluna is not None:
            return coluna

    return None


def _gestor_deve_pagar(
    gestor: Any
) -> bool:

    chave = _normalizar_texto(gestor)

    return chave in {
        "ifsc",
        "instituto_federal_de_santa_catarina"
    }


def _status_bloqueia_pagamento(
    status: Any
) -> bool:

    chave = _normalizar_texto(status)

    bloqueados = {
        "indeferido",
        "indeferimento",
        "arquivado",
        "desistencia",
        "desistencia_do_pedido",
    }

    return (
        chave in bloqueados
        or any(
            termo in chave
            for termo in [
                "indefer",
                "arquivad",
                "desist"
            ]
        )
    )


def _deve_pagar(
    gestor: Any,
    status: Any
) -> bool:

    return (
        _gestor_deve_pagar(gestor)
        and not _status_bloqueia_pagamento(status)
    )


# ============================================================
# PREPARAÇÃO DOS REGISTROS
# ============================================================
def _preparar_patentes(
    df: pd.DataFrame
) -> pd.DataFrame:

    if df.empty:
        return df

    aliases = {
        "numero_processo": (
            "numero_processo",
            "numero_patente",
            "processo",
            "numero de patente",
            "patente",
        ),

        "data_deposito": (
            "data_deposito",
            "deposito",
            "depósito",
            "data do deposito",
        ),

        "data_concessao": (
            "data_concessao",
            "data da concessao",
            "data da concessão",
        ),

        "descricao": (
            "descricao",
            "descrição",
            "resumo",
        ),

        "titular": (
            "titular",
            "depositante",
            "depositante/ titular",
            "depositante titular",
        ),

        "gestor": (
            "gestor",
        ),

        "status": (
            "status",
            "status do pedido",
            "situacao",
            "situação",
        ),

        "titulo": (
            "titulo",
            "título",
        ),

        "inventores": (
            "inventores",
            "nome dos inventores",
            "nome do inventor",
        ),

        "campus": (
            "campus",
        ),

        "atributos": (
            "atributos",
            "atributo",
        ),

        "id_externo": (
            "id_externo",
            "id do sistema",
        ),

        "tipo_pi": (
            "tipo_pi",
            "modalidade_pi",
            "modalidade de pi",
            "modalidade",
            "tipo",
        ),

        "ano": (
            "ano",
        ),

        "data_publicacao": (
            "data_publicacao",
            "data da publicacao",
            "data da publicação",
            "datada publicacao",
        ),

        "data_exame": (
            "data_exame",
            "data exame",
            "exame",
        ),

        "acordo_titularidade": (
            "acordo_titularidade",
            "acordo de titularidade",
        ),

        "procuracao": (
            "procuracao",
            "procuração",
        ),

        "termo_cessao": (
            "termo_cessao",
            "termo de cessao",
            "termo de cessão",
        ),

        "ipc_classificacao": (
            "ipc_classificacao",
            "ipc classificacao",
            "ipc classificação",
            "ipc",
        ),

        "linguagem": (
            "linguagem",
            "linguagem do software",
        ),
    }

    for destino, nomes in aliases.items():

        if destino in df.columns:
            continue

        origem = _coluna_existente(
            df,
            *nomes
        )

        df[destino] = (
            df[origem]
            if origem
            else None
        )

    if "numero_patente" not in df.columns:
        df["numero_patente"] = (
            df["numero_processo"]
        )

    if "modalidade_pi" not in df.columns:
        df["modalidade_pi"] = (
            df["tipo_pi"]
        )

    df["tipo_pi"] = (
        df["tipo_pi"]
        .apply(normalizar_modalidade)
    )

    df["modalidade_pi"] = df["tipo_pi"]

    df["status"] = (
        df["status"]
        .apply(_normalizar_status)
    )

    return df


# ============================================================
# PATENTES / PIs
# ============================================================
def init_database() -> None:

    obter_patentes()


def obter_patentes() -> pd.DataFrame:

    data = _request(
        "GET",
        f"{_endpoint()}?select=*&order=id.asc",
        headers=_headers(),
    )

    return _preparar_patentes(
        pd.DataFrame(data or [])
    )


def _patente_url(
    patente_id: Any
) -> str:

    return (
        f"{_endpoint()}?id=eq."
        f"{quote(str(patente_id), safe='')}"
    )


def _payload_patente(
    dados: Dict[str, Any]
) -> Dict[str, Any]:

    gestor = dados.get("gestor")

    status = _normalizar_status(
        dados.get(
            "status_patente",
            dados.get("status")
        )
    )

    modalidade = normalizar_modalidade(
        dados.get(
            "modalidade_pi",
            dados.get("tipo_pi")
        )
    )

    payload = {
        "numero_processo":
            dados.get("numero"),

        "tipo_pi":
            modalidade,

        "data_deposito":
            _parse_data(
                dados.get("data_dep")
            ),

        "data_concessao":
            _parse_data(
                dados.get("data_conc")
            ),

        "descricao":
            dados.get("descricao"),

        "titular":
            dados.get("titular"),

        "gestor":
            gestor,

        "status":
            status,

        "titulo":
            dados.get("titulo"),

        "inventores":
            dados.get("inventores"),

        "campus":
            dados.get("campus"),

        "atributos":
            dados.get("atributos"),

        "acordo_titularidade":
            dados.get("acordo_titularidade"),

        "procuracao":
            dados.get("procuracao"),

        "termo_cessao":
            dados.get("termo_cessao"),

        "ipc_classificacao":
            dados.get("ipc_classificacao"),

        "linguagem":
            dados.get("linguagem"),

        "ano":
            dados.get("ano"),

        "data_publicacao":
            _parse_data(
                dados.get("data_publicacao")
            ),

        "data_exame":
            _parse_data(
                dados.get("data_exame")
            ),
    }

    return {
        chave: _valor_limpo(valor)
        for chave, valor in payload.items()
    }


# ============================================================
# CRONOGRAMA DE PAGAMENTOS
# ============================================================
def _calcular_cronograma(
    data_dep: str,
    modalidade_pi: Any
) -> List[Dict[str, Any]]:

    inicio = pd.to_datetime(data_dep)

    modalidade = normalizar_modalidade(
        modalidade_pi
    )

    if modalidade == "Software":

        itens = [
            (
                1,
                "Registro de Software",
                0,
                "Registro"
            )
        ]

    elif modalidade == "Desenho Industrial":

        itens = [
            (
                i,
                f"{i}º quinquênio - Desenho Industrial",
                i * 5,
                "Quinquenio"
            )
            for i in range(1, 5)
        ]

    else:

        itens = [
            (
                i,
                f"{i}ª anuidade - Patente",
                i - 1,
                "Anuidade"
            )
            for i in range(1, 21)
        ]

    cronograma = []

    for numero, descricao, anos, tipo_obrigacao in itens:

        ini = inicio + pd.DateOffset(
            years=anos
        )

        if tipo_obrigacao == "Anuidade":

            venc = ini + pd.DateOffset(
                months=3
            )

            inicio_extra = (
                venc + pd.DateOffset(days=1)
            )

            fim_extra = (
                inicio_extra
                + pd.DateOffset(months=6)
            )

        else:

            venc = ini
            inicio_extra = None
            fim_extra = None

        cronograma.append({
            "numero_obrigacao":
                numero,

            "tipo_obrigacao":
                tipo_obrigacao,

            "descricao_pagamento":
                descricao,

            "data_inicio":
                ini.date().isoformat(),

            "data_vencimento":
                venc.date().isoformat(),

            "data_inicio_extraordinario":
                (
                    inicio_extra.date().isoformat()
                    if inicio_extra is not None
                    else None
                ),

            "data_fim_extraordinario":
                (
                    fim_extra.date().isoformat()
                    if fim_extra is not None
                    else None
                ),

            "data_pagamento":
                None,

            "status":
                "Pendente",
        })

    return cronograma


def _anuidades_patente_url(
    patente_id: Any
) -> str:

    return (
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}"
        f"?ativo_pi_id=eq."
        f"{quote(str(patente_id), safe='')}"
    )


def _sincronizar_anuidades(
    patente_id: Any,
    data_dep: Any,
    modalidade_pi: Any
) -> None:

    data_dep = _parse_data(
        data_dep
    )

    if not data_dep:
        return

    cronograma = _calcular_cronograma(
        data_dep,
        modalidade_pi
    )

    existentes = _request(
        "GET",
        f"{_anuidades_patente_url(patente_id)}"
        f"&select=*",
        headers=_headers(),
    ) or []

    existentes_por_numero = {
        int(item["numero_obrigacao"]): item
        for item in existentes
        if item.get("numero_obrigacao") is not None
    }

    for item in cronograma:

        numero = int(
            item["numero_obrigacao"]
        )

        existente = (
            existentes_por_numero
            .get(numero)
        )

        payload = {
            "ativo_pi_id":
                patente_id,

            "tipo_obrigacao":
                item["tipo_obrigacao"],

            "numero_obrigacao":
                numero,

            "descricao_pagamento":
                item["descricao_pagamento"],

            "data_inicio":
                item["data_inicio"],

            "data_vencimento":
                item["data_vencimento"],

            "data_inicio_extraordinario":
                item[
                    "data_inicio_extraordinario"
                ],

            "data_fim_extraordinario":
                item[
                    "data_fim_extraordinario"
                ],
        }

        if existente:

            _request(
                "PATCH",
                f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}"
                f"?id=eq."
                f"{quote(str(existente['id']), safe='')}",
                headers=_headers(
                    "return=minimal"
                ),
                json=payload,
            )

        else:

            _request(
                "POST",
                _endpoint(
                    SUPABASE_ANUIDADES_TABLE
                ),
                headers=_headers(
                    "return=minimal"
                ),
                json=payload,
            )


def garantir_pagamentos_existentes() -> None:

    df = obter_patentes()

    if df.empty:
        return

    for _, pi in df.iterrows():

        if pi.get("data_deposito"):

            _sincronizar_anuidades(
                pi["id"],
                pi.get("data_deposito"),
                pi.get("tipo_pi"),
            )


def _sincronizar_apos_salvar(
    patente_id: Any,
    dados: Dict[str, Any]
) -> None:

    _sincronizar_anuidades(
        patente_id,
        dados.get("data_dep"),
        dados.get("tipo_pi"),
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
            headers=_headers(
                "return=representation"
            ),
            json=_payload_patente(
                dados
            ),
        )

        if not resultado:

            raise RuntimeError(
                "Supabase não retornou o ID "
                "da PI cadastrada."
            )

        patente_id = (
            resultado[0]["id"]
            if isinstance(resultado, list)
            else resultado["id"]
        )

        _sincronizar_apos_salvar(
            patente_id,
            dados
        )

        return (
            True,
            "PI cadastrada com sucesso no Supabase"
        )

    except Exception as exc:

        return (
            False,
            f"Erro ao cadastrar PI: {exc}"
        )


def atualizar_patente(
    patente_id: Any,
    **dados: Any
) -> Tuple[bool, str]:

    try:

        _request(
            "PATCH",
            _patente_url(patente_id),
            headers=_headers(
                "return=minimal"
            ),
            json=_payload_patente(
                dados
            ),
        )

        atual = obter_patentes()

        linha = (
            atual[
                atual["id"].astype(str)
                == str(patente_id)
            ]
            if not atual.empty
            else pd.DataFrame()
        )

        if not linha.empty:

            pi = linha.iloc[0]

            data_dep = (
                dados.get("data_dep")
                or pi.get("data_deposito")
            )

            modalidade = (
                dados.get("tipo_pi")
                or pi.get("tipo_pi")
            )

            _sincronizar_anuidades(
                patente_id,
                data_dep,
                modalidade
            )

        return (
            True,
            "PI atualizada com sucesso no Supabase"
        )

    except Exception as exc:

        return (
            False,
            f"Erro ao atualizar PI: {exc}"
        )


def salvar_patente_importada(
    dados: Dict[str, Any],
    cur: Any = None
) -> Tuple[bool, str]:

    try:

        numero = quote(
            str(dados["numero"]),
            safe=""
        )

        existente = _request(
            "GET",
            f"{_endpoint()}"
            f"?select=id"
            f"&numero_processo=eq.{numero}"
            f"&limit=1",
            headers=_headers(),
        )

        payload = _payload_patente(
            dados
        )

        if existente:

            patente_id = existente[0]["id"]

            _request(
                "PATCH",
                _patente_url(patente_id),
                headers=_headers(
                    "return=minimal"
                ),
                json=payload,
            )

            _sincronizar_anuidades(
                patente_id,
                dados.get("data_dep"),
                dados.get("tipo_pi"),
            )

            return (
                True,
                "PI existente atualizada no Supabase"
            )

        resultado = _request(
            "POST",
            _endpoint(),
            headers=_headers(
                "return=representation"
            ),
            json=payload,
        )

        patente_id = (
            resultado[0]["id"]
            if isinstance(resultado, list)
            else resultado["id"]
        )

        _sincronizar_anuidades(
            patente_id,
            dados.get("data_dep"),
            dados.get("tipo_pi"),
        )

        return (
            True,
            "Nova PI importada para o Supabase"
        )

    except Exception as exc:

        return False, str(exc)


# ============================================================
# ANUIDADES / PAGAMENTOS
# ============================================================
def _status_calculado_anuidade(
    row: pd.Series
) -> str:
    """
    Retorna os estados em formato padronizado (minúsculas)
    para manter compatibilidade com o front-end e utils.py.
    """
    status = _normalizar_texto(
        row.get("status", "")
    )

    if status in {"nao_pagar", "nao pagar", "não pagar", "não_pagar"}:
        return "nao_pagar"

    if (
        row.get("data_pagamento")
        or status == "pago"
    ):
        return "pago"

    hoje = date.today()

    try:

        inicio_ord = (
            pd.to_datetime(
                row["data_inicio"]
            ).date()
        )

        fim_ord = (
            pd.to_datetime(
                row["data_vencimento"]
            ).date()
        )

        inicio_extra_raw = row.get(
            "data_inicio_extraordinario"
        )

        fim_extra_raw = row.get(
            "data_fim_extraordinario"
        )

        if (
            inicio_extra_raw
            and fim_extra_raw
        ):

            inicio_extra = (
                pd.to_datetime(
                    inicio_extra_raw
                ).date()
            )

            fim_extra = (
                pd.to_datetime(
                    fim_extra_raw
                ).date()
            )

            if hoje > fim_extra:
                return "vermelho"

            if (
                inicio_extra
                <= hoje
                <= fim_extra
            ):
                return "extraordinario"

        if (
            inicio_ord
            <= hoje
            <= fim_ord
        ):
            return "pendente"

        if hoje < inicio_ord:
            return "futuro"

    except Exception:
        pass

    return "pendente"


def obter_anuidades(
    patente_id: Any
) -> pd.DataFrame:
    """
    Obtém as obrigações financeiras da PI e cria aliases de compatibilidade
    com o modelo de dados anterior (SQLite/Front-end).
    """
    df = obter_patentes()

    if df.empty:
        return pd.DataFrame()

    match = df[
        df["id"].astype(str)
        == str(patente_id)
    ]

    if match.empty:
        return pd.DataFrame()

    pi = match.iloc[0]

    data_dep = pi.get(
        "data_deposito"
    )

    modalidade = pi.get(
        "tipo_pi"
    )

    if not data_dep:
        return pd.DataFrame()

    registros = _request(
        "GET",
        f"{_anuidades_patente_url(patente_id)}"
        f"&select=*"
        f"&order=numero_obrigacao.asc",
        headers=_headers(),
    ) or []

    if not registros:

        _sincronizar_anuidades(
            patente_id,
            data_dep,
            modalidade
        )

        registros = _request(
            "GET",
            f"{_anuidades_patente_url(patente_id)}"
            f"&select=*"
            f"&order=numero_obrigacao.asc",
            headers=_headers(),
        ) or []

    resultado = pd.DataFrame(
        registros
    )

    if resultado.empty:
        return resultado

    # ============================================================
    # CAMADA DE COMPATIBILIDADE DE COLUNAS (SQLite -> Supabase)
    # ============================================================
    resultado["numero_anuidade"] = (
        resultado["numero_obrigacao"]
    )
    resultado["data_inicio_ordinario"] = resultado["data_inicio"]
    resultado["data_fim_ordinario"] = resultado["data_vencimento"]

    if "ativo_pi_id" in resultado.columns:
        resultado["patente_id"] = resultado["ativo_pi_id"]

    resultado["modalidade_pi"] = pi.get("tipo_pi")

    pode_pagar = _deve_pagar(
        pi.get("gestor"),
        pi.get("status")
    )

    if not pode_pagar:

        resultado["status"] = (
            "nao_pagar"
        )

    else:

        resultado["status"] = (
            resultado.apply(
                _status_calculado_anuidade,
                axis=1
            )
        )

    return resultado


def atualizar_status_anuidade(
    patente_id: Any,
    numero_anuidade: int,
    novo_status: str,
    data_pagamento: Optional[str] = None,
) -> None:

    chave = _normalizar_texto(
        novo_status
    )

    mapa = {
        "pago": "Pago",
        "nao_pagar": "Não pagar",
        "nao pagar": "Não pagar",
        "pendente": "Pendente",
        "vencido": "Vencido",
        "em_analise": "Em análise",
        "cancelado": "Cancelado",
    }

    if chave not in mapa:

        raise ValueError(
            "Status de pagamento inválido."
        )

    status = mapa[chave]

    patente_id_q = quote(
        str(patente_id),
        safe=""
    )

    numero_q = quote(
        str(int(numero_anuidade)),
        safe=""
    )

    existente = _request(
        "GET",
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}"
        f"?ativo_pi_id=eq.{patente_id_q}"
        f"&numero_obrigacao=eq.{numero_q}"
        f"&limit=1",
        headers=_headers(),
    ) or []

    if not existente:

        df = obter_patentes()

        match = (
            df[
                df["id"].astype(str)
                == str(patente_id)
            ]
            if not df.empty
            else pd.DataFrame()
        )

        if match.empty:
            raise RuntimeError(
                "PI não encontrada."
            )

        pi = match.iloc[0]

        _sincronizar_anuidades(
            patente_id,
            pi.get("data_deposito"),
            pi.get("tipo_pi")
        )

        existente = _request(
            "GET",
            f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}"
            f"?ativo_pi_id=eq.{patente_id_q}"
            f"&numero_obrigacao=eq.{numero_q}"
            f"&limit=1",
            headers=_headers(),
        ) or []

    if not existente:

        raise RuntimeError(
            "Obrigação financeira não encontrada "
            "para esta PI."
        )

    registro_id = existente[0]["id"]

    payload = {
        "status": status
    }

    if status == "Pago":

        payload["data_pagamento"] = (
            _parse_data(data_pagamento)
            or date.today().isoformat()
        )

    elif status in {
        "Não pagar",
        "Pendente",
        "Vencido",
        "Cancelado"
    }:

        payload["data_pagamento"] = None

    _request(
        "PATCH",
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}"
        f"?id=eq."
        f"{quote(str(registro_id), safe='')}",
        headers=_headers(
            "return=minimal"
        ),
        json=payload,
    )


def deletar_patente(
    patente_id: Any
) -> None:

    _request(
        "DELETE",
        _patente_url(patente_id),
        headers=_headers(
            "return=minimal"
        ),
    )


# ============================================================
# IMPORTAÇÃO EM LOTE DE ATIVOS DE PI
# ============================================================
def importar_ativos_lote(
    lista_ativos: List[Dict[str, Any]]
) -> Tuple[bool, str]:
    """
    Importa uma lista de ativos de PI diretamente para
    a tabela 'ativos_pi'.
    """

    if not lista_ativos:

        return (
            False,
            "Nenhum dado fornecido para importação."
        )

    try:

        registros = []

        for indice, ativo in enumerate(
            lista_ativos,
            start=1
        ):

            if not isinstance(
                ativo,
                dict
            ):

                return (
                    False,
                    f"Registro {indice} da importação "
                    "não é um dicionário válido."
                )

            numero_processo = _valor_limpo(
                ativo.get(
                    "numero_processo"
                )
            )

            tipo_pi = normalizar_modalidade(
                ativo.get("tipo_pi")
            )

            data_deposito = _parse_data(
                ativo.get("data_deposito")
            )

            if not numero_processo:

                return (
                    False,
                    f"Registro {indice}: "
                    "número do processo não informado."
                )

            if not data_deposito:

                return (
                    False,
                    f"Registro {indice} "
                    f"({numero_processo}): "
                    "data de depósito não informada "
                    "ou inválida."
                )

            linguagem = _valor_limpo(
                ativo.get("linguagem")
            )

            if (
                tipo_pi == "Software"
                and not linguagem
            ):

                return (
                    False,
                    f"Registro {indice} "
                    f"({numero_processo}): "
                    "a linguagem é obrigatória "
                    "para Software."
                )

            registro = {

                "tipo_pi":
                    tipo_pi,

                "numero_processo":
                    str(
                        numero_processo
                    ).strip(),

                "titulo":
                    _valor_limpo(
                        ativo.get("titulo")
                    ),

                "descricao":
                    _valor_limpo(
                        ativo.get("descricao")
                    ),

                "titular":
                    _valor_limpo(
                        ativo.get("titular")
                    ),

                "gestor":
                    _valor_limpo(
                        ativo.get("gestor")
                    ),

                "inventores":
                    _valor_limpo(
                        ativo.get("inventores")
                    ),

                "campus":
                    _valor_limpo(
                        ativo.get("campus")
                    ),

                "status":
                    _normalizar_status(
                        ativo.get("status")
                    ),

                "data_deposito":
                    data_deposito,

                "data_concessao":
                    _parse_data(
                        ativo.get(
                            "data_concessao"
                        )
                    ),

                "data_publicacao":
                    _parse_data(
                        ativo.get(
                            "data_publicacao"
                        )
                    ),

                "data_exame":
                    _parse_data(
                        ativo.get(
                            "data_exame"
                        )
                    ),

                "ano":
                    ativo.get("ano"),

                "ipc_classificacao":
                    _valor_limpo(
                        ativo.get(
                            "ipc_classificacao"
                        )
                    ),

                "linguagem":
                    (
                        linguagem
                        if tipo_pi == "Software"
                        else None
                    ),

                "atributos":
                    _valor_limpo(
                        ativo.get("atributos")
                    ),

                "acordo_titularidade":
                    _valor_limpo(
                        ativo.get(
                            "acordo_titularidade"
                        )
                    ),

                "procuracao":
                    _valor_limpo(
                        ativo.get("procuracao")
                    ),

                "termo_cessao":
                    _valor_limpo(
                        ativo.get(
                            "termo_cessao"
                        )
                    ),
            }

            if registro["ano"] is not None:

                try:

                    registro["ano"] = int(
                        float(
                            registro["ano"]
                        )
                    )

                except Exception:

                    registro["ano"] = None

            registros.append(
                registro
            )

        url = (
            f"{_endpoint()}"
            f"?on_conflict=numero_processo"
        )

        response = _request(
            "POST",
            url,
            headers=_headers(
                "resolution=merge-duplicates,"
                "return=representation"
            ),
            json=registros,
        )

        quantidade = (
            len(response)
            if isinstance(
                response,
                list
            )
            else len(registros)
        )

        return (
            True,
            "Importação concluída com sucesso! "
            f"{quantidade} ativo(s) processado(s)."
        )

    except Exception as exc:

        return (
            False,
            f"Erro ao persistir dados "
            f"no Supabase: {exc}"
        )


# ============================================================
# IMPORTAÇÃO EXCEL ANTIGA
# ============================================================
def importar_excel(
    arquivo_excel
) -> List[Tuple[str, bool, str]]:

    resultados = []

    try:

        df = pd.read_excel(
            arquivo_excel
        )

    except Exception as exc:

        return [
            (
                "ERRO_GERAL",
                False,
                f"Falha ao ler a planilha: {exc}"
            )
        ]

    colunas = {
        _normalizar_texto(col): col
        for col in df.columns
    }

    def campo(
        *nomes: str
    ) -> Optional[str]:

        for nome in nomes:

            coluna = colunas.get(
                _normalizar_texto(nome)
            )

            if coluna is not None:
                return coluna

        return None

    mapa = {

        "id_externo":
            campo(
                "id",
                "id externo",
                "id do sistema"
            ),

        "numero":
            campo(
                "processo",
                "numero_processo",
                "numero de patente",
                "patente"
            ),

        "data_dep":
            campo(
                "deposito",
                "depósito",
                "data_deposito",
                "data do deposito"
            ),

        "data_conc":
            campo(
                "data da concessao",
                "data da concessão",
                "data_concessao"
            ),

        "titulo":
            campo(
                "titulo",
                "título"
            ),

        "descricao":
            campo(
                "resumo",
                "descricao",
                "descrição"
            ),

        "inventores":
            campo(
                "nome dos inventores",
                "inventores",
                "nome do inventor"
            ),

        "titular":
            campo(
                "depositante/ titular",
                "depositante titular",
                "titular",
                "depositante"
            ),

        "gestor":
            campo("gestor"),

        "status":
            campo(
                "status do pedido",
                "status",
                "situacao",
                "situação"
            ),

        "campus":
            campo("campus"),

        "atributos":
            campo(
                "atributos",
                "atributo"
            ),

        "modalidade_pi":
            campo(
                "modalidade de pi",
                "modalidade pi",
                "modalidade",
                "tipo"
            ),

        "ano":
            campo("ano"),

        "data_publicacao":
            campo(
                "datada publicacao",
                "datada publicação",
                "data da publicacao",
                "data publicacao"
            ),

        "data_exame":
            campo(
                "data exame",
                "data_exame",
                "exame"
            ),

        "acordo_titularidade":
            campo(
                "acordo de titularidade",
                "acordo titularidade"
            ),

        "procuracao":
            campo(
                "procuracao",
                "procuração"
            ),

        "termo_cessao":
            campo(
                "termo de cessao",
                "termo de cessão",
                "termo cessao"
            ),

        "ipc_classificacao":
            campo(
                "ipc classificacao",
                "ipc classificação",
                "ipc- classificacao",
                "ipc"
            ),

        "linguagem":
            campo(
                "linguagem",
                "linguagem do software"
            ),
    }

    for idx, row in df.iterrows():

        numero = (
            _valor_limpo(
                row.get(
                    mapa["numero"]
                )
            )
            if mapa["numero"]
            else None
        )

        data_dep = (
            _parse_data(
                row.get(
                    mapa["data_dep"]
                )
            )
            if mapa["data_dep"]
            else None
        )

        if not numero or not data_dep:

            resultados.append(
                (
                    str(
                        numero
                        or f"Linha {idx + 2}"
                    ),
                    False,
                    "Processo ou depósito ausente."
                )
            )

            continue

        ano_val = (
            row.get(
                mapa["ano"]
            )
            if mapa["ano"]
            else None
        )

        try:

            ano_val = (
                int(float(ano_val))
                if pd.notna(ano_val)
                else None
            )

        except Exception:

            ano_val = None

        dados = {

            "numero":
                str(numero).strip(),

            "data_dep":
                data_dep,

            "data_conc":
                (
                    _parse_data(
                        row.get(
                            mapa["data_conc"]
                        )
                    )
                    if mapa["data_conc"]
                    else None
                ),

            "descricao":
                (
                    _valor_limpo(
                        row.get(
                            mapa["descricao"]
                        )
                    )
                    if mapa["descricao"]
                    else None
                ),

            "titular":
                (
                    _valor_limpo(
                        row.get(
                            mapa["titular"]
                        )
                    )
                    if mapa["titular"]
                    else None
                ),

            "gestor":
                (
                    _valor_limpo(
                        row.get(
                            mapa["gestor"]
                        )
                    )
                    if mapa["gestor"]
                    else None
                ),

            "status_patente":
                (
                    _normalizar_status(
                        row.get(
                            mapa["status"]
                        )
                    )
                    if mapa["status"]
                    else "Ativo"
                ),

            "titulo":
                (
                    _valor_limpo(
                        row.get(
                            mapa["titulo"]
                        )
                    )
                    if mapa["titulo"]
                    else None
                ),

            "inventores":
                (
                    _valor_limpo(
                        row.get(
                            mapa["inventores"]
                        )
                    )
                    if mapa["inventores"]
                    else None
                ),

            "campus":
                (
                    _valor_limpo(
                        row.get(
                            mapa["campus"]
                        )
                    )
                    if mapa["campus"]
                    else None
                ),

            "atributos":
                (
                    _valor_limpo(
                        row.get(
                            mapa["atributos"]
                        )
                    )
                    if mapa["atributos"]
                    else None
                ),

            "id_externo":
                (
                    _valor_limpo(
                        row.get(
                            mapa["id_externo"]
                        )
                    )
                    if mapa["id_externo"]
                    else None
                ),

            "modalidade_pi":
                (
                    normalizar_modalidade(
                        row.get(
                            mapa["modalidade_pi"]
                        )
                    )
                    if mapa["modalidade_pi"]
                    else "Patente"
                ),

            "ano":
                ano_val,

            "data_publicacao":
                (
                    _parse_data(
                        row.get(
                            mapa["data_publicacao"]
                        )
                    )
                    if mapa["data_publicacao"]
                    else None
                ),

            "data_exame":
                (
                    _parse_data(
                        row.get(
                            mapa["data_exame"]
                        )
                    )
                    if mapa["data_exame"]
                    else None
                ),

            "acordo_titularidade":
                (
                    _valor_limpo(
                        row.get(
                            mapa["acordo_titularidade"]
                        )
                    )
                    if mapa["acordo_titularidade"]
                    else None
                ),

            "procuracao":
                (
                    _valor_limpo(
                        row.get(
                            mapa["procuracao"]
                        )
                    )
                    if mapa["procuracao"]
                    else None
                ),

            "termo_cessao":
                (
                    _valor_limpo(
                        row.get(
                            mapa["termo_cessao"]
                        )
                    )
                    if mapa["termo_cessao"]
                    else None
                ),

            "ipc_classificacao":
                (
                    _valor_limpo(
                        row.get(
                            mapa["ipc_classificacao"]
                        )
                    )
                    if mapa["ipc_classificacao"]
                    else None
                ),

            "linguagem":
                (
                    _valor_limpo(
                        row.get(
                            mapa["linguagem"]
                        )
                    )
                    if mapa.get("linguagem")
                    else None
                ),
        }

        ok, msg = salvar_patente_importada(
            dados
        )

        resultados.append(
            (
                dados["numero"],
                ok,
                msg
            )
        )

    return resultados


# ============================================================
# VALIDAÇÃO DA PLANILHA
# ============================================================
def analisar_inconsistencias_excel(
    arquivo_excel
) -> List[str]:

    df = pd.read_excel(
        arquivo_excel
    )

    colunas = {
        _normalizar_texto(col): col
        for col in df.columns
    }

    problemas = []

    if not any(
        c in colunas
        for c in [
            "processo",
            "numero_processo",
            "patente"
        ]
    ):

        problemas.append(
            "Coluna obrigatória 'Processo' "
            "não foi encontrada."
        )

    if not any(
        c in colunas
        for c in [
            "deposito",
            "data_deposito"
        ]
    ):

        problemas.append(
            "Coluna obrigatória 'Depósito' "
            "não foi encontrada."
        )

    if not any(
        c in colunas
        for c in [
            "modalidade_de_pi",
            "modalidade_pi",
            "modalidade",
            "tipo"
        ]
    ):

        problemas.append(
            "Coluna 'Modalidade de PI' "
            "não encontrada; os registros "
            "serão tratados como Patente."
        )

    return problemas
