import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st


# ============================================================
# CONFIGURAÇÃO DO SUPABASE
# ============================================================

def _get_secret(nome: str, padrao: Any = None) -> Any:
    """
    Procura uma configuração primeiro nas variáveis de ambiente
    e depois nos Secrets do Streamlit.
    """
    valor = os.getenv(nome)

    if valor:
        return valor

    try:
        valor = st.secrets.get(nome)
        if valor:
            return valor
    except Exception:
        pass

    return padrao


SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_KEY = (
    _get_secret("SUPABASE_KEY")
    or _get_secret("SUPABASE_PUBLISHABLE_KEY")
    or _get_secret("SUPABASE_ANON_KEY")
)

if SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.rstrip("/")


TIMEOUT = 30


# ============================================================
# CONFIGURAÇÃO DAS TABELAS
# ============================================================

TABELA_PATENTES = "patentes"
TABELA_ANUIDADES = "anuidades"


# ============================================================
# FUNÇÕES BÁSICAS DO SUPABASE
# ============================================================

def _verificar_configuracao() -> None:
    if not SUPABASE_URL:
        raise RuntimeError(
            "SUPABASE_URL não está configurada nos Secrets do Streamlit."
        )

    if not SUPABASE_KEY:
        raise RuntimeError(
            "SUPABASE_PUBLISHABLE_KEY não está configurada "
            "nos Secrets do Streamlit."
        )


def _url(tabela: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{tabela}"


def _headers(prefer: Optional[str] = None) -> Dict[str, str]:

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }

    if prefer:
        headers["Prefer"] = prefer

    return headers


def _tratar_resposta(response: requests.Response) -> Any:

    if response.ok:

        if not response.text:
            return None

        try:
            return response.json()
        except Exception:
            return response.text

    raise RuntimeError(
        f"Erro Supabase HTTP {response.status_code}: "
        f"{response.text}"
    )


# ============================================================
# INICIALIZAÇÃO / TESTE
# ============================================================

def init_database() -> None:
    """
    Mantém compatibilidade com o app.py.

    O banco é o Supabase.
    Não existe mais banco SQLite local.
    """

    _verificar_configuracao()

    response = requests.get(
        _url(TABELA_PATENTES),
        headers=_headers(),
        params={
            "select": "id",
            "limit": "1",
        },
        timeout=TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"Não foi possível conectar ao Supabase: "
            f"{response.status_code} - {response.text}"
        )


def testar_conexao() -> bool:

    try:
        init_database()
        return True
    except Exception:
        return False


# ============================================================
# LIMPEZA E CONVERSÃO DE VALORES
# ============================================================

def _valor_limpo(valor: Any) -> Optional[Any]:
    """
    Converte valores vazios para None.

    No JSON enviado ao Supabase, None vira NULL no PostgreSQL.
    """

    if valor is None:
        return None

    try:
        if pd.isna(valor):
            return None
    except Exception:
        pass

    if isinstance(valor, str):

        valor = valor.strip()

        if valor == "":
            return None

        if valor.lower() in {
            "nan",
            "none",
            "null",
            "nat",
            "n/a",
            "na",
        }:
            return None

    return valor


def _parse_data(valor: Any) -> Optional[str]:

    valor = _valor_limpo(valor)

    if valor is None:
        return None

    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%Y-%m-%d")

    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")

    if isinstance(valor, date):
        return valor.strftime("%Y-%m-%d")

    if isinstance(valor, str):

        formatos = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y/%m/%d",
        ]

        for formato in formatos:
            try:
                return datetime.strptime(
                    valor,
                    formato
                ).strftime("%Y-%m-%d")
            except ValueError:
                pass

    try:

        data = pd.to_datetime(
            valor,
            errors="coerce"
        )

        if pd.isna(data):
            return None

        return data.strftime("%Y-%m-%d")

    except Exception:

        return None


def _parse_int(valor: Any) -> Optional[int]:

    valor = _valor_limpo(valor)

    if valor is None:
        return None

    try:
        return int(float(valor))
    except Exception:
        return None


# ============================================================
# PATENTES
# ============================================================

def _preparar_patentes(dados: List[Dict[str, Any]]) -> pd.DataFrame:

    if not dados:
        return pd.DataFrame()

    df = pd.DataFrame(dados)

    # --------------------------------------------------------
    # Tradução dos nomes do banco para os nomes usados pelo app
    # --------------------------------------------------------

    mapa = {
        "id": "id",
        "pedido": "numero_patente",
        "data_deposito": "data_deposito",
        "data_concessao": "data_concessao",
        "resumo": "descricao",
        "depositante_titular": "titular",
        "gestor": "gestor",
        "status": "status",
        "titulo": "titulo",
        "nome_inventores": "inventores",
        "modalidade_pi": "modalidade_pi",
        "ano": "ano",
        "data_publicacao": "data_publicacao",
        "data_exame": "data_exame",
        "acordo_titularidade": "acordo_titularidade",
        "ipc_classificacao": "ipc_classificacao",
        "linguagem": "linguagem",
        "campo_aplicacao": "campo_aplicacao",
        "tipo_programa": "tipo_programa",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }

    df = df.rename(columns=mapa)

    colunas = [
        "id",
        "numero_patente",
        "data_deposito",
        "data_concessao",
        "descricao",
        "titular",
        "gestor",
        "status",
        "titulo",
        "inventores",
        "modalidade_pi",
        "ano",
        "data_publicacao",
        "data_exame",
        "acordo_titularidade",
        "ipc_classificacao",
        "linguagem",
        "campo_aplicacao",
        "tipo_programa",
        "created_at",
        "updated_at",
    ]

    for coluna in colunas:

        if coluna not in df.columns:
            df[coluna] = None

    return df[colunas]


def obter_patentes() -> pd.DataFrame:

    _verificar_configuracao()

    response = requests.get(
        _url(TABELA_PATENTES),
        headers=_headers(),
        params={
            "select": "*",
            "order": "id.asc",
        },
        timeout=TIMEOUT,
    )

    dados = _tratar_resposta(response)

    if not dados:
        return pd.DataFrame()

    return _preparar_patentes(dados)


def obter_patente_por_id(patente_id: int) -> Optional[Dict[str, Any]]:

    _verificar_configuracao()

    response = requests.get(
        _url(TABELA_PATENTES),
        headers=_headers(),
        params={
            "id": f"eq.{patente_id}",
            "select": "*",
            "limit": "1",
        },
        timeout=TIMEOUT,
    )

    dados = _tratar_resposta(response)

    if not dados:
        return None

    return dados[0]


# ============================================================
# PAYLOAD DE PATENTE
# ============================================================

def _payload_patente(
    numero_patente=None,
    data_deposito=None,
    data_concessao=None,
    descricao=None,
    titular=None,
    gestor=None,
    status=None,
    titulo=None,
    inventores=None,
    modalidade_pi=None,
    ano=None,
    data_publicacao=None,
    data_exame=None,
    acordo_titularidade=None,
    ipc_classificacao=None,
    linguagem=None,
    campo_aplicacao=None,
    tipo_programa=None,
) -> Dict[str, Any]:

    return {
        "pedido": _valor_limpo(numero_patente),
        "data_deposito": _parse_data(data_deposito),
        "data_concessao": _parse_data(data_concessao),
        "resumo": _valor_limpo(descricao),
        "depositante_titular": _valor_limpo(titular),
        "gestor": _valor_limpo(gestor),
        "status": _valor_limpo(status),
        "titulo": _valor_limpo(titulo),
        "nome_inventores": _valor_limpo(inventores),
        "modalidade_pi": _valor_limpo(modalidade_pi),
        "ano": _parse_int(ano),
        "data_publicacao": _parse_data(data_publicacao),
        "data_exame": _parse_data(data_exame),
        "acordo_titularidade": _valor_limpo(acordo_titularidade),
        "ipc_classificacao": _valor_limpo(ipc_classificacao),
        "linguagem": _valor_limpo(linguagem),
        "campo_aplicacao": _valor_limpo(campo_aplicacao),
        "tipo_programa": _valor_limpo(tipo_programa),
    }


# ============================================================
# ADICIONAR PATENTE
# ============================================================

def adicionar_patente(
    numero_patente=None,
    data_deposito=None,
    data_concessao=None,
    descricao=None,
    titular=None,
    gestor=None,
    status=None,
    titulo=None,
    inventores=None,
    modalidade_pi=None,
    ano=None,
    data_publicacao=None,
    data_exame=None,
    acordo_titularidade=None,
    ipc_classificacao=None,
    linguagem=None,
    campo_aplicacao=None,
    tipo_programa=None,
) -> Dict[str, Any]:

    _verificar_configuracao()

    payload = _payload_patente(
        numero_patente,
        data_deposito,
        data_concessao,
        descricao,
        titular,
        gestor,
        status,
        titulo,
        inventores,
        modalidade_pi,
        ano,
        data_publicacao,
        data_exame,
        acordo_titularidade,
        ipc_classificacao,
        linguagem,
        campo_aplicacao,
        tipo_programa,
    )

    response = requests.post(
        _url(TABELA_PATENTES),
        headers=_headers("return=representation"),
        json=payload,
        timeout=TIMEOUT,
    )

    dados = _tratar_resposta(response)

    if not dados:
        raise RuntimeError(
            "O Supabase não retornou a patente criada."
        )

    patente = dados[0]

    patente_id = patente.get("id")

    if patente_id is not None:
        garantir_pagamentos_existentes(patente_id)

    return patente


# ============================================================
# ATUALIZAR PATENTE
# ============================================================

def atualizar_patente(
    patente_id,
    numero_patente=None,
    data_deposito=None,
    data_concessao=None,
    descricao=None,
    titular=None,
    gestor=None,
    status=None,
    titulo=None,
    inventores=None,
    modalidade_pi=None,
    ano=None,
    data_publicacao=None,
    data_exame=None,
    acordo_titularidade=None,
    ipc_classificacao=None,
    linguagem=None,
    campo_aplicacao=None,
    tipo_programa=None,
) -> Dict[str, Any]:

    _verificar_configuracao()

    payload = _payload_patente(
        numero_patente,
        data_deposito,
        data_concessao,
        descricao,
        titular,
        gestor,
        status,
        titulo,
        inventores,
        modalidade_pi,
        ano,
        data_publicacao,
        data_exame,
        acordo_titularidade,
        ipc_classificacao,
        linguagem,
        campo_aplicacao,
        tipo_programa,
    )

    response = requests.patch(
        _url(TABELA_PATENTES),
        headers=_headers("return=representation"),
        params={
            "id": f"eq.{patente_id}",
        },
        json=payload,
        timeout=TIMEOUT,
    )

    dados = _tratar_resposta(response)

    if not dados:
        raise RuntimeError(
            "Nenhuma patente foi atualizada."
        )

    garantir_pagamentos_existentes(patente_id)

    return dados[0]


# ============================================================
# EXCLUIR PATENTE
# ============================================================

def excluir_patente(patente_id: int) -> bool:

    _verificar_configuracao()

    # Primeiro excluímos as anuidades.
    response_anuidades = requests.delete(
        _url(TABELA_ANUIDADES),
        headers=_headers(),
        params={
            "patente_id": f"eq.{patente_id}",
        },
        timeout=TIMEOUT,
    )

    if not response_anuidades.ok:
        raise RuntimeError(
            "Erro ao excluir as anuidades: "
            f"{response_anuidades.text}"
        )

    response = requests.delete(
        _url(TABELA_PATENTES),
        headers=_headers(),
        params={
            "id": f"eq.{patente_id}",
        },
        timeout=TIMEOUT,
    )

    return response.ok


# ============================================================
# CRONOGRAMA DE PAGAMENTOS
# ============================================================

def _calcular_cronograma(
    patente: Dict[str, Any]
) -> List[Dict[str, Any]]:

    patente_id = patente.get("id")

    modalidade = (
        patente.get("modalidade_pi")
        or ""
    ).strip().lower()

    data_deposito = _parse_data(
        patente.get("data_deposito")
    )

    if not data_deposito:
        return []

    data_dep = datetime.strptime(
        data_deposito,
        "%Y-%m-%d"
    ).date()

    cronograma = []

    # --------------------------------------------------------
    # SOFTWARE
    # --------------------------------------------------------

    if "software" in modalidade or "programa" in modalidade:

        cronograma.append({
            "patente_id": patente_id,
            "numero_anuidade": 1,
            "status": "PENDENTE",
            "data_pagamento": None,
            "descricao_pagamento": "Taxa única de depósito",
            "data_inicio_ordinario": data_dep.isoformat(),
            "data_fim_ordinario": data_dep.isoformat(),
            "data_inicio_extraordinario": None,
            "data_fim_extraordinario": None,
            "modalidade_pi": patente.get("modalidade_pi"),
        })

        return cronograma

    # --------------------------------------------------------
    # DESENHO INDUSTRIAL
    # --------------------------------------------------------

    if (
        "desenho" in modalidade
        or "modelo" in modalidade
    ):

        # Depósito inicial
        cronograma.append({
            "patente_id": patente_id,
            "numero_anuidade": 1,
            "status": "PENDENTE",
            "data_pagamento": None,
            "descricao_pagamento": "Depósito inicial",
            "data_inicio_ordinario": data_dep.isoformat(),
            "data_fim_ordinario": data_dep.isoformat(),
            "data_inicio_extraordinario": None,
            "data_fim_extraordinario": None,
            "modalidade_pi": patente.get("modalidade_pi"),
        })

        # 4 quinquênios
        for numero in range(2, 6):

            inicio = data_dep.replace(
                year=data_dep.year + ((numero - 1) * 5)
            )

            fim = inicio + timedelta(days=365)

            cronograma.append({
                "patente_id": patente_id,
                "numero_anuidade": numero,
                "status": "PENDENTE",
                "data_pagamento": None,
                "descricao_pagamento": f"{numero - 1}º quinquênio",
                "data_inicio_ordinario": inicio.isoformat(),
                "data_fim_ordinario": fim.isoformat(),
                "data_inicio_extraordinario": (
                    fim + timedelta(days=1)
                ).isoformat(),
                "data_fim_extraordinario": (
                    fim + timedelta(days=60)
                ).isoformat(),
                "modalidade_pi": patente.get("modalidade_pi"),
            })

        return cronograma

    # --------------------------------------------------------
    # PATENTE
    # --------------------------------------------------------

    # 20 anuidades
    for numero in range(1, 21):

        # A primeira anuidade começa no aniversário do depósito.
        inicio = data_dep.replace(
            year=data_dep.year + numero
        )

        fim = inicio + timedelta(days=365)

        inicio_extra = fim + timedelta(days=1)
        fim_extra = fim + timedelta(days=180)

        cronograma.append({
            "patente_id": patente_id,
            "numero_anuidade": numero,
            "status": "PENDENTE",
            "data_pagamento": None,
            "descricao_pagamento": f"{numero}ª anuidade",
            "data_inicio_ordinario": inicio.isoformat(),
            "data_fim_ordinario": fim.isoformat(),
            "data_inicio_extraordinario": inicio_extra.isoformat(),
            "data_fim_extraordinario": fim_extra.isoformat(),
            "modalidade_pi": patente.get("modalidade_pi"),
        })

    return cronograma


# ============================================================
# GARANTIR CRONOGRAMA NO SUPABASE
# ============================================================

def garantir_pagamentos_existentes(
    patente_id: int
) -> None:
    """
    Garante que o cronograma de pagamentos exista no Supabase.

    IMPORTANTE:
    O campo 'id' NÃO é enviado.
    O PostgreSQL gera automaticamente usando a sequence.
    """

    _verificar_configuracao()

    patente = obter_patente_por_id(patente_id)

    if not patente:
        return

    cronograma = _calcular_cronograma(patente)

    if not cronograma:
        return

    # Verifica quais anuidades já existem.
    response = requests.get(
        _url(TABELA_ANUIDADES),
        headers=_headers(),
        params={
            "patente_id": f"eq.{patente_id}",
            "select": "numero_anuidade",
        },
        timeout=TIMEOUT,
    )

    existentes = _tratar_resposta(response)

    numeros_existentes = {
        int(item["numero_anuidade"])
        for item in (existentes or [])
        if item.get("numero_anuidade") is not None
    }

    faltantes = [
        item
        for item in cronograma
        if int(item["numero_anuidade"])
        not in numeros_existentes
    ]

    if not faltantes:
        return

    response = requests.post(
        _url(TABELA_ANUIDADES),
        headers=_headers(
            "return=minimal,resolution=ignore-duplicates"
        ),
        json=faltantes,
        timeout=TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            "Erro ao criar cronograma de anuidades: "
            f"{response.status_code} - {response.text}"
        )


# ============================================================
# OBTER ANUIDADES
# ============================================================

def obter_anuidades(
    patente_id: Optional[int] = None
) -> pd.DataFrame:

    _verificar_configuracao()

    if patente_id is not None:

        # Primeiro garante que o cronograma exista.
        garantir_pagamentos_existentes(patente_id)

        params = {
            "patente_id": f"eq.{patente_id}",
            "select": "*",
            "order": "numero_anuidade.asc",
        }

    else:

        # Garante cronograma para todas as PIs.
        patentes = obter_patentes()

        if not patentes.empty:

            for _, patente in patentes.iterrows():

                try:
                    garantir_pagamentos_existentes(
                        int(patente["id"])
                    )
                except Exception:
                    pass

        params = {
            "select": "*",
            "order": "numero_anuidade.asc",
        }

    response = requests.get(
        _url(TABELA_ANUIDADES),
        headers=_headers(),
        params=params,
        timeout=TIMEOUT,
    )

    dados = _tratar_resposta(response)

    if not dados:
        return pd.DataFrame()

    df = pd.DataFrame(dados)

    # --------------------------------------------------------
    # Calcula status automaticamente quando ainda estiver
    # pendente.
    # --------------------------------------------------------

    hoje = date.today()

    def calcular_status(row):

        status_atual = row.get("status")

        if status_atual:
            status_texto = str(status_atual).upper()

            if status_texto in {
                "PAGO",
                "PAGA",
                "QUITADO",
                "QUITADA",
            }:
                return "PAGO"

        data_fim = _parse_data(
            row.get("data_fim_ordinario")
        )

        data_fim_extra = _parse_data(
            row.get("data_fim_extraordinario")
        )

        if data_fim:

            fim = datetime.strptime(
                data_fim,
                "%Y-%m-%d"
            ).date()

            if hoje <= fim:
                return "PENDENTE"

        if data_fim_extra:

            fim_extra = datetime.strptime(
                data_fim_extra,
                "%Y-%m-%d"
            ).date()

            if hoje <= fim_extra:
                return "EM PRAZO EXTRAORDINÁRIO"

        return "VENCIDA"

    df["status_calculado"] = df.apply(
        calcular_status,
        axis=1
    )

    return df


# ============================================================
# ATUALIZAR PAGAMENTO DE ANUIDADE
# ============================================================

def atualizar_status_anuidade(
    patente_id: int,
    numero_anuidade: int,
    status: str,
    data_pagamento: Any = None,
    descricao_pagamento: Any = None,
) -> bool:

    _verificar_configuracao()

    payload = {
        "patente_id": int(patente_id),
        "numero_anuidade": int(numero_anuidade),
        "status": _valor_limpo(status),
        "data_pagamento": _parse_data(data_pagamento),
        "descricao_pagamento": _valor_limpo(
            descricao_pagamento
        ),
    }

    response = requests.post(
        _url(TABELA_ANUIDADES),
        headers=_headers(
            "return=representation,resolution=merge-duplicates"
        ),
        params={
            "on_conflict": "patente_id,numero_anuidade"
        },
        json=payload,
        timeout=TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            "Erro ao atualizar pagamento da anuidade: "
            f"{response.status_code} - {response.text}"
        )

    return True


# ============================================================
# IMPORTAÇÃO EXCEL
# ============================================================

def _mapear_coluna(
    colunas: List[str],
    nomes_possiveis: List[str]
) -> Optional[str]:

    normalizadas = {
        str(c).strip().lower(): c
        for c in colunas
    }

    for nome in nomes_possiveis:

        chave = nome.strip().lower()

        if chave in normalizadas:
            return normalizadas[chave]

    return None


def _normalizar_colunas_excel(
    df: pd.DataFrame
) -> pd.DataFrame:

    mapa = {}

    equivalencias = {

        "numero_patente": [
            "numero_patente",
            "número_patente",
            "pedido",
            "número do pedido",
            "numero do pedido",
            "nº pedido",
            "nº do pedido",
            "processo",
        ],

        "data_deposito": [
            "data_deposito",
            "data depósito",
            "data de depósito",
            "data_deposito",
        ],

        "data_concessao": [
            "data_concessao",
            "data concessao",
            "data concessão",
            "data de concessao",
            "data de concessão",
        ],

        "descricao": [
            "descricao",
            "descrição",
            "resumo",
        ],

        "titular": [
            "titular",
            "depositante_titular",
            "depositante",
            "depositante/titular",
        ],

        "gestor": [
            "gestor",
        ],

        "status": [
            "status",
            "situação",
            "situacao",
        ],

        "titulo": [
            "titulo",
            "título",
        ],

        "inventores": [
            "inventores",
            "nome_inventores",
            "nome dos inventores",
        ],

        "modalidade_pi": [
            "modalidade_pi",
            "modalidade",
            "modalidade pi",
            "tipo de propriedade intelectual",
        ],

        "ano": [
            "ano",
        ],

        "data_publicacao": [
            "data_publicacao",
            "data publicação",
            "data de publicação",
        ],

        "data_exame": [
            "data_exame",
            "data exame",
            "data de exame",
        ],

        "acordo_titularidade": [
            "acordo_titularidade",
            "acordo titularidade",
            "acordo de titularidade",
        ],

        "ipc_classificacao": [
            "ipc_classificacao",
            "ipc",
            "classificação ipc",
            "classificacao ipc",
        ],

        "linguagem": [
            "linguagem",
        ],

        "campo_aplicacao": [
            "campo_aplicacao",
            "campo aplicação",
            "campo de aplicação",
        ],

        "tipo_programa": [
            "tipo_programa",
            "tipo programa",
        ],
    }

    for destino, possibilidades in equivalencias.items():

        coluna = _mapear_coluna(
            list(df.columns),
            possibilidades
        )

        if coluna is not None:
            mapa[coluna] = destino

    return df.rename(columns=mapa)


def salvar_patente_importada(
    dados: Dict[str, Any]
) -> Dict[str, Any]:

    _verificar_configuracao()

    numero = _valor_limpo(
        dados.get("numero_patente")
    )

    if not numero:
        raise ValueError(
            "O número do pedido/patente é obrigatório."
        )

    payload = _payload_patente(
        numero_patente=dados.get("numero_patente"),
        data_deposito=dados.get("data_deposito"),
        data_concessao=dados.get("data_concessao"),
        descricao=dados.get("descricao"),
        titular=dados.get("titular"),
        gestor=dados.get("gestor"),
        status=dados.get("status"),
        titulo=dados.get("titulo"),
        inventores=dados.get("inventores"),
        modalidade_pi=dados.get("modalidade_pi"),
        ano=dados.get("ano"),
        data_publicacao=dados.get("data_publicacao"),
        data_exame=dados.get("data_exame"),
        acordo_titularidade=dados.get(
            "acordo_titularidade"
        ),
        ipc_classificacao=dados.get(
            "ipc_classificacao"
        ),
        linguagem=dados.get("linguagem"),
        campo_aplicacao=dados.get(
            "campo_aplicacao"
        ),
        tipo_programa=dados.get(
            "tipo_programa"
        ),
    )

    # --------------------------------------------------------
    # Verifica se já existe pelo número do pedido
    # --------------------------------------------------------

    response = requests.get(
        _url(TABELA_PATENTES),
        headers=_headers(),
        params={
            "pedido": f"eq.{numero}",
            "select": "*",
            "limit": "1",
        },
        timeout=TIMEOUT,
    )

    existentes = _tratar_resposta(response)

    # --------------------------------------------------------
    # ATUALIZA
    # --------------------------------------------------------

    if existentes:

        patente_id = existentes[0]["id"]

        response = requests.patch(
            _url(TABELA_PATENTES),
            headers=_headers("return=representation"),
            params={
                "id": f"eq.{patente_id}",
            },
            json=payload,
            timeout=TIMEOUT,
        )

        dados_retorno = _tratar_resposta(response)

        patente = (
            dados_retorno[0]
            if dados_retorno
            else existentes[0]
        )

    # --------------------------------------------------------
    # INSERE
    # --------------------------------------------------------

    else:

        response = requests.post(
            _url(TABELA_PATENTES),
            headers=_headers("return=representation"),
            json=payload,
            timeout=TIMEOUT,
        )

        dados_retorno = _tratar_resposta(response)

        if not dados_retorno:
            raise RuntimeError(
                "Supabase não retornou o registro inserido."
            )

        patente = dados_retorno[0]

    # --------------------------------------------------------
    # Garante cronograma
    # --------------------------------------------------------

    patente_id = patente.get("id")

    if patente_id is not None:

        garantir_pagamentos_existentes(
            int(patente_id)
        )

    return patente


def importar_excel(
    arquivo
) -> Dict[str, Any]:

    _verificar_configuracao()

    # --------------------------------------------------------
    # Lê Excel
    # --------------------------------------------------------

    try:
        df = pd.read_excel(arquivo)
    except Exception as e:
        raise RuntimeError(
            f"Não foi possível ler o arquivo Excel: {e}"
        )

    if df.empty:
        return {
            "total": 0,
            "inseridos": 0,
            "atualizados": 0,
            "erros": [],
            "dados": pd.DataFrame(),
        }

    # --------------------------------------------------------
    # Normaliza nomes das colunas
    # --------------------------------------------------------

    df = _normalizar_colunas_excel(df)

    resultados = []

    erros = []

    inseridos = 0
    atualizados = 0

    # --------------------------------------------------------
    # Processa cada linha
    # --------------------------------------------------------

    for indice, linha in df.iterrows():

        try:

            dados = {
                "numero_patente": _valor_limpo(
                    linha.get("numero_patente")
                ),

                "data_deposito": _parse_data(
                    linha.get("data_deposito")
                ),

                "data_concessao": _parse_data(
                    linha.get("data_concessao")
                ),

                "descricao": _valor_limpo(
                    linha.get("descricao")
                ),

                "titular": _valor_limpo(
                    linha.get("titular")
                ),

                "gestor": _valor_limpo(
                    linha.get("gestor")
                ),

                "status": _valor_limpo(
                    linha.get("status")
                ),

                "titulo": _valor_limpo(
                    linha.get("titulo")
                ),

                "inventores": _valor_limpo(
                    linha.get("inventores")
                ),

                "modalidade_pi": _valor_limpo(
                    linha.get("modalidade_pi")
                ),

                "ano": _parse_int(
                    linha.get("ano")
                ),

                "data_publicacao": _parse_data(
                    linha.get("data_publicacao")
                ),

                "data_exame": _parse_data(
                    linha.get("data_exame")
                ),

                "acordo_titularidade": _valor_limpo(
                    linha.get("acordo_titularidade")
                ),

                "ipc_classificacao": _valor_limpo(
                    linha.get("ipc_classificacao")
                ),

                "linguagem": _valor_limpo(
                    linha.get("linguagem")
                ),

                "campo_aplicacao": _valor_limpo(
                    linha.get("campo_aplicacao")
                ),

                "tipo_programa": _valor_limpo(
                    linha.get("tipo_programa")
                ),
            }

            numero = dados["numero_patente"]

            if not numero:
                raise ValueError(
                    "Número do pedido/patente vazio."
                )

            # Verifica existência antes de salvar.
            response = requests.get(
                _url(TABELA_PATENTES),
                headers=_headers(),
                params={
                    "pedido": f"eq.{numero}",
                    "select": "id",
                    "limit": "1",
                },
                timeout=TIMEOUT,
            )

            existentes = _tratar_resposta(response)

            salvar_patente_importada(dados)

            if existentes:
                atualizados += 1
            else:
                inseridos += 1

            resultados.append({
                "linha_excel": indice + 2,
                "pedido": numero,
                "resultado": (
                    "Atualizado"
                    if existentes
                    else "Inserido"
                ),
            })

        except Exception as e:

            erros.append({
                "linha_excel": indice + 2,
                "pedido": _valor_limpo(
                    linha.get("numero_patente")
                ),
                "erro": str(e),
            })

    return {
        "total": len(df),
        "inseridos": inseridos,
        "atualizados": atualizados,
        "erros": erros,
        "dados": pd.DataFrame(resultados),
    }


# ============================================================
# ANÁLISE DE INCONSISTÊNCIAS
# ============================================================

def analisar_inconsistencias_excel(
    arquivo
) -> List[str]:

    problemas = []

    try:
        df = pd.read_excel(arquivo)
    except Exception as e:
        return [
            f"Não foi possível ler o Excel: {e}"
        ]

    if df.empty:
        return ["A planilha está vazia."]

    df = _normalizar_colunas_excel(df)

    if "numero_patente" not in df.columns:

        problemas.append(
            "A planilha não possui uma coluna "
            "identificando o número do pedido/patente."
        )

    else:

        vazios = df["numero_patente"].isna().sum()

        vazios += (
            df["numero_patente"]
            .astype(str)
            .str.strip()
            .isin(["", "nan", "None"])
            .sum()
        )

        if vazios > 0:

            problemas.append(
                f"{vazios} linha(s) sem número do pedido/patente."
            )

        duplicados = (
            df["numero_patente"]
            .astype(str)
            .str.strip()
            .duplicated()
            .sum()
        )

        if duplicados > 0:

            problemas.append(
                f"{duplicados} número(s) de pedido duplicado(s) "
                "na planilha."
            )

    return problemas


# ============================================================
# FUNÇÕES DE COMPATIBILIDADE
# ============================================================

def inserir_patente(*args, **kwargs):
    return adicionar_patente(*args, **kwargs)


def atualizar_patente_por_id(*args, **kwargs):
    return atualizar_patente(*args, **kwargs)


def excluir_pi(patente_id):
    return excluir_patente(patente_id)
