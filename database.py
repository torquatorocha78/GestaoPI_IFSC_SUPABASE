```python
import os
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests


# ============================================================
# CONFIGURAÇÃO SUPABASE
# ============================================================

SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://ptxtclyfwlcwqgwzqieu.supabase.co"
).rstrip("/")

SUPABASE_KEY = os.getenv(
    "SUPABASE_PUBLISHABLE_KEY"
)

SUPABASE_TABLE = os.getenv(
    "SUPABASE_TABLE",
    "patentes"
)


# ============================================================
# HEADERS / REQUISIÇÕES
# ============================================================

def _headers(prefer: Optional[str] = None) -> Dict[str, str]:

    if not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_PUBLISHABLE_KEY não configurada. "
            "Configure essa variável nos Secrets do Streamlit."
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

    if (
        "software" in chave
        or "programa" in chave
    ):
        return "Software"

    if (
        "desenho" in chave
        or chave in {
            "di",
            "desenho_industrial",
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

        return (
            pd.to_datetime(
                str(valor).strip(),
                dayfirst=True,
                errors="raise"
            )
            .date()
            .isoformat()
        )

    except Exception:

        return str(valor).strip() or None


def _normalizar_status(status: Any) -> str:

    status = _valor_limpo(status)

    if not status:
        return "Ativo"

    chave = _normalizar_texto(status)

    mapa = {
        "patente_concedida":
            "Patente Concedida",

        "concedido":
            "Patente Concedida",

        "concessao":
            "Patente Concedida",

        "tramitando_normal":
            "Tramitando Normal",

        "indeferimento":
            "Indeferimento",

        "infederimento":
            "Indeferimento",

        "recurso_contra_indeferimento":
            "Recurso contra indeferimento",

        "pedido_de_exame":
            "Pedido de exame",

        "transferida_a_titularidade":
            "Transferida a titularidade",

        "arquivado":
            "Arquivado",

        "desistencia":
            "Desistência",
    }

    return mapa.get(
        chave,
        str(status).strip()
    )


# ============================================================
# PREPARAÇÃO DOS DADOS
# ============================================================

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


def _preparar_patentes(
    df: pd.DataFrame
) -> pd.DataFrame:

    if df.empty:
        return df

    aliases = {

        "numero_patente": (
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

        "modalidade_pi": (
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
    }

    for destino, nomes in aliases.items():

        if destino in df.columns:
            continue

        origem = _coluna_existente(
            df,
            *nomes
        )

        if origem:
            df[destino] = df[origem]

        else:
            df[destino] = None

    if "id" not in df.columns:
        df["id"] = range(
            1,
            len(df) + 1
        )

    df["modalidade_pi"] = (
        df["modalidade_pi"]
        .apply(normalizar_modalidade)
    )

    df["status"] = (
        df["status"]
        .fillna("Ativo")
        .replace("", "Ativo")
    )

    return df


# ============================================================
# INICIALIZAÇÃO
# ============================================================

def init_database() -> None:

    # Apenas testa a conexão.
    obter_patentes()


# ============================================================
# PATENTES
# ============================================================

def obter_patentes() -> pd.DataFrame:

    data = _request(
        "GET",
        f"{_endpoint()}?select=*&order=id.asc",
        headers=_headers(),
    )

    df = pd.DataFrame(
        data or []
    )

    return _preparar_patentes(df)


def _patente_url(
    patente_id: Any
) -> str:

    return (
        f"{_endpoint()}"
        f"?id=eq."
        f"{quote(str(patente_id), safe='')}"
    )


def _payload_patente(
    dados: Dict[str, Any]
) -> Dict[str, Any]:

    payload = {

        "numero_patente":
            dados.get("numero"),

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
            dados.get("gestor"),

        "status":
            _normalizar_status(
                dados.get("status_patente")
            ),

        "titulo":
            dados.get("titulo"),

        "inventores":
            dados.get("inventores"),

        "campus":
            dados.get("campus"),

        "atributos":
            dados.get("atributos"),

        "id_externo":
            dados.get("id_externo"),

        "modalidade_pi":
            normalizar_modalidade(
                dados.get("modalidade_pi")
            ),

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

        "acordo_titularidade":
            dados.get("acordo_titularidade"),

        "procuracao":
            dados.get("procuracao"),

        "termo_cessao":
            dados.get("termo_cessao"),

        "ipc_classificacao":
            dados.get("ipc_classificacao"),
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

    inicio = pd.to_datetime(
        data_dep
    )

    modalidade = normalizar_modalidade(
        modalidade_pi
    )

    if modalidade == "Software":

        itens = [
            (
                1,
                "Taxa única de depósito",
                0
            )
        ]

    elif modalidade == "Desenho Industrial":

        itens = [
            (
                1,
                "Taxa de depósito",
                0
            )
        ]

        itens += [
            (
                i + 1,
                f"{i}º quinquênio",
                i * 5
            )
            for i in range(1, 5)
        ]

    else:

        itens = [
            (
                i,
                f"{i}ª anuidade",
                i - 1
            )
            for i in range(1, 21)
        ]

    cronograma = []

    for numero, descricao, anos in itens:

        ini_ord = (
            inicio
            + pd.DateOffset(
                years=anos
            )
        )

        fim_ord = (
            ini_ord
            + pd.DateOffset(
                months=3
            )
        )

        ini_ext = (
            fim_ord
            + pd.DateOffset(
                days=1
            )
        )

        fim_ext = (
            ini_ext
            + pd.DateOffset(
                months=6
            )
        )

        cronograma.append(
            {
                "numero_anuidade":
                    numero,

                "descricao_pagamento":
                    descricao,

                "data_inicio_ordinario":
                    ini_ord.date().isoformat(),

                "data_fim_ordinario":
                    fim_ord.date().isoformat(),

                "data_inicio_extraordinario":
                    ini_ext.date().isoformat(),

                "data_fim_extraordinario":
                    fim_ext.date().isoformat(),

                "data_pagamento":
                    None,

                "status":
                    "pendente",

                "modalidade_pi":
                    modalidade,
            }
        )

    return cronograma


# ============================================================
# GARANTIR CRONOGRAMA NO SUPABASE
# ============================================================

def garantir_pagamentos_existentes(
    patente_id: Any
) -> None:

    patente_url = (
        f"{_endpoint()}"
        f"?select=id,data_deposito,modalidade_pi"
        f"&id=eq.{quote(str(patente_id), safe='')}"
    )

    patente = _request(
        "GET",
        patente_url,
        headers=_headers(),
    )

    if not patente:
        return

    pi = patente[0]

    if not pi.get("data_deposito"):
        return

    modalidade = pi.get(
        "modalidade_pi",
        "Patente"
    )

    # Verifica se já existem pagamentos.
    url = (
        f"{_endpoint('anuidades')}"
        f"?select=id"
        f"&patente_id=eq.{quote(str(patente_id), safe='')}"
        f"&limit=1"
    )

    existentes = _request(
        "GET",
        url,
        headers=_headers(),
    )

    if existentes:
        return

    cronograma = _calcular_cronograma(
        pi["data_deposito"],
        modalidade
    )

    registros = []

    for pagamento in cronograma:

        registros.append(
            {
                "patente_id":
                    patente_id,

                "numero_anuidade":
                    pagamento["numero_anuidade"],

                "descricao_pagamento":
                    pagamento["descricao_pagamento"],

                "data_inicio_ordinario":
                    pagamento[
                        "data_inicio_ordinario"
                    ],

                "data_fim_ordinario":
                    pagamento[
                        "data_fim_ordinario"
                    ],

                "data_inicio_extraordinario":
                    pagamento[
                        "data_inicio_extraordinario"
                    ],

                "data_fim_extraordinario":
                    pagamento[
                        "data_fim_extraordinario"
                    ],

                "data_pagamento":
                    None,

                "status":
                    "pendente",

                "modalidade_pi":
                    modalidade,
            }
        )

    if registros:

        _request(
            "POST",
            _endpoint("anuidades"),
            headers=_headers("return=minimal"),
            json=registros,
        )


# ============================================================
# ADICIONAR PATENTE
# ============================================================

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

        resultado = _request(
            "POST",
            _endpoint(),
            headers=_headers(
                "return=representation"
            ),
            json=_payload_patente(
                locals()
            ),
        )

        patente_id = None

        if resultado:

            if isinstance(resultado, list):

                patente_id = resultado[0].get(
                    "id"
                )

            elif isinstance(resultado, dict):

                patente_id = resultado.get(
                    "id"
                )

        if patente_id:

            garantir_pagamentos_existentes(
                patente_id
            )

        return (
            True,
            "PI cadastrada com sucesso no Supabase."
        )

    except Exception as exc:

        return (
            False,
            f"Erro ao cadastrar PI: {exc}"
        )


# ============================================================
# ATUALIZAR PATENTE
# ============================================================

def atualizar_patente(
    patente_id: Any,
    **dados: Any
) -> Tuple[bool, str]:

    try:

        _request(
            "PATCH",
            _patente_url(
                patente_id
            ),
            headers=_headers(
                "return=minimal"
            ),
            json=_payload_patente(
                dados
            ),
        )

        # Se o cronograma ainda não existir,
        # cria automaticamente.
        garantir_pagamentos_existentes(
            patente_id
        )

        return (
            True,
            "PI atualizada com sucesso no Supabase."
        )

    except Exception as exc:

        return (
            False,
            f"Erro ao atualizar PI: {exc}"
        )


# ============================================================
# IMPORTAÇÃO
# ============================================================

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
            (
                f"{_endpoint()}"
                f"?select=id"
                f"&numero_patente=eq.{numero}"
                f"&limit=1"
            ),
            headers=_headers(),
        )

        payload = _payload_patente(
            dados
        )

        if existente:

            patente_id = existente[0]["id"]

            _request(
                "PATCH",
                _patente_url(
                    patente_id
                ),
                headers=_headers(
                    "return=minimal"
                ),
                json=payload,
            )

            garantir_pagamentos_existentes(
                patente_id
            )

            return (
                True,
                "PI existente atualizada no Supabase."
            )

        resultado = _request(
            "POST",
            _endpoint(),
            headers=_headers(
                "return=representation"
            ),
            json=payload,
        )

        patente_id = None

        if resultado:

            if isinstance(resultado, list):

                patente_id = resultado[0].get(
                    "id"
                )

            elif isinstance(resultado, dict):

                patente_id = resultado.get(
                    "id"
                )

        if patente_id:

            garantir_pagamentos_existentes(
                patente_id
            )

        return (
            True,
            "Nova PI importada para o Supabase."
        )

    except Exception as exc:

        return (
            False,
            str(exc)
        )


# ============================================================
# OBTER ANUIDADES / PAGAMENTOS
# ============================================================

def obter_anuidades(
    patente_id: Any
) -> pd
```
