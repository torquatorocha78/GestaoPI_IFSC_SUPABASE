import os
import re
import time
import unicodedata
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import requests

try:
    import streamlit as st
except Exception:  # pragma: no cover - permite testes fora do Streamlit
    st = None


# ============================================================
# CONFIGURAÇÃO SUPABASE
# ============================================================
def _segredo(nome: str, padrao: str = "") -> str:
    """Lê primeiro das variáveis de ambiente e, se não houver, do st.secrets."""
    valor = os.getenv(nome)
    if valor:
        return str(valor).strip()
    if st is not None:
        try:
            valor = st.secrets.get(nome)
            if valor:
                return str(valor).strip()
        except Exception:
            pass
    return padrao


# SUPABASE_URL pode ser informado como https://xxxx.supabase.co
# ou https://xxxx.supabase.co/rest/v1/ (corrigido automaticamente).
SUPABASE_URL = _segredo(
    "SUPABASE_URL",
    "https://ptxtclyfwlcwqgwzqieu.supabase.co",
).rstrip("/")

if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-len("/rest/v1")].rstrip("/")

SUPABASE_KEY = _segredo("SUPABASE_PUBLISHABLE_KEY")
SUPABASE_TABLE = _segredo("SUPABASE_TABLE", "patentes")
SUPABASE_ANUIDADES_TABLE = _segredo("SUPABASE_ANUIDADES_TABLE", "anuidades")
SUPABASE_HISTORICO_JURIDICO_TABLE = "historico_consultas_juridicas"

# PostgREST devolve no máximo 1000 linhas por requisição (padrão do Supabase).
# 40 PIs x 20 anuidades = 800 linhas, abaixo do limite.
_LOTE_IDS = 40

# Se o INSERT em anuidades for bloqueado (RLS, view, tipo errado...), não
# repetimos a tentativa a cada PI/recarga durante este intervalo.
_BLOQUEIO_SYNC_SEGUNDOS = 300
_bloqueio_sync: Dict[str, Any] = {"ate": 0.0, "mensagem": None}

# Colunas opcionais que o app consegue dispensar se não existirem no banco.
_COLUNAS_OPCIONAIS_ANUIDADES = {"descricao_pagamento", "modalidade_pi", "status"}
_colunas_ausentes: Dict[str, set] = {}


# ============================================================
# ERROS
# ============================================================
class SupabaseError(RuntimeError):
    """Erro HTTP do Supabase com código, mensagem e dica de correção."""

    def __init__(self, status_code: int, detalhe: Any, metodo: str, url: str):
        self.status_code = status_code
        self.detalhe = detalhe
        self.metodo = metodo
        self.tabela = _tabela_da_url(url)
        if isinstance(detalhe, dict):
            self.codigo = str(detalhe.get("code") or "")
            self.mensagem = str(detalhe.get("message") or detalhe)
        else:
            self.codigo = ""
            self.mensagem = str(detalhe)
        self.dica = _dica_erro(self)

        texto = (
            f"Supabase retornou {status_code} ({self.codigo or 'sem código'}) "
            f"em {metodo} /{self.tabela}: {self.mensagem}"
        )
        if isinstance(detalhe, dict):
            extra = detalhe.get("details") or detalhe.get("hint")
            if extra:
                texto += f" | {extra}"
        if self.dica:
            texto += f" → {self.dica}"
        super().__init__(texto)


def _tabela_da_url(url: str) -> str:
    try:
        return url.split("/rest/v1/", 1)[1].split("?", 1)[0]
    except Exception:
        return "?"


def _dica_erro(exc: "SupabaseError") -> str:
    codigo = exc.codigo
    msg = exc.mensagem.lower()
    if codigo == "PGRST204":
        return "a coluna informada não existe nessa tabela. Rode o script correcao_supabase.sql."
    if codigo in {"PGRST205", "42P01"}:
        return "a tabela não existe (ou o nome está diferente) no Supabase."
    if codigo == "42501" or exc.status_code in (401, 403) or "row-level security" in msg:
        return (
            "permissão negada (RLS). A chave publishable não tem policy de "
            "INSERT/UPDATE nessa tabela. Rode o bloco de policies do correcao_supabase.sql."
        )
    if codigo == "23502":
        return "existe coluna NOT NULL sem valor padrão que o app não envia."
    if codigo == "23503":
        return (
            "chave estrangeira inválida: patente_id não existe na tabela referenciada "
            "(verifique se a FK aponta para patentes e não para ativos_pi)."
        )
    if codigo == "23505":
        return (
            "registro duplicado: a anuidade já existe, mas não está visível para a "
            "chave publishable (falta policy de SELECT)."
        )
    if codigo == "22P02":
        return "tipo incompatível (ex.: patente_id é uuid numa tabela e bigint na outra)."
    if codigo in {"55000", "42809"} or "view" in msg:
        return "a tabela é uma VIEW e não aceita INSERT/UPDATE direto."
    return ""


def _supabase_error(response: requests.Response) -> str:
    # Mantida por compatibilidade com código antigo.
    try:
        detalhe = response.json()
    except Exception:
        detalhe = response.text
    return f"Supabase retornou {response.status_code}: {detalhe}"


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


def _py(valor: Any) -> Any:
    """Converte escalares numpy/pandas em tipos nativos do Python."""
    if valor is None or isinstance(valor, (str, bytes, bool, int, float)):
        return valor
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.date().isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if hasattr(valor, "item"):
        try:
            return valor.item()
        except Exception:
            pass
    return valor


def _json_seguro(valor: Any) -> Any:
    """Garante que o payload é serializável (sem numpy, NaN ou Timestamp)."""
    if isinstance(valor, dict):
        return {str(k): _json_seguro(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_json_seguro(v) for v in valor]
    valor = _py(valor)
    if isinstance(valor, float) and valor != valor:  # NaN
        return None
    return valor


def _request(method: str, url: str, **kwargs: Any) -> Any:
    if "json" in kwargs:
        kwargs["json"] = _json_seguro(kwargs["json"])

    try:
        response = requests.request(method, url, timeout=30, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(f"Não foi possível conectar ao Supabase: {exc}") from exc

    if response.status_code >= 400:
        try:
            detalhe = response.json()
        except Exception:
            detalhe = response.text
        raise SupabaseError(response.status_code, detalhe, method, url)

    if not response.text:
        return None

    try:
        return response.json()
    except Exception:
        return response.text


def _coluna_inexistente(exc: Exception) -> Optional[str]:
    if not isinstance(exc, SupabaseError) or exc.codigo != "PGRST204":
        return None
    achado = re.search(r"'([^']+)' column", exc.mensagem)
    return achado.group(1) if achado else None


def _sem_colunas(payload: Any, colunas: set) -> Any:
    if isinstance(payload, list):
        return [_sem_colunas(item, colunas) for item in payload]
    return {k: v for k, v in payload.items() if k not in colunas}


def _enviar_com_ajuste(method: str, url: str, prefer: str, payload: Any, tabela: str,
                       opcionais: set) -> Any:
    """Envia o payload; se o banco não tiver uma coluna opcional, remove-a e tenta de novo."""
    ausentes = _colunas_ausentes.setdefault(tabela, set())
    for _ in range(len(opcionais) + 1):
        try:
            return _request(
                method,
                url,
                headers=_headers(prefer),
                json=_sem_colunas(payload, ausentes),
            )
        except SupabaseError as exc:
            coluna = _coluna_inexistente(exc)
            if coluna and coluna in opcionais and coluna not in ausentes:
                ausentes.add(coluna)
                continue
            raise
    raise RuntimeError(f"Não foi possível ajustar o payload para a tabela {tabela}.")


# ============================================================
# NORMALIZAÇÃO
# ============================================================
def _normalizar_texto(valor: Any) -> str:
    valor = _valor_limpo(valor)
    texto = "" if valor is None else str(valor).strip().lower()
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
    """Retorna None para vazio/NaN e converte numpy/Timestamp para tipos nativos."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    valor = _py(valor)
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


def _int_ou_none(valor: Any) -> Optional[int]:
    valor = _valor_limpo(valor)
    if valor is None:
        return None
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _parse_data(valor: Any) -> Optional[str]:
    """Converte para AAAA-MM-DD. Retorna None se não for uma data válida."""
    valor = _valor_limpo(valor)
    if valor is None:
        return None

    texto = str(valor).strip()
    try:
        # Formato ISO (vindo do Supabase ou do date_input) não usa dayfirst.
        if re.match(r"^\d{4}-\d{2}-\d{2}", texto):
            return pd.to_datetime(texto[:10], format="%Y-%m-%d").date().isoformat()
        return pd.to_datetime(texto, dayfirst=True, errors="raise").date().isoformat()
    except Exception:
        return None


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
    _request(
        "GET",
        f"{_endpoint()}?select=id&limit=1",
        headers=_headers(),
    )


def obter_patentes() -> pd.DataFrame:
    data = _request(
        "GET",
        f"{_endpoint()}?select=*&order=id.asc",
        headers=_headers(),
    )
    return _preparar_patentes(pd.DataFrame(data or []))


def obter_patente(patente_id: Any) -> Optional[pd.Series]:
    """Busca uma única PI pelo id (1 requisição, em vez de baixar todas)."""
    data = _request(
        "GET",
        f"{_patente_url(patente_id)}&select=*&limit=1",
        headers=_headers(),
    ) or []
    df = _preparar_patentes(pd.DataFrame(data))
    return None if df.empty else df.iloc[0]


def _patente_url(patente_id: Any) -> str:
    return f"{_endpoint()}?id=eq.{quote(str(_py(patente_id)), safe='')}"


def _payload_patente(dados: Dict[str, Any]) -> Dict[str, Any]:
    gestor = dados.get("gestor")
    status = _normalizar_status(dados.get("status_patente", dados.get("status")))

    payload = {
        "numero_patente": dados.get("numero"),
        "data_deposito": _parse_data(dados.get("data_dep")),
        "data_concessao": _parse_data(dados.get("data_conc")),
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
        "ano": _int_ou_none(dados.get("ano")),
        "data_publicacao": _parse_data(dados.get("data_publicacao")),
        "data_exame": _parse_data(dados.get("data_exame")),
        "acordo_titularidade": dados.get("acordo_titularidade"),
        "procuracao": dados.get("procuracao"),
        "termo_cessao": dados.get("termo_cessao"),
        "ipc_classificacao": dados.get("ipc_classificacao"),
    }

    # O banco possui a coluna gerada "pagar". Não enviamos o valor;
    # o próprio Supabase calcula com gestor + status.
    limpo = {chave: _valor_limpo(valor) for chave, valor in payload.items()}
    if limpo.get("id_externo") is not None:
        limpo["id_externo"] = str(limpo["id_externo"])
    return limpo


# ============================================================
# CRONOGRAMA DE PAGAMENTOS
# ============================================================
def _calcular_cronograma(data_dep: Any, modalidade_pi: Any) -> List[Dict[str, Any]]:
    data_iso = _parse_data(data_dep)
    if not data_iso:
        return []

    inicio = pd.Timestamp(data_iso)
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
        f"?patente_id=eq.{quote(str(_py(patente_id)), safe='')}"
    )


def _buscar_anuidades_pi(patente_id: Any) -> List[Dict[str, Any]]:
    return _request(
        "GET",
        f"{_anuidades_patente_url(patente_id)}&select=*&order=numero_anuidade.asc",
        headers=_headers(),
    ) or []


_CAMPOS_CRONOGRAMA = (
    "descricao_pagamento",
    "data_inicio_ordinario",
    "data_fim_ordinario",
    "data_inicio_extraordinario",
    "data_fim_extraordinario",
    "modalidade_pi",
)


def _registro_difere(existente: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    for campo in _CAMPOS_CRONOGRAMA:
        if campo not in existente:
            continue  # coluna não existe no banco
        atual = _valor_limpo(existente.get(campo))
        novo = payload.get(campo)
        if campo.startswith("data_"):
            atual = _parse_data(atual)
        if atual != novo:
            return True
    return False


def _sync_bloqueado() -> Optional[str]:
    if _bloqueio_sync["mensagem"] and time.time() < _bloqueio_sync["ate"]:
        return _bloqueio_sync["mensagem"]
    return None


def _bloquear_sync(exc: Exception) -> None:
    # Erros de estrutura/permissão não se resolvem sozinhos: evita repetir a cada PI.
    if isinstance(exc, SupabaseError) and exc.status_code in (400, 401, 403, 404, 405, 409):
        _bloqueio_sync["mensagem"] = str(exc)
        _bloqueio_sync["ate"] = time.time() + _BLOQUEIO_SYNC_SEGUNDOS


def liberar_sincronizacao() -> None:
    """Permite nova tentativa de gravar cronogramas (após corrigir o banco)."""
    _bloqueio_sync["mensagem"] = None
    _bloqueio_sync["ate"] = 0.0
    _colunas_ausentes.clear()


def _sincronizar_anuidades(
    patente_id: Any,
    data_dep: Any,
    modalidade_pi: Any,
    existentes: Optional[List[Dict[str, Any]]] = None,
    atualizar_existentes: bool = True,
) -> None:
    """Cria/atualiza o cronograma na tabela anuidades sem apagar pagamentos já registrados.

    - Insere todas as parcelas faltantes em UMA requisição (antes eram até 20).
    - Só faz PATCH quando as datas/descrição realmente mudaram.
    - Nunca sobrescreve status/data_pagamento já registrados.
    """
    cronograma = _calcular_cronograma(data_dep, modalidade_pi)
    if not cronograma:
        return

    bloqueio = _sync_bloqueado()
    if bloqueio:
        raise RuntimeError(bloqueio)

    patente_id = _py(patente_id)
    if existentes is None:
        existentes = _buscar_anuidades_pi(patente_id)

    existentes_por_numero = {}
    for item in existentes:
        numero = _int_ou_none(item.get("numero_anuidade"))
        if numero is not None:
            existentes_por_numero[numero] = item

    tabela = SUPABASE_ANUIDADES_TABLE
    novos = []

    try:
        for item in cronograma:
            numero = int(item["numero_anuidade"])
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

            existente = existentes_por_numero.get(numero)
            if existente is None:
                novos.append({**payload, "status": "pendente"})
            elif atualizar_existentes and existente.get("id") is not None and _registro_difere(existente, payload):
                _enviar_com_ajuste(
                    "PATCH",
                    f"{_endpoint(tabela)}?id=eq.{quote(str(_py(existente['id'])), safe='')}",
                    "return=minimal",
                    payload,
                    tabela,
                    _COLUNAS_OPCIONAIS_ANUIDADES,
                )

        if novos:
            _enviar_com_ajuste(
                "POST",
                _endpoint(tabela),
                "return=minimal",
                novos,
                tabela,
                _COLUNAS_OPCIONAIS_ANUIDADES,
            )
    except Exception as exc:
        _bloquear_sync(exc)
        raise


def garantir_pagamentos_existentes() -> List[str]:
    """Garante que PIs existentes tenham seus cronogramas. Retorna os avisos de falha."""
    df = obter_patentes()
    if df.empty:
        return []
    mapa = obter_anuidades_lote(df)
    return avisos_anuidades(mapa)


def _sincronizar_apos_salvar(patente_id: Any, dados: Dict[str, Any]) -> Optional[str]:
    try:
        _sincronizar_anuidades(
            patente_id,
            dados.get("data_dep"),
            dados.get("modalidade_pi"),
        )
        return None
    except Exception as exc:
        return f"PI salva, mas o cronograma de pagamentos não foi gravado: {exc}"


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
    dados = dict(locals())
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
        aviso = _sincronizar_apos_salvar(patente_id, dados)
        if aviso:
            return True, aviso
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
    except Exception as exc:
        return False, f"Erro ao atualizar PI: {exc}"

    try:
        pi = obter_patente(patente_id)
        if pi is not None:
            data_dep = dados.get("data_dep") or pi.get("data_deposito")
            modalidade = dados.get("modalidade_pi") or pi.get("modalidade_pi")
            _sincronizar_anuidades(patente_id, data_dep, modalidade)
    except Exception as exc:
        return True, f"PI atualizada, mas o cronograma não foi sincronizado: {exc}"

    return True, "PI atualizada com sucesso no Supabase"


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
            aviso = _sincronizar_apos_salvar(patente_id, dados)
            return True, aviso or "PI existente atualizada no Supabase"

        resultado = _request(
            "POST",
            _endpoint(),
            headers=_headers("return=representation"),
            json=payload,
        )
        patente_id = resultado[0]["id"] if isinstance(resultado, list) else resultado["id"]
        aviso = _sincronizar_apos_salvar(patente_id, dados)
        return True, aviso or "Nova PI importada para o Supabase"
    except Exception as exc:
        return False, str(exc)


# ============================================================
# ANUIDADES / PAGAMENTOS
# ============================================================
def _status_calculado_anuidade(row: pd.Series) -> str:
    status_atual = str(_valor_limpo(row.get("status")) or "").lower()
    if status_atual == "nao_pagar":
        return "nao_pagar"
    # Atenção: NaN é "verdadeiro" em Python, por isso usar _valor_limpo.
    if _valor_limpo(row.get("data_pagamento")) or status_atual == "pago":
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


_COLUNAS_ANUIDADE = [
    "id",
    "patente_id",
    "numero_anuidade",
    "descricao_pagamento",
    "data_inicio_ordinario",
    "data_fim_ordinario",
    "data_inicio_extraordinario",
    "data_fim_extraordinario",
    "data_pagamento",
    "status",
    "modalidade_pi",
    "origem",
]


def _mesclar_cronograma(
    patente_id: Any,
    cronograma: List[Dict[str, Any]],
    registros: List[Dict[str, Any]],
) -> pd.DataFrame:
    """Une o cronograma calculado com o que está salvo no banco.

    O banco prevalece; o calculado preenche colunas ausentes/vazias.
    Parcelas fora do cronograma atual (ex.: modalidade alterada) são ignoradas.
    """
    linhas: Dict[int, Dict[str, Any]] = {
        int(c["numero_anuidade"]): {**c, "id": None, "patente_id": _py(patente_id), "origem": "calculado"}
        for c in cronograma
    }

    for registro in registros:
        numero = _int_ou_none(registro.get("numero_anuidade"))
        if numero is None:
            continue
        if linhas and numero not in linhas and cronograma:
            continue
        mesclado = dict(linhas.get(numero, {}))
        for chave, valor in registro.items():
            if _valor_limpo(valor) is not None or chave not in mesclado:
                mesclado[chave] = _valor_limpo(valor)
        mesclado["numero_anuidade"] = numero
        mesclado["origem"] = "supabase"
        linhas[numero] = mesclado

    df = pd.DataFrame([linhas[n] for n in sorted(linhas)])
    for coluna in _COLUNAS_ANUIDADE:
        if coluna not in df.columns:
            df[coluna] = None
    # Evita NaN (que é "verdadeiro") nas colunas de texto/data.
    return df.astype(object).where(pd.notna(df), None)


def _montar_anuidades_pi(
    pi: pd.Series,
    registros: List[Dict[str, Any]],
    erro_leitura: Optional[str] = None,
) -> pd.DataFrame:
    patente_id = _py(pi.get("id"))
    modalidade = normalizar_modalidade(pi.get("modalidade_pi"))
    cronograma = _calcular_cronograma(pi.get("data_deposito"), modalidade)
    aviso = erro_leitura

    if erro_leitura is None and cronograma:
        numeros_salvos = {_int_ou_none(r.get("numero_anuidade")) for r in registros}
        faltando = any(c["numero_anuidade"] not in numeros_salvos for c in cronograma)
        if faltando:
            try:
                _sincronizar_anuidades(
                    patente_id,
                    pi.get("data_deposito"),
                    modalidade,
                    existentes=registros,
                    atualizar_existentes=False,
                )
                registros = _buscar_anuidades_pi(patente_id)
            except Exception as exc:
                aviso = (
                    "O cronograma não pôde ser gravado no Supabase e está sendo "
                    f"exibido apenas calculado. Detalhe: {exc}"
                )

    if not cronograma and not registros:
        vazio = pd.DataFrame(columns=_COLUNAS_ANUIDADE)
        vazio.attrs["aviso"] = aviso
        return vazio

    resultado = _mesclar_cronograma(patente_id, cronograma, registros)

    if not _deve_pagar(pi.get("gestor"), pi.get("status")):
        resultado["status"] = "nao_pagar"
    else:
        resultado["status"] = resultado.apply(_status_calculado_anuidade, axis=1)

    resultado.attrs["aviso"] = aviso
    return resultado


def obter_anuidades(patente_id: Any, pi: Optional[pd.Series] = None) -> pd.DataFrame:
    """Cronograma de uma PI. Nunca derruba a página: em caso de falha na gravação,
    devolve o cronograma calculado e registra o motivo em df.attrs['aviso']."""
    if pi is None:
        pi = obter_patente(patente_id)
        if pi is None:
            return pd.DataFrame(columns=_COLUNAS_ANUIDADE)

    erro_leitura = None
    try:
        registros = _buscar_anuidades_pi(patente_id)
    except Exception as exc:
        registros = []
        erro_leitura = f"Não foi possível ler a tabela {SUPABASE_ANUIDADES_TABLE}: {exc}"

    return _montar_anuidades_pi(pi, registros, erro_leitura)


def obter_anuidades_lote(df_pis: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Cronogramas de várias PIs com poucas requisições.

    Retorna {str(id_da_pi): DataFrame}. Use chave_pi(pi['id']) para consultar.
    """
    resultado: Dict[str, pd.DataFrame] = {}
    if df_pis is None or df_pis.empty or "id" not in df_pis.columns:
        return resultado

    ids = [_py(i) for i in df_pis["id"].tolist() if _valor_limpo(i) is not None]
    registros_por_pi: Dict[str, List[Dict[str, Any]]] = {}
    erro_leitura = None

    try:
        for inicio in range(0, len(ids), _LOTE_IDS):
            bloco = ids[inicio:inicio + _LOTE_IDS]
            lista = ",".join(quote(str(i), safe="") for i in bloco)
            dados = _request(
                "GET",
                f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}?select=*"
                f"&patente_id=in.({lista})&order=patente_id.asc,numero_anuidade.asc",
                headers=_headers(),
            ) or []
            for item in dados:
                registros_por_pi.setdefault(chave_pi(item.get("patente_id")), []).append(item)
    except Exception as exc:
        erro_leitura = f"Não foi possível ler a tabela {SUPABASE_ANUIDADES_TABLE}: {exc}"

    for _, pi in df_pis.iterrows():
        chave = chave_pi(pi.get("id"))
        resultado[chave] = _montar_anuidades_pi(
            pi,
            registros_por_pi.get(chave, []),
            erro_leitura,
        )

    return resultado


def chave_pi(patente_id: Any) -> str:
    valor = _py(patente_id)
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor)


def avisos_anuidades(mapa_ou_df: Any) -> List[str]:
    """Lista de avisos únicos (erros reais do Supabase) gerados ao montar cronogramas."""
    if isinstance(mapa_ou_df, pd.DataFrame):
        frames = [mapa_ou_df]
    else:
        frames = list((mapa_ou_df or {}).values())
    vistos: List[str] = []
    for frame in frames:
        aviso = frame.attrs.get("aviso")
        if aviso and aviso not in vistos:
            vistos.append(aviso)
    return vistos


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

    patente_id_q = quote(str(_py(patente_id)), safe="")
    numero_q = quote(str(int(numero_anuidade)), safe="")
    url_busca = (
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}"
        f"?patente_id=eq.{patente_id_q}&numero_anuidade=eq.{numero_q}&limit=1"
    )

    existente = _request("GET", url_busca, headers=_headers()) or []

    if not existente:
        # Cria o cronograma se ainda não existir (sem respeitar o bloqueio: é ação do usuário).
        pi = obter_patente(patente_id)
        if pi is None:
            raise RuntimeError("PI não encontrada.")
        liberar_sincronizacao()
        _sincronizar_anuidades(patente_id, pi.get("data_deposito"), pi.get("modalidade_pi"))
        existente = _request("GET", url_busca, headers=_headers()) or []

    if not existente:
        raise RuntimeError(
            "Pagamento/anuidade não encontrado para esta PI. Se o registro existe no banco, "
            "verifique a policy de SELECT da tabela anuidades."
        )

    registro_id = existente[0]["id"]
    payload: Dict[str, Any] = {"status": status}

    if status == "pago":
        payload["data_pagamento"] = _parse_data(data_pagamento) or date.today().isoformat()
    else:
        payload["data_pagamento"] = None

    _request(
        "PATCH",
        f"{_endpoint(SUPABASE_ANUIDADES_TABLE)}?id=eq.{quote(str(_py(registro_id)), safe='')}",
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

    def valor(row, chave, conversor=_valor_limpo):
        return conversor(row.get(mapa[chave])) if mapa[chave] else None

    for idx, row in df.iterrows():
        numero = valor(row, "numero")
        data_dep = valor(row, "data_dep", _parse_data)

        if not numero or not data_dep:
            resultados.append(
                (str(numero or f"Linha {idx + 2}"), False, "Processo ou depósito ausente/inválido.")
            )
            continue

        dados = {
            "numero": str(numero).strip(),
            "data_dep": data_dep,
            "data_conc": valor(row, "data_conc", _parse_data),
            "descricao": valor(row, "descricao"),
            "titular": valor(row, "titular"),
            "gestor": valor(row, "gestor"),
            "status_patente": _normalizar_status(row.get(mapa["status"])) if mapa["status"] else "Ativo",
            "titulo": valor(row, "titulo"),
            "inventores": valor(row, "inventores"),
            "campus": valor(row, "campus"),
            "atributos": valor(row, "atributos"),
            "id_externo": valor(row, "id_externo"),
            "modalidade_pi": normalizar_modalidade(row.get(mapa["modalidade_pi"])) if mapa["modalidade_pi"] else "Patente",
            "ano": valor(row, "ano", _int_ou_none),
            "data_publicacao": valor(row, "data_publicacao", _parse_data),
            "data_exame": valor(row, "data_exame", _parse_data),
            "acordo_titularidade": valor(row, "acordo_titularidade"),
            "procuracao": valor(row, "procuracao"),
            "termo_cessao": valor(row, "termo_cessao"),
            "ipc_classificacao": valor(row, "ipc_classificacao"),
        }

        ok, msg = salvar_patente_importada(dados)
        resultados.append((dados["numero"], ok, msg))

    return resultados


def analisar_inconsistencias_excel(arquivo_excel) -> List[str]:
    try:
        df = pd.read_excel(arquivo_excel)
    except Exception as exc:
        return [f"Falha ao ler a planilha: {exc}"]

    colunas = {_normalizar_texto(col): col for col in df.columns}
    problemas = []

    if not any(c in colunas for c in ["processo", "numero_patente", "numero_de_patente", "patente"]):
        problemas.append("Coluna obrigatória 'Processo' não foi encontrada.")

    if not any(c in colunas for c in ["deposito", "data_deposito", "data_do_deposito"]):
        problemas.append("Coluna obrigatória 'Depósito' não foi encontrada.")

    if not any(c in colunas for c in ["modalidade_de_pi", "modalidade_pi", "modalidade", "tipo"]):
        problemas.append(
            "Coluna 'Modalidade de PI' não encontrada; os registros serão tratados como Patente."
        )

    return problemas


# ============================================================
# ASSISTENTE JURÍDICO NIT - HISTÓRICO NO SUPABASE
# ============================================================
def registrar_consulta_juridica(
    pergunta: str,
    resposta: str,
    documento_nome: Optional[str] = None,
    paginas: Optional[str] = None,
    fontes: Optional[List[Dict[str, Any]]] = None,
    ativo_pi_id: Any = None,
    modelo: Optional[str] = None,
) -> Tuple[bool, str]:
    """Grava uma consulta do Assistente Jurídico (tabela historico_consultas_juridicas)."""
    pergunta = str(pergunta or "").strip()
    resposta = str(resposta or "").strip()

    if not pergunta:
        return False, "Pergunta jurídica não informada."

    payload = {
        "pergunta": pergunta,
        "resposta": resposta,
        "documento_nome": _valor_limpo(documento_nome),
        "paginas": _valor_limpo(paginas),
        "fontes": fontes if fontes else [],
        "ativo_pi_id": _valor_limpo(ativo_pi_id),
        "modelo": _valor_limpo(modelo),
    }

    try:
        _request(
            "POST",
            _endpoint(SUPABASE_HISTORICO_JURIDICO_TABLE),
            headers=_headers("return=minimal"),
            json=payload,
        )
        return True, "Consulta jurídica registrada no histórico."
    except Exception as exc:
        return False, f"Não foi possível registrar o histórico: {exc}"


def obter_historico_consultas_juridicas(limite: int = 50) -> pd.DataFrame:
    """Retorna as consultas jurídicas mais recentes."""
    try:
        limite = max(1, min(int(limite), 200))
    except Exception:
        limite = 50

    url = (
        f"{_endpoint(SUPABASE_HISTORICO_JURIDICO_TABLE)}"
        f"?select=*&order=created_at.desc&limit={limite}"
    )
    registros = _request("GET", url, headers=_headers()) or []
    return pd.DataFrame(registros)


def obter_historico_consulta_juridica(consulta_id: Any) -> Optional[Dict[str, Any]]:
    """Recupera uma consulta específica do histórico."""
    consulta_id_q = quote(str(_py(consulta_id)), safe="")
    registros = _request(
        "GET",
        f"{_endpoint(SUPABASE_HISTORICO_JURIDICO_TABLE)}?id=eq.{consulta_id_q}&select=*&limit=1",
        headers=_headers(),
    ) or []
    return registros[0] if registros else None


def excluir_consulta_juridica(consulta_id: Any) -> Tuple[bool, str]:
    """Exclui uma consulta específica do histórico."""
    consulta_id_q = quote(str(_py(consulta_id)), safe="")
    try:
        _request(
            "DELETE",
            f"{_endpoint(SUPABASE_HISTORICO_JURIDICO_TABLE)}?id=eq.{consulta_id_q}",
            headers=_headers("return=minimal"),
        )
        return True, "Consulta removida do histórico."
    except Exception as exc:
        return False, f"Erro ao remover consulta: {exc}"


def buscar_contexto_ativo_pi(
    termo: Optional[str] = None,
    ativo_pi_id: Any = None,
    limite: int = 20,
) -> pd.DataFrame:
    """Busca a PI na MESMA tabela usada pelo app (patentes).

    Antes consultava 'ativos_pi' usando o id vindo de 'patentes', o que trazia
    a PI errada ou nada.
    """
    try:
        limite = max(1, min(int(limite), 100))
    except Exception:
        limite = 20

    if _valor_limpo(ativo_pi_id) is not None:
        filtro = f"id=eq.{quote(str(_py(ativo_pi_id)), safe='')}"
    else:
        termo = re.sub(r"[,()*]", " ", str(termo or "")).strip()
        if not termo:
            return pd.DataFrame()
        termo_q = quote(termo, safe="")
        filtro = (
            "or=("
            f"numero_patente.ilike.*{termo_q}*,"
            f"titulo.ilike.*{termo_q}*,"
            f"titular.ilike.*{termo_q}*,"
            f"inventores.ilike.*{termo_q}*,"
            f"gestor.ilike.*{termo_q}*"
            ")"
        )

    registros = _request(
        "GET",
        f"{_endpoint()}?select=*&{filtro}&limit={limite}",
        headers=_headers(),
    ) or []
    return _preparar_patentes(pd.DataFrame(registros))


def obter_obrigacoes_ativo(ativo_pi_id: Any, limite: int = 100) -> pd.DataFrame:
    """Obrigações financeiras da PI = cronograma da tabela anuidades."""
    df = obter_anuidades(ativo_pi_id)
    try:
        limite = max(1, min(int(limite), 200))
    except Exception:
        limite = 100
    return df.head(limite)
