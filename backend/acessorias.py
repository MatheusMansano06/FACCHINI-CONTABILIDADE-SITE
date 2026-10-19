"""Cliente fino para a API da Acessórias (api.acessorias.com).

Cada função corresponde a um recurso realmente usado pelo portal — não é
um wrapper genérico de toda a API. Erros de rede/timeout/formato nunca
sobem como exceção: devolvem None (item único) ou lista vazia (listagem),
com o erro registrado no log. Uma falha da Acessórias não pode derrubar a
página inteira do portal, só a seção que dependia daquele dado.

Todas as chamadas são assíncronas (httpx.AsyncClient) — o backend serve
várias pessoas ao mesmo tempo, e uma chamada de rede síncrona aqui dentro
travaria o processo inteiro até a Acessórias responder, deixando todo
mundo esperando na fila por causa de uma pessoa só.

Respostas ficam em cache por CACHE_TTL_SEGUNDOS: sem isso, clicar entre
Início e Documentos repetia as mesmas chamadas à Acessórias toda vez,
e cada clique esperava a rede de novo — por isso a navegação parecia
lenta.

Medido direto contra a Acessórias (não é limite de requisição nosso nem
delas — não aparece nenhum 429 no log): cada chamada individual varia
de ~0.2s a ~5s dependendo do recurso e do momento, mesmo em paralelo.
Isso é fora do nosso controle (é a latência do servidor deles, não do
nosso código) — o que dá pra controlar é not repetir essa espera a cada
clique. Por isso o cache subiu de 30s pra CACHE_TTL_SEGUNDOS: nenhum dos
dados aqui (vencimento, documento entregue, solicitação, boleto) muda de
minuto a minuto, então vale a troca de "alguns minutos de atraso" por
"não pagar de novo o preço de rede a cada navegação dentro da mesma
visita".
"""
import asyncio
import logging
import os
import time
from datetime import date, timedelta

import httpx

logger = logging.getLogger("acessorias")

BASE_URL = "https://api.acessorias.com"
TIMEOUT = 10.0
CACHE_TTL_SEGUNDOS = 180

_cliente: httpx.AsyncClient | None = None
_cache: dict[tuple, tuple[float, dict | list | None]] = {}


def _obter_cliente() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None:
        # Um cliente só, reaproveitado entre chamadas: mantém a conexão
        # HTTPS com a Acessórias aberta (keep-alive) em vez de negociar
        # TLS do zero a cada requisição — é a principal fonte de latência
        # evitável numa API externa.
        _cliente = httpx.AsyncClient(timeout=TIMEOUT)
    return _cliente


def _token() -> str | None:
    token = os.environ.get("ACESSORIAS_API_TOKEN")
    if not token:
        logger.warning("ACESSORIAS_API_TOKEN não definido — integração desligada.")
    return token


def _chave_cache(caminho: str, params: dict | None) -> tuple:
    return (caminho, tuple(sorted((params or {}).items())))


async def _get(caminho: str, params: dict | None = None, tentativas: int = 3) -> dict | list | None:
    chave = _chave_cache(caminho, params)
    agora = time.monotonic()
    em_cache = _cache.get(chave)
    if em_cache and agora < em_cache[0]:
        return em_cache[1]

    token = _token()
    if not token:
        return None

    for tentativa in range(tentativas):
        try:
            resposta = await _obter_cliente().get(
                f"{BASE_URL}{caminho}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            # 429 (limite de 100 req/min da Acessórias) não é erro pra
            # desistir na hora — uma pequena espera e tentar de novo resolve
            # a maioria dos casos, tanto numa página do portal sob carga
            # quanto num script em lote como indexar_contatos.py.
            if resposta.status_code == 429 and tentativa < tentativas - 1:
                espera = 5 * (tentativa + 1)
                logger.warning("Limite de requisições da Acessórias — esperando %ss e tentando de novo", espera)
                await asyncio.sleep(espera)
                continue
            resposta.raise_for_status()
            valor = resposta.json()
            _cache[chave] = (agora + CACHE_TTL_SEGUNDOS, valor)
            return valor
        except httpx.HTTPError as erro:
            logger.error("Falha ao chamar Acessórias %s: %s", caminho, erro)
            return None
    return None


async def buscar_empresa(identificador: str) -> dict | None:
    dados = await _get(f"/companies/{identificador}")
    if isinstance(dados, dict) and "Erro" not in dados:
        return dados
    return None


async def buscar_perfil_empresa(identificador: str) -> dict | None:
    """Igual buscar_empresa, mas já traz contatos e inscrições estaduais
    junto (uma chamada só) — usado só na página Perfil."""
    dados = await _get(
        f"/companies/{identificador}",
        params={"contacts": "", "registrationData": "", "stateRegistrations": ""},
    )
    if isinstance(dados, dict) and "Erro" not in dados:
        return dados
    return None


async def listar_contatos(identificador: str) -> list[dict]:
    dados = await _get(f"/companies/{identificador}", params={"contacts": ""})
    if isinstance(dados, dict) and "Erro" not in dados:
        return dados.get("ContatosNaEmpresa", [])
    return []


async def listar_usuarios_escritorio() -> list[dict]:
    """Usuários internos (funcionários) cadastrados na Acessórias — não
    confundir com ContatosNaEmpresa (contatos de cliente). Usado só por
    backend/criar_funcionario.py, pra sugerir nome/e-mail em vez do
    administrador digitar."""
    dados = await _get("/users/ListAll")
    return dados if isinstance(dados, list) else []


async def listar_departamentos(identificador: str) -> list[dict]:
    dados = await _get(f"/companies/{identificador}", params={"departments": ""})
    if isinstance(dados, dict) and "Erro" not in dados:
        return dados.get("Departamentos", [])
    return []


async def listar_todas_empresas() -> list[dict]:
    """Pagina /companies/ListAll até esgotar. Só backend/indexar_contatos.py
    usa isso — nenhuma rota do portal precisa da lista inteira de empresas,
    e paginar tudo é lento demais pra rodar dentro de um request comum."""
    empresas: list[dict] = []
    pagina = 1
    while True:
        dados = await _get("/companies/ListAll", params={"Pagina": pagina})
        if not isinstance(dados, list) or not dados:
            break
        empresas.extend(dados)
        pagina += 1
    return empresas


def _entregas(dados: dict | list | None) -> list[dict]:
    """/deliveries devolve um dict com "Entregas" quando o identificador é
    um CNPJ/CPF específico, e uma lista de empresas (cada uma com sua
    "Entregas") quando é 'ListAll'. Normaliza os dois formatos."""
    if isinstance(dados, dict):
        return dados.get("Entregas", [])
    if isinstance(dados, list) and dados:
        return dados[0].get("Entregas", [])
    return []


async def listar_vencimentos(identificador: str, dias_a_frente: int = 30) -> list[dict]:
    hoje = date.today()
    dados = await _get(
        f"/deliveries/{identificador}/",
        params={
            "DtInitial": hoje.isoformat(),
            "DtFinal": (hoje + timedelta(days=dias_a_frente)).isoformat(),
            "situation": "pending",
            "config": "",
        },
    )
    return _entregas(dados)


async def listar_obrigacoes(identificador: str, dias_atras: int = 90, dias_a_frente: int = 90) -> list[dict]:
    """Sem filtro de `situation`: traz obrigações em qualquer status
    (pendente, atrasada, entregue) — usado na página Obrigações, que
    mostra o panorama completo, diferente do "Próximos vencimentos" do
    Início (só pendentes)."""
    hoje = date.today()
    dados = await _get(
        f"/deliveries/{identificador}/",
        params={
            "DtInitial": (hoje - timedelta(days=dias_atras)).isoformat(),
            "DtFinal": (hoje + timedelta(days=dias_a_frente)).isoformat(),
            "config": "",
        },
    )
    return _entregas(dados)


async def listar_documentos_entregues(identificador: str, dias_atras: int = 30) -> list[dict]:
    hoje = date.today()
    dados = await _get(
        f"/deliveries/{identificador}/",
        params={
            "DtInitial": (hoje - timedelta(days=dias_atras)).isoformat(),
            "DtFinal": hoje.isoformat(),
            "situation": "delivered",
            "attachments": "",
            "config": "",
        },
    )
    return _entregas(dados)


async def listar_boletos(identificador: str, dias_atras: int = 90, dias_a_frente: int = 30) -> list[dict]:
    hoje = date.today()
    dados = await _get(
        f"/invoices/{identificador}/",
        params={
            "VIni": (hoje - timedelta(days=dias_atras)).isoformat(),
            "VFim": (hoje + timedelta(days=dias_a_frente)).isoformat(),
        },
    )
    return dados if isinstance(dados, list) else []


async def listar_solicitacoes_da_empresa(identificador: str, limite: int = 3, max_paginas: int = 3) -> list[dict]:
    """GET /requests não filtra por empresa — busca várias páginas de
    ListAll em paralelo (não uma atrás da outra) e filtra em memória pelo
    CNPJ/CPF. Antes buscava sequencialmente e parava só ao achar `limite`
    resultados — pra empresas que nunca aparecem em nenhuma página (a
    maioria, hoje), isso significava esgotar as 5 páginas uma de cada vez
    antes de desistir, e essa era a chamada mais lenta de cada carregamento
    de página. Buscar em paralelo troca "várias esperas de rede em fila"
    por "uma esperada só", ao custo de sempre bater `max_paginas` chamadas
    (mitigado pelo cache em _get). Ver limitação anotada no plano: não
    escala indefinidamente."""
    paginas = await asyncio.gather(
        *(_get("/requests/ListAll", params={"Pagina": pagina}) for pagina in range(1, max_paginas + 1))
    )
    encontradas = [
        solicitacao
        for dados in paginas
        if isinstance(dados, list)
        for solicitacao in dados
        if solicitacao.get("EmpCNPJ") == identificador
    ]
    return encontradas[:limite]


async def listar_todas_solicitacoes(max_paginas: int = 5) -> list[dict]:
    """Pro painel da equipe: solicitações de TODAS as empresas — ao
    contrário de listar_solicitacoes_da_empresa, aqui não filtra por
    CNPJ nenhum, é a fila inteira do escritório. Mesma paginação em
    paralelo, mesma limitação de não escalar indefinidamente."""
    paginas = await asyncio.gather(
        *(_get("/requests/ListAll", params={"Pagina": pagina}) for pagina in range(1, max_paginas + 1))
    )
    solicitacoes = []
    for dados in paginas:
        if isinstance(dados, list):
            solicitacoes.extend(dados)
    return solicitacoes


async def criar_solicitacao(
    identificador: str,
    assunto: str,
    departamento: str,
    prioridade: str,
    descricao: str,
    arquivo_nome: str | None = None,
    arquivo_bytes: bytes | None = None,
) -> dict:
    """POST /requests — não passa por _get (é escrita, não faz sentido
    cachear) nem pelas tentativas automáticas em 429 (reenviar um POST
    sozinho poderia duplicar a solicitação do cliente se a primeira, na
    real, tiver passado)."""
    token = _token()
    if not token:
        return {"Erro": "Integração com a Acessórias está indisponível agora. Tente de novo mais tarde."}

    campos = {
        "assunto": assunto,
        "empresa": identificador,
        "departamento": departamento,
        "prioridade": prioridade,
        "descricao": descricao,
    }
    arquivos = {"arquivo": (arquivo_nome, arquivo_bytes)} if arquivo_bytes and arquivo_nome else None

    try:
        resposta = await _obter_cliente().post(
            f"{BASE_URL}/requests",
            data=campos,
            files=arquivos,
            headers={"Authorization": f"Bearer {token}"},
        )
        resultado = resposta.json()
        if resposta.status_code >= 400:
            return {"Erro": resultado.get("Erro", "Não foi possível abrir a solicitação. Tente de novo.")}
        # Sem isso, o cliente que acabou de abrir a solicitação não a via
        # na própria lista por até CACHE_TTL_SEGUNDOS (achado testando de
        # verdade: criei uma solicitação e ela sumiu da lista até o cache
        # vencer) — como não sabemos em qual página da paginação a nova
        # entrada vai cair, invalida todas as páginas cacheadas de
        # /requests/ListAll de uma vez, não só uma.
        for chave in [c for c in _cache if c[0] == "/requests/ListAll"]:
            del _cache[chave]
        return resultado
    except httpx.HTTPError as erro:
        logger.error("Falha ao criar solicitação na Acessórias: %s", erro)
        return {"Erro": "Falha de conexão com a Acessórias. Tente de novo."}


# --- Painel da equipe: fila paginada, detalhe e atualização -------------
# Escrita em solicitação, segundo a documentação oficial
# (https://api.acessorias.com/documentation, seção "Requests
# (criação/edição)"): só existe POST /requests/{id}, que num envio só
# comenta (descricao), muda o status (statusSol R/C/F — F finaliza),
# reabre (reabrir=1), marca o comentário como privado (descPrivate=S),
# muda prazo/assunto/tipo/departamento e anexa arquivos. NÃO existe
# endpoint pra atribuir responsável — isso continua só no sistema deles.

async def listar_fila_solicitacoes(pagina: int = 1, status: str | None = None, paginas_por_bloco: int = 5) -> dict:
    """Uma "página" do painel = um bloco de `paginas_por_bloco` páginas
    da Acessórias (20 itens cada, fixo do lado deles), buscadas em
    paralelo, mais UMA página a frente só pra saber se existe próxima —
    sem isso, o painel cortava a fila em 100 itens sem avisar ninguém.
    A página a frente fica no cache de _get e é reaproveitada quando a
    equipe clica em "Próxima", então não é chamada desperdiçada.
    `status` vira o filtro SolStatus da própria Acessórias (A, P, C, F).

    Devolve {"solicitacoes": [...], "tem_mais": bool, "falhou": bool} —
    "falhou" separa "a Acessórias não respondeu" de "fila vazia", que
    antes apareciam iguais pra equipe."""
    filtros = {"SolStatus": status} if status else {}
    primeira = (pagina - 1) * paginas_por_bloco + 1
    respostas = await asyncio.gather(
        *(
            _get("/requests/ListAll", params={"Pagina": numero, **filtros})
            for numero in range(primeira, primeira + paginas_por_bloco + 1)
        )
    )
    *bloco, a_frente = respostas
    return {
        "solicitacoes": [item for dados in bloco if isinstance(dados, list) for item in dados],
        "tem_mais": isinstance(a_frente, list) and len(a_frente) > 0,
        "falhou": bloco[0] is None,
    }


async def buscar_solicitacao(sol_id: str) -> dict | None:
    """GET /requests/{SolID} — mesma estrutura de um item de ListAll,
    mais SolInteracoes (o histórico). A Acessórias devolve uma lista com
    um item só, e SolInteracoes vem como lista de listas — normaliza os
    dois aqui pra quem chama não precisar saber disso."""
    dados = await _get(f"/requests/{sol_id}")
    if isinstance(dados, list):
        dados = dados[0] if dados else None
    if not isinstance(dados, dict) or "Erro" in dados or not dados.get("SolID"):
        return None
    interacoes = []
    for item in dados.get("SolInteracoes") or []:
        if isinstance(item, list):
            interacoes.extend(i for i in item if isinstance(i, dict))
        elif isinstance(item, dict):
            interacoes.append(item)
    return {**dados, "SolInteracoes": interacoes}


def _invalidar_cache_solicitacoes(sol_id: str) -> None:
    """Depois de qualquer escrita: some com o detalhe da solicitação e
    com TODAS as páginas de ListAll em cache (com e sem filtro de
    status) — ListAll vem ordenado pela última atualização, então a
    solicitação recém-alterada muda de página."""
    for chave in [c for c in _cache if c[0] in ("/requests/ListAll", f"/requests/{sol_id}")]:
        del _cache[chave]


# Mensagens de erro documentadas da Acessórias -> texto nosso. Nunca
# repassa o texto cru deles pro navegador; o original vai só pro log.
_ERROS_EDICAO_CONHECIDOS = (
    ("está finalizada", "Esta solicitação está finalizada. Escolha Resolvendo ou Com o cliente para reabrir."),
    ("não é permitido em solicitação interna", "Solicitação interna não pode ficar com o status Com o cliente."),
    ("obrigatório ao alterar o status", "Escreva um comentário para mudar o status."),
    ("statusSol é obrigatório", "Escolha o novo status da solicitação."),
)
_ERRO_EDICAO_GENERICO = "A Acessórias não aceitou a alteração. Confira a solicitação e tente de novo."


async def atualizar_solicitacao(
    sol_id: str,
    descricao: str,
    status_sol: str,
    privado: bool = False,
    reabrir: bool = False,
    data_prazo: str | None = None,
) -> dict:
    """POST /requests/{id} — comenta e define o status num envio só (a
    Acessórias exige status ao comentar, e comentário ao mudar status).
    Como criar_solicitacao: sem cache e sem nova tentativa automática
    em 429 (reenviar sozinho poderia duplicar o comentário).

    Devolve {"ok": True} ou {"Erro": <mensagem já tratada pra equipe>}.
    Quem chama já validou os campos — aqui só monta a requisição."""
    token = _token()
    if not token:
        return {"Erro": "Integração com a Acessórias está indisponível agora. Tente de novo mais tarde."}

    campos = {"statusSol": status_sol, "descricao": descricao, "descPrivate": "S" if privado else "N"}
    if reabrir:
        campos["reabrir"] = "1"
    if data_prazo:
        campos["data_prazo"] = data_prazo

    try:
        resposta = await _obter_cliente().post(
            f"{BASE_URL}/requests/{sol_id}",
            data=campos,
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as erro:
        logger.error("Falha ao atualizar solicitação %s na Acessórias: %s", sol_id, erro)
        return {"Erro": "Falha de conexão com a Acessórias. Tente de novo."}

    if resposta.status_code == 429:
        return {"Erro": "A Acessórias está recebendo muitas requisições agora. Aguarde um minuto e tente de novo."}
    try:
        resultado = resposta.json()
    except ValueError:
        resultado = {}

    erro_api = resultado.get("Erro") if isinstance(resultado, dict) else None
    if resposta.status_code >= 400 or erro_api:
        logger.error("Acessórias recusou atualização da solicitação %s (%s): %s", sol_id, resposta.status_code, erro_api)
        texto = str(erro_api or "")
        for trecho, mensagem in _ERROS_EDICAO_CONHECIDOS:
            if trecho in texto:
                return {"Erro": mensagem}
        return {"Erro": _ERRO_EDICAO_GENERICO}

    _invalidar_cache_solicitacoes(sol_id)
    return {"ok": True}
