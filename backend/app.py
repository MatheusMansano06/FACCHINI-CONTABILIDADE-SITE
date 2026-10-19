"""Backend do site: serve os arquivos estáticos, a API de login e o portal.

Um único processo cuida de tudo — a lead page e o login continuam sendo
entregues como arquivos estáticos, exatamente como antes. As páginas do
portal (pages/portal-*.html) exigem sessão válida e são renderizadas como
templates Jinja2, preenchidas com dados buscados ao vivo na API da
Acessórias — o token nunca chega ao navegador, só o HTML já pronto.

As buscas na Acessórias rodam em paralelo (asyncio.gather) dentro de cada
página, não uma atrás da outra — o tempo de carregar o Início é o da
chamada mais lenta das quatro, não a soma das quatro.
"""
import asyncio
import calendar as modulo_calendario
import os
import secrets
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # precisa rodar antes de importar acessorias (lê env em cada chamada, mas o token já deve estar carregado)

import acessorias  # noqa: E402
import email_envio  # noqa: E402
from auth import (  # noqa: E402
    TAMANHO_MAXIMO_EMAIL,
    TAMANHO_MINIMO_SENHA,
    consumir_token_redefinicao,
    email_da_conta,
    emitir_token_redefinicao,
    gerar_hash,
    limpar_falhas_login,
    login_bloqueado,
    redefinicao_bloqueada,
    registrar_falha_login,
    registrar_pedido_redefinicao,
    token_redefinicao_valido,
    verificar_senha,
)
from database import inicializar_schema, obter_conexao  # noqa: E402

RAIZ = Path(__file__).parent.parent
PAGINAS = RAIZ / "pages"

# Cookie de sessão só como "Secure" (HTTPS) quando ENV=production está
# definido — em desenvolvimento local (http://) o navegador descartaria
# um cookie Secure e o login pareceria não "colar".
HTTPS_ONLY = os.environ.get("ENV") == "production"

SECRET_SESSAO = os.environ.get("SESSION_SECRET")
if not SECRET_SESSAO:
    if HTTPS_ONLY:
        # Nunca subir em produção com uma chave adivinhável: sem ela,
        # qualquer um que já viu este código forjaria um cookie de sessão
        # válido pra qualquer cliente ou funcionário.
        raise RuntimeError(
            "SESSION_SECRET não definido no ambiente — obrigatório em "
            "produção (ver backend/.env.example). O servidor não sobe sem ele."
        )
    print(
        "AVISO: SESSION_SECRET não definido no ambiente — gerando uma chave "
        "aleatória só para esta execução (sessões caem a cada restart). "
        "Defina a variável antes de publicar (ver backend/.env.example)."
    )
    SECRET_SESSAO = secrets.token_hex(32)

app = FastAPI()

# Rotas de autenticação que precisam funcionar mesmo com a troca pendente.
ROTAS_LIVRES_TROCA = {
    "/api/login", "/api/trocar-senha", "/api/esqueci-senha", "/api/redefinir-senha",
    "/api/redefinir-senha/validar", "/api/contato",
    "/pages/equipe-login.html", "/api/equipe/trocar-senha",
}


def _troca_pendente(request: Request) -> str | None:
    """'cliente' ou 'equipe' quando a área pedida exige trocar antes a senha
    provisória. É checado aqui, num ponto só, e não em cada rota: com a
    senha provisória comum, qualquer pessoa que a conheça entraria na conta
    de um cliente que ainda não trocou — então nenhum dado sai antes da troca,
    e rotas novas já nascem protegidas."""
    caminho = request.url.path
    if caminho in ROTAS_LIVRES_TROCA:
        return None
    sessao = request.session
    if caminho.startswith(("/pages/equipe-", "/api/equipe/")):
        pendente = sessao.get("funcionario_id") and sessao.get("funcionario_deve_trocar_senha")
        return "equipe" if pendente else None
    if caminho.startswith(("/pages/portal-", "/api/")) or caminho == "/pages/selecionar-empresa.html":
        pendente = sessao.get("usuario_id") and sessao.get("deve_trocar_senha")
        return "cliente" if pendente else None
    return None


# Registrado ANTES do SessionMiddleware de propósito: o último registrado é
# o mais externo, e este precisa rodar por dentro dele pra enxergar a sessão.
@app.middleware("http")
async def exigir_troca_de_senha(request: Request, call_next):
    area = _troca_pendente(request)
    if area:
        destino = "trocar-senha.html?equipe" if area == "equipe" else "trocar-senha.html"
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"erro": "Troque sua senha provisória antes de continuar.", "destino": destino},
                status_code=403,
            )
        return RedirectResponse(f"/pages/{destino}", status_code=303)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_SESSAO,
    session_cookie="facchini_sessao",
    max_age=60 * 60 * 8,  # 8 horas
    https_only=HTTPS_ONLY,
    same_site="lax",
)

CABECALHOS_SEGURANCA = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}
if HTTPS_ONLY:
    CABECALHOS_SEGURANCA["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers.update(CABECALHOS_SEGURANCA)
    return resposta


templates = Jinja2Templates(directory=str(PAGINAS))


@app.on_event("startup")
def ao_iniciar() -> None:
    inicializar_schema()


def _registrar_acesso(email: str, nome: str, tipo: str) -> None:
    """Item 11 da referência do usuário sobre o Acessórias — histórico de
    acessos não existe na API deles, é 100% nosso. Chamado só depois de
    login bem-sucedido (não registra tentativa falha, isso já é outro
    mecanismo — auth.registrar_falha_login)."""
    with obter_conexao() as conexao:
        conexao.execute(
            "INSERT INTO historico_acessos (email, nome, tipo) VALUES (?, ?, ?)",
            (email, nome, tipo),
        )


@app.post("/api/login")
async def login(request: Request):
    """Porta única do portal: a mesma tela serve cliente e equipe. A senha
    é conferida nas duas tabelas — funcionário vai pro painel da equipe,
    cliente pro portal. Quem é as duas coisas com o mesmo e-mail (ex.: o
    Henrique) entra nas duas de uma vez e alterna pelo menu do usuário."""
    corpo = await _corpo_json(request)
    email = str(corpo.get("usuario", "")).strip().lower()
    senha = str(corpo.get("senha", ""))

    if not email or not senha or len(email) > TAMANHO_MAXIMO_EMAIL:
        return JSONResponse({"erro": "Informe usuário e senha."}, status_code=400)

    ip = _ip_cliente(request)
    if login_bloqueado(email, ip):
        return JSONResponse(
            {"erro": "Muitas tentativas. Aguarde alguns minutos e tente de novo."},
            status_code=429,
        )

    with obter_conexao() as conexao:
        usuario = conexao.execute(
            "SELECT id, nome, senha_hash, deve_trocar_senha FROM usuarios WHERE email = ?", (email,)
        ).fetchone()
        funcionario = conexao.execute(
            "SELECT id, nome, senha_hash, deve_trocar_senha FROM funcionarios WHERE email = ?", (email,)
        ).fetchone()

    # Sempre as duas verificações (com hash fictício quando a conta não
    # existe): o tempo de resposta não revela se o e-mail é de cliente,
    # de equipe ou de ninguém.
    cliente_ok, equipe_ok = await asyncio.gather(
        run_in_threadpool(verificar_senha, senha, usuario["senha_hash"] if usuario else None),
        run_in_threadpool(verificar_senha, senha, funcionario["senha_hash"] if funcionario else None),
    )
    if not cliente_ok and not equipe_ok:
        registrar_falha_login(email, ip)
        return JSONResponse({"erro": "Usuário ou senha incorretos."}, status_code=401)

    limpar_falhas_login(email)
    # Sessão nova a cada login: nunca mistura com a de outra pessoa que
    # tenha usado o mesmo navegador antes.
    request.session.clear()

    if cliente_ok:
        with obter_conexao() as conexao:
            empresas = [
                linha["identificador_acessorias"]
                for linha in conexao.execute(
                    "SELECT identificador_acessorias FROM usuario_empresas WHERE usuario_id = ? ORDER BY id",
                    (usuario["id"],),
                )
            ]
        _registrar_acesso(email, usuario["nome"], "cliente")
        request.session["usuario_id"] = usuario["id"]
        request.session["nome"] = usuario["nome"]
        request.session["empresas"] = empresas
        request.session["deve_trocar_senha"] = bool(usuario["deve_trocar_senha"])
        # Uma empresa só: entra direto nela. Mais de uma: tela de escolha.
        request.session["empresa_ativa"] = empresas[0] if len(empresas) == 1 else None

    if equipe_ok:
        _registrar_acesso(email, funcionario["nome"], "equipe")
        request.session["funcionario_id"] = funcionario["id"]
        request.session["funcionario_nome"] = funcionario["nome"]
        request.session["funcionario_deve_trocar_senha"] = bool(funcionario["deve_trocar_senha"])
        if funcionario["deve_trocar_senha"]:
            return {"ok": True, "destino": "trocar-senha.html?equipe"}
        return {"ok": True, "destino": "equipe-atendimento.html"}

    if request.session["deve_trocar_senha"]:
        return {"ok": True, "destino": "trocar-senha.html"}
    return {"ok": True, "destino": _destino_cliente(request)}


def _destino_cliente(request: Request) -> str:
    if request.session.get("empresa_ativa") or len(request.session.get("empresas", [])) <= 1:
        return "portal-inicio.html"
    return "selecionar-empresa.html"


@app.post("/api/trocar-senha")
async def trocar_senha(request: Request):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    erro = await _trocar_senha_da_conta(
        request, "cliente", request.session["usuario_id"], bool(request.session.get("deve_trocar_senha"))
    )
    if erro:
        return erro

    # Sem redirecionamento: o cliente continua na mesma página do portal,
    # só o aviso flutuante some. Trocou aqui, não aparece mais em nenhum
    # login futuro — mas se só fechar sem trocar, volta a aparecer na
    # próxima vez que entrar (deve_trocar_senha continua 1 no banco).
    _troca_concluida_na_sessao(request)
    return {"ok": True, "destino": _destino_cliente(request)}


@app.post("/api/selecionar-empresa")
async def selecionar_empresa(request: Request):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    corpo = await request.json()
    identificador = str(corpo.get("identificador", ""))

    if identificador not in request.session.get("empresas", []):
        return JSONResponse({"erro": "Empresa inválida."}, status_code=400)

    request.session["empresa_ativa"] = identificador
    return {"ok": True, "destino": "portal-inicio.html"}


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/pages/login.html", status_code=303)


# --- Painel da equipe (Central de Atendimento) ---------------------------
# Login separado do cliente por decisão do usuário: são níveis de acesso
# bem diferentes (funcionário vê solicitações de toda a Facchini, cliente
# só a própria empresa), então usam chaves de sessão próprias
# (funcionario_id, não usuario_id) mesmo dividindo o mesmo cookie —
# nenhuma rota do cliente aceita sessão de funcionário nem vice-versa.

@app.post("/api/equipe/trocar-senha")
async def equipe_trocar_senha(request: Request):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    erro = await _trocar_senha_da_conta(
        request,
        "equipe",
        request.session["funcionario_id"],
        bool(request.session.get("funcionario_deve_trocar_senha")),
    )
    if erro:
        return erro

    _troca_concluida_na_sessao(request)
    return {"ok": True, "destino": "equipe-atendimento.html"}


@app.get("/equipe/logout")
async def equipe_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/pages/login.html", status_code=303)


# A tela de login da equipe virou a mesma do cliente; o endereço antigo
# continua funcionando pra quem salvou nos favoritos.
@app.get("/pages/equipe-login.html")
async def equipe_login_antigo():
    return RedirectResponse("/pages/login.html", status_code=303)


def _troca_concluida_na_sessao(request: Request) -> None:
    """A senha é uma só por e-mail (ver _trocar_senha_da_conta): trocou
    numa área, a outra também sai do modo de troca obrigatória."""
    request.session["deve_trocar_senha"] = False
    request.session["funcionario_deve_trocar_senha"] = False


def _tem_sessao_equipe(request: Request) -> bool:
    return bool(request.session.get("funcionario_id"))


def _guarda_equipe(request: Request) -> RedirectResponse | None:
    if not _tem_sessao_equipe(request):
        return RedirectResponse("/pages/login.html", status_code=303)
    return None


def _tem_sessao(request: Request) -> bool:
    return bool(request.session.get("usuario_id"))


def _guarda_portal(request: Request) -> RedirectResponse | None:
    """Toda página do portal passa por aqui antes de montar qualquer dado.
    Protege contra acesso direto por URL: se o login tem mais de uma
    empresa e nenhuma foi escolhida ainda nesta sessão, força a tela de
    seleção em vez de cair numa página sem saber qual empresa mostrar."""
    if not _tem_sessao(request):
        return RedirectResponse("/pages/login.html", status_code=303)
    if not request.session.get("empresa_ativa") and len(request.session.get("empresas", [])) > 1:
        return RedirectResponse("/pages/selecionar-empresa.html", status_code=303)
    return None


MESES_PT = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


def _data(texto: str, formato: str = "%Y-%m-%d") -> date | None:
    try:
        return datetime.strptime(texto, formato).date()
    except (ValueError, TypeError):
        return None


def _formatar_vencimentos(bruto: list[dict]) -> list[dict]:
    hoje = date.today()
    vencimentos = []
    for item in bruto:
        prazo = _data(item.get("EntDtPrazo", ""))
        if not prazo:
            continue
        dias_restantes = (prazo - hoje).days
        competencia = _data(item.get("EntCompetencia", ""))
        vencimentos.append({
            "dia": f"{prazo.day:02d}",
            "mes": MESES_PT[prazo.month - 1],
            "nome": item.get("Nome", ""),
            "competencia": f"Competência {competencia.month:02d}/{competencia.year}" if competencia else "",
            "dias_restantes": max(dias_restantes, 0),
            "breve": dias_restantes <= 7,
        })
    vencimentos.sort(key=lambda v: v["dias_restantes"])
    return vencimentos


def _formatar_documentos(bruto: list[dict]) -> list[dict]:
    bruto_ordenado = sorted(bruto, key=lambda item: item.get("EntDtEntrega", ""), reverse=True)
    documentos = []
    for item in bruto_ordenado:
        entrega = _data(item.get("EntDtEntrega", ""))
        competencia = _data(item.get("EntCompetencia", ""))
        anexos = item.get("Anexos") or []
        documentos.append({
            "nome": item.get("Nome", ""),
            "referencia": f"{competencia.month:02d}/{competencia.year}" if competencia else "Atualizado",
            "tipo": item.get("Config", {}).get("DptoNome", ""),
            "data_envio": entrega.strftime("%d/%m/%Y") if entrega else "",
            "anexo_url": anexos[0] if anexos else None,
        })
    return documentos


def _classe_status_obrigacao(status: str) -> str:
    if status.startswith("Atrasada"):
        return "atrasada"
    # "Ent. antecipada", "Ent. no prazo" (entregue) e "Dispensada" (não
    # precisa de ação) são todo "resolvido" pro cliente — só "Pendente"
    # continua contando como em aberto.
    if status.startswith("Ent.") or status.startswith("Dispensada"):
        return "concluido"
    return "andamento"


def _formatar_obrigacoes(bruto: list[dict]) -> list[dict]:
    bruto_ordenado = sorted(bruto, key=lambda item: item.get("EntDtPrazo", ""))
    obrigacoes = []
    for item in bruto_ordenado:
        prazo = _data(item.get("EntDtPrazo", ""))
        competencia = _data(item.get("EntCompetencia", ""))
        status = item.get("Status", "")
        obrigacoes.append({
            "nome": item.get("Nome", ""),
            "competencia": f"{competencia.month:02d}/{competencia.year}" if competencia else "",
            "prazo": prazo.strftime("%d/%m/%Y") if prazo else "",
            "tipo": item.get("Config", {}).get("DptoNome", ""),
            "status": status,
            "classe_status": _classe_status_obrigacao(status),
        })
    return obrigacoes


_STATUS_PARA_CLASSE = {
    "Finalizada": "concluido",
    "Cliente": "respondido",
}


def _formatar_atendimentos(bruto: list[dict]) -> list[dict]:
    atendimentos = []
    for item in bruto:
        abertura = item.get("SolDHAbertura", "")
        status = item.get("SolStatus", "")
        atendimentos.append({
            "id": item.get("SolID", ""),
            "assunto": item.get("SolAssunto", ""),
            "data": abertura.split(" ")[0] if abertura else "",
            "status": status,
            "classe_status": _STATUS_PARA_CLASSE.get(status, "andamento"),
        })
    return atendimentos


def _formatar_solicitacoes(bruto: list[dict]) -> list[dict]:
    # SolID maior = criada depois — mais simples e mais confiável que
    # tentar ordenar a data "DD/MM/AAAA HH:MM:SS" como texto.
    bruto_ordenado = sorted(bruto, key=lambda item: int(item.get("SolID") or 0), reverse=True)
    solicitacoes = []
    for item in bruto_ordenado:
        abertura = item.get("SolDHAbertura", "")
        status = item.get("SolStatus", "")
        solicitacoes.append({
            "id": item.get("SolID", ""),
            "assunto": item.get("SolAssunto", ""),
            "data": abertura.split(" ")[0] if abertura else "",
            "prioridade": item.get("SolPrioridade", ""),
            "status": status,
            "classe_status": _STATUS_PARA_CLASSE.get(status, "andamento"),
        })
    return solicitacoes


_STATUS_BOLETO_LABEL = {"P": "Pendente", "Q": "Quitado", "C": "Cancelado"}
_STATUS_BOLETO_CLASSE = {"P": "andamento", "Q": "concluido", "C": "atrasada"}


def _boletos_pagos_localmente(identificador: str) -> set[tuple[str, str, str]]:
    with obter_conexao() as conexao:
        linhas = conexao.execute(
            "SELECT vencimento, valor, competencia FROM boletos_pagos_local WHERE identificador_acessorias = ?",
            (identificador,),
        ).fetchall()
    return {(linha["vencimento"], linha["valor"], linha["competencia"]) for linha in linhas}


def _formatar_boletos(bruto: list[dict], pagos_localmente: set[tuple[str, str, str]] | None = None) -> list[dict]:
    pagos_localmente = pagos_localmente or set()

    def chave_vencimento(item: dict) -> date:
        return _data(item.get("Vencimento", ""), "%d/%m/%Y") or date.min

    bruto_ordenado = sorted(bruto, key=chave_vencimento, reverse=True)
    boletos = []
    for item in bruto_ordenado:
        status = item.get("Status", "")
        vencimento = item.get("Vencimento", "")
        valor = item.get("Valor", "")
        competencia = item.get("Competencia", "")
        boletos.append({
            "competencia": competencia,
            "vencimento": vencimento,
            "valor": valor,
            "status": _STATUS_BOLETO_LABEL.get(status, status),
            "classe_status": _STATUS_BOLETO_CLASSE.get(status, "andamento"),
            "nota_url": item.get("PDFNota") or None,
            # Só local — a Acessórias não expõe escrita nisso (ver
            # boletos_pagos_local em database.py). Não sobrepõe o status
            # real vindo de lá, é uma marcação à parte.
            "pago_local": (vencimento, valor, competencia) in pagos_localmente,
        })
    return boletos


_PRIORIDADE_ORDEM = {"Muito alta": 0, "Alta": 1, "Média": 2, "Baixa": 3}
# Reaproveita as cores já existentes de etiqueta-status (vermelho/azul/verde)
# pra prioridade também, em vez de criar uma paleta nova só pra isso.
_PRIORIDADE_PARA_CLASSE = {"Muito alta": "atrasada", "Alta": "atrasada", "Média": "andamento", "Baixa": "concluido"}


def _formatar_atendimento_equipe(bruto: list[dict]) -> list[dict]:
    """Fila da equipe: mais urgente (prioridade) e mais antiga (esperando
    há mais tempo) primeiro — diferente da lista do cliente
    (_formatar_solicitacoes), que ordena só por mais recente."""
    hoje = datetime.now()

    def chave_ordenacao(item: dict) -> tuple:
        prioridade = _PRIORIDADE_ORDEM.get(item.get("SolPrioridade", ""), 99)
        abertura = _data(item.get("SolDHAbertura", "").split(" ")[0], "%d/%m/%Y") or date.max
        return (prioridade, abertura)

    bruto_ordenado = sorted(bruto, key=chave_ordenacao)
    atendimentos = []
    for item in bruto_ordenado:
        abertura_texto = item.get("SolDHAbertura", "")
        abertura_data = _data(abertura_texto.split(" ")[0], "%d/%m/%Y") if abertura_texto else None
        dias_aberto = (hoje.date() - abertura_data).days if abertura_data else None
        status = item.get("SolStatus", "")
        atendimentos.append({
            "id": item.get("SolID", ""),
            "assunto": item.get("SolAssunto", ""),
            "empresa": item.get("EmpNome") or item.get("EmpCNPJ", ""),
            "data": abertura_data.strftime("%d/%m/%Y") if abertura_data else "",
            "dias_aberto": dias_aberto,
            "prioridade": item.get("SolPrioridade", ""),
            "classe_prioridade": _PRIORIDADE_PARA_CLASSE.get(item.get("SolPrioridade", ""), "andamento"),
            "status": status,
            "classe_status": _STATUS_PARA_CLASSE.get(status, "andamento"),
        })
    return atendimentos


# Filtro de status do painel -> filtro SolStatus da própria Acessórias
# (documentação de GET /requests). Filtrar lá, não no navegador: com a
# fila paginada, um filtro só no navegador esconderia linhas da página
# atual e daria a impressão errada de que não há mais nenhuma.
FILTROS_STATUS_ATENDIMENTO = {
    "A": "Nova",
    "P": "Resolvendo",
    "C": "Com o cliente",
    "F": "Finalizada",
}
MAXIMO_PAGINAS_ATENDIMENTO = 50  # 50 x 100 = 5.000 solicitações; além disso é URL forjada


async def _montar_contexto_atendimento(request: Request, pagina: int = 1, status: str = "") -> dict:
    fila = await acessorias.listar_fila_solicitacoes(pagina=pagina, status=status or None)
    return {
        "nome_usuario": request.session.get("funcionario_nome", "equipe"),
        "deve_trocar_senha": bool(request.session.get("funcionario_deve_trocar_senha")),
        "atendimentos": _formatar_atendimento_equipe(fila["solicitacoes"]),
        "pagina": pagina,
        "tem_anterior": pagina > 1,
        "tem_proxima": fila["tem_mais"] and pagina < MAXIMO_PAGINAS_ATENDIMENTO,
        "falha_acessorias": fila["falhou"],
        "status_filtro": status,
        "opcoes_status": FILTROS_STATUS_ATENDIMENTO,
    }


def _identificador_ativo(request: Request) -> str | None:
    return request.session.get("empresa_ativa")


def _cabecalho(request: Request, empresa_dados: dict | None, identificador: str | None) -> dict:
    fantasia = (empresa_dados or {}).get("Fantasia") or (empresa_dados or {}).get("Razao") or "Cliente"
    cnpj = (empresa_dados or {}).get("Identificador") or identificador or "—"
    return {
        "nome_usuario": request.session.get("nome", "cliente"),
        "empresa": {
            "fantasia": fantasia,
            "cnpj": cnpj,
            # fantasia nunca é vazio (o "or 'Cliente'" acima garante isso).
            "inicial": fantasia[:1].upper(),
        },
        # Controla o aviso flutuante de troca de senha (portal-shell.css /
        # portal.js) — presente em toda página do portal.
        "deve_trocar_senha": bool(request.session.get("deve_trocar_senha")),
        # Só mostra "Trocar empresa" no menu do usuário quando faz sentido.
        "multiplas_empresas": len(request.session.get("empresas", [])) > 1,
        # Sino do topo — ponto e aria-label (ver _comunicados_nao_lidos).
        "sino": _sino(request),
    }


async def _montar_contexto_inicio(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"vencimentos": [], "documentos": [], "atendimentos": []})
        return contexto

    # As quatro chamadas são independentes entre si — rodar em paralelo em
    # vez de uma depois da outra é a diferença entre a página demorar o
    # tempo da mais lenta ou a soma de todas.
    empresa_dados, vencimentos_brutos, documentos_brutos, atendimentos_brutos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_vencimentos(identificador),
        acessorias.listar_documentos_entregues(identificador),
        acessorias.listar_solicitacoes_da_empresa(identificador, limite=3),
    )

    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto.update({
        "vencimentos": _formatar_vencimentos(vencimentos_brutos),
        "documentos": _formatar_documentos(documentos_brutos)[:10],
        "atendimentos": _formatar_atendimentos(atendimentos_brutos),
    })
    return contexto


async def _montar_contexto_documentos(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto["documentos"] = []
        return contexto

    empresa_dados, documentos_brutos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_documentos_entregues(identificador, dias_atras=365),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["documentos"] = _formatar_documentos(documentos_brutos)
    return contexto


async def _montar_contexto_obrigacoes(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto["obrigacoes"] = []
        return contexto

    empresa_dados, obrigacoes_brutas = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_obrigacoes(identificador),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["obrigacoes"] = _formatar_obrigacoes(obrigacoes_brutas)
    return contexto


def _montar_semanas_calendario(obrigacoes: list[dict], ano: int, mes: int) -> list[list[dict | None]]:
    """Reaproveita a mesma lista já formatada por _formatar_obrigacoes (não
    busca nada novo na Acessórias) e organiza em semanas domingo-sábado,
    cada dia com as obrigações que vencem nele. Dias fora do mês (início/
    fim da grade) viram None — o template só desenha a célula vazia."""
    por_dia: dict[int, list[dict]] = {}
    for item in obrigacoes:
        prazo = _data(item["prazo"], "%d/%m/%Y")
        if prazo and prazo.year == ano and prazo.month == mes:
            por_dia.setdefault(prazo.day, []).append(item)

    calendario = modulo_calendario.Calendar(firstweekday=6)  # domingo primeiro
    semanas = []
    for semana in calendario.monthdayscalendar(ano, mes):
        linha = [{"dia": dia, "itens": por_dia.get(dia, [])} if dia else None for dia in semana]
        semanas.append(linha)
    return semanas


async def _montar_contexto_calendario(request: Request, ano: int, mes: int) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"semanas": [], "mes_nome": "", "mes_anterior": {}, "mes_seguinte": {}})
        return contexto

    # Janela ampla (±120 dias) o bastante pra cobrir qualquer mês vizinho
    # sem precisar buscar de novo na Acessórias a cada troca de mês — o
    # cache de _get já resolve isso, então navegar entre meses próximos
    # não paga chamada de rede extra.
    empresa_dados, obrigacoes_brutas = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_obrigacoes(identificador, dias_atras=120, dias_a_frente=120),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    obrigacoes = _formatar_obrigacoes(obrigacoes_brutas)
    contexto["semanas"] = _montar_semanas_calendario(obrigacoes, ano, mes)
    contexto["mes_nome"] = f"{MESES_PT[mes - 1]} {ano}"
    contexto["mes_anterior"] = {"ano": ano - 1, "mes": 12} if mes == 1 else {"ano": ano, "mes": mes - 1}
    contexto["mes_seguinte"] = {"ano": ano + 1, "mes": 1} if mes == 12 else {"ano": ano, "mes": mes + 1}
    return contexto


async def _montar_contexto_solicitacoes(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"solicitacoes": [], "departamentos": []})
        return contexto

    empresa_dados, solicitacoes_brutas, departamentos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_solicitacoes_da_empresa(identificador, limite=20, max_paginas=5),
        acessorias.listar_departamentos(identificador),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["solicitacoes"] = _formatar_solicitacoes(solicitacoes_brutas)
    contexto["departamentos"] = departamentos
    return contexto


async def _montar_contexto_financeiro(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto["boletos"] = []
        return contexto

    empresa_dados, boletos_brutos = await asyncio.gather(
        acessorias.buscar_empresa(identificador),
        acessorias.listar_boletos(identificador),
    )
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["boletos"] = _formatar_boletos(boletos_brutos, _boletos_pagos_localmente(identificador))
    return contexto


def _data_cadastro(texto: str) -> str:
    # A Acessórias usa "0000-00-00" como "sem data definida" em vez de
    # omitir o campo — mostrar isso cru pro cliente ficaria estranho.
    data = _data(texto)
    return data.strftime("%d/%m/%Y") if data else "—"


def _historico_acessos(request: Request, limite: int = 10) -> list[dict]:
    """Item 11 da referência do usuário sobre o Acessórias — não vem de
    lá, é histórico local (tabela historico_acessos, gravada em
    _registrar_acesso a cada login bem-sucedido)."""
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        return []
    with obter_conexao() as conexao:
        usuario = conexao.execute("SELECT email FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not usuario:
            return []
        linhas = conexao.execute(
            "SELECT criado_em FROM historico_acessos WHERE email = ? AND tipo = 'cliente' ORDER BY id DESC LIMIT ?",
            (usuario["email"], limite),
        ).fetchall()
    acessos = []
    for linha in linhas:
        momento = datetime.strptime(linha["criado_em"], "%Y-%m-%d %H:%M:%S")
        acessos.append({"data_hora": momento.strftime("%d/%m/%Y às %H:%M")})
    return acessos


async def _montar_contexto_perfil(request: Request) -> dict:
    identificador = _identificador_ativo(request)
    if not identificador:
        contexto = _cabecalho(request, None, None)
        contexto.update({"perfil": None, "contatos": [], "inscricoes": [], "acessos": []})
        return contexto

    dados = await acessorias.buscar_perfil_empresa(identificador)
    contexto = _cabecalho(request, dados, identificador)
    contexto["acessos"] = _historico_acessos(request)
    if not dados:
        # Falha real da Acessórias (não "campo vazio") — o template mostra
        # o aviso de "não conseguimos carregar" em vez de uma ficha em
        # branco, que pareceria um bug nosso.
        contexto.update({"perfil": None, "contatos": [], "inscricoes": []})
        return contexto

    contexto["perfil"] = {
        "razao": dados.get("Razao", ""),
        "fantasia": dados.get("Fantasia", ""),
        "cnpj": dados.get("Identificador", identificador),
        "status": dados.get("Status", ""),
        "regime": dados.get("Regime", "") or "—",
        "telefone": dados.get("Telefone", "") or "—",
        "uf": dados.get("UF", "") or "—",
        "cliente_desde": _data_cadastro(dados.get("ClienteDesde", "")),
    }
    contexto["contatos"] = dados.get("ContatosNaEmpresa", [])
    contexto["inscricoes"] = dados.get("InscricoesEstaduais", [])
    return contexto


# Páginas do portal exigem sessão válida — cada página nova do portal
# ganha uma rota igual a esta, seguindo o mesmo padrão: checar
# _guarda_portal antes de tudo, e só então montar dados.
@app.get("/pages/portal-inicio.html")
async def pagina_portal_inicio(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_inicio(request)
    return templates.TemplateResponse(request, "portal-inicio.html", contexto)


@app.get("/pages/portal-documentos.html")
async def pagina_portal_documentos(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_documentos(request)
    return templates.TemplateResponse(request, "portal-documentos.html", contexto)


@app.get("/pages/portal-obrigacoes.html")
async def pagina_portal_obrigacoes(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_obrigacoes(request)
    return templates.TemplateResponse(request, "portal-obrigacoes.html", contexto)


@app.get("/pages/portal-calendario.html")
async def pagina_portal_calendario(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    hoje = date.today()
    try:
        ano = int(request.query_params.get("ano", hoje.year))
        mes = int(request.query_params.get("mes", hoje.month))
        if not 1 <= mes <= 12:
            raise ValueError
    except ValueError:
        ano, mes = hoje.year, hoje.month
    contexto = await _montar_contexto_calendario(request, ano, mes)
    return templates.TemplateResponse(request, "portal-calendario.html", contexto)


@app.get("/pages/portal-solicitacoes.html")
async def pagina_portal_solicitacoes(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_solicitacoes(request)
    return templates.TemplateResponse(request, "portal-solicitacoes.html", contexto)


@app.get("/pages/portal-financeiro.html")
async def pagina_portal_financeiro(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_financeiro(request)
    return templates.TemplateResponse(request, "portal-financeiro.html", contexto)


@app.get("/pages/portal-perfil.html")
async def pagina_portal_perfil(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    contexto = await _montar_contexto_perfil(request)
    return templates.TemplateResponse(request, "portal-perfil.html", contexto)


@app.get("/pages/equipe-atendimento.html")
async def pagina_equipe_atendimento(request: Request):
    guarda = _guarda_equipe(request)
    if guarda:
        return guarda
    # ?pagina=N&status=X — inválido cai no padrão em vez de dar erro
    # (mesmo critério do ?ano/?mes do calendário).
    try:
        pagina = int(request.query_params.get("pagina", "1"))
        if not 1 <= pagina <= MAXIMO_PAGINAS_ATENDIMENTO:
            raise ValueError
    except ValueError:
        pagina = 1
    status = request.query_params.get("status", "")
    if status not in FILTROS_STATUS_ATENDIMENTO:
        status = ""
    contexto = await _montar_contexto_atendimento(request, pagina, status)
    return templates.TemplateResponse(request, "equipe-atendimento.html", contexto)


TAMANHO_MAXIMO_ANEXO = 30 * 1024 * 1024  # 30MB — mesmo limite da Acessórias


@app.post("/api/solicitacoes")
async def api_criar_solicitacao(
    request: Request,
    assunto: str = Form(...),
    departamento: str = Form(...),
    prioridade: str = Form(...),
    descricao: str = Form(...),
    arquivo: UploadFile | None = File(None),
):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    identificador = _identificador_ativo(request)
    if not identificador:
        return JSONResponse({"erro": "Nenhuma empresa selecionada."}, status_code=400)

    assunto = assunto.strip()
    descricao = descricao.strip()
    if not assunto or not descricao:
        return JSONResponse({"erro": "Preencha assunto e descrição."}, status_code=400)

    arquivo_bytes = None
    arquivo_nome = None
    if arquivo and arquivo.filename:
        arquivo_bytes = await arquivo.read()
        if len(arquivo_bytes) > TAMANHO_MAXIMO_ANEXO:
            return JSONResponse({"erro": "O anexo passa de 30MB — envie um arquivo menor."}, status_code=400)
        arquivo_nome = arquivo.filename

    resultado = await acessorias.criar_solicitacao(
        identificador, assunto, departamento, prioridade, descricao,
        arquivo_nome=arquivo_nome, arquivo_bytes=arquivo_bytes,
    )
    if "Erro" in resultado:
        return JSONResponse({"erro": resultado["Erro"]}, status_code=400)

    return {"ok": True}


@app.post("/api/boletos/alternar-pago")
async def api_alternar_pago(request: Request):
    """"Marcar como pago" (item 6) — só local, a Acessórias não tem
    escrita pra isso. Usa a empresa ativa da sessão, nunca uma vinda do
    corpo da requisição, pra um cliente nunca conseguir marcar boleto de
    empresa que não é a dele."""
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    identificador = _identificador_ativo(request)
    if not identificador:
        return JSONResponse({"erro": "Nenhuma empresa selecionada."}, status_code=400)

    corpo = await request.json()
    vencimento = str(corpo.get("vencimento", "")).strip()
    valor = str(corpo.get("valor", "")).strip()
    competencia = str(corpo.get("competencia", "")).strip()
    if not vencimento or not valor or not competencia:
        return JSONResponse({"erro": "Dados do boleto inválidos."}, status_code=400)

    with obter_conexao() as conexao:
        existente = conexao.execute(
            """SELECT id FROM boletos_pagos_local
               WHERE identificador_acessorias = ? AND vencimento = ? AND valor = ? AND competencia = ?""",
            (identificador, vencimento, valor, competencia),
        ).fetchone()
        if existente:
            conexao.execute("DELETE FROM boletos_pagos_local WHERE id = ?", (existente["id"],))
            pago = False
        else:
            conexao.execute(
                """INSERT INTO boletos_pagos_local (identificador_acessorias, vencimento, valor, competencia)
                   VALUES (?, ?, ?, ?)""",
                (identificador, vencimento, valor, competencia),
            )
            pago = True

    return {"ok": True, "pago": pago}


# Não passa por _guarda_portal — é justamente essa página que resolve o
# caso de "sessão válida, mas nenhuma empresa escolhida ainda".
@app.get("/pages/selecionar-empresa.html")
async def pagina_selecionar_empresa(request: Request):
    if not _tem_sessao(request):
        return RedirectResponse("/pages/login.html", status_code=303)

    identificadores = request.session.get("empresas", [])
    dados_das_empresas = await asyncio.gather(*(acessorias.buscar_empresa(i) for i in identificadores))
    empresas = [
        {
            "identificador": identificador,
            "fantasia": (dados or {}).get("Fantasia") or (dados or {}).get("Razao") or identificador,
            "cnpj": (dados or {}).get("Identificador") or identificador,
        }
        for identificador, dados in zip(identificadores, dados_das_empresas)
    ]
    return templates.TemplateResponse(
        request,
        "selecionar-empresa.html",
        {"nome_usuario": request.session.get("nome", "cliente"), "empresas": empresas},
    )


class ArquivosEstaticos(StaticFiles):
    """StaticFiles do FastAPI não desliga o cache do navegador sozinho —
    ao contrário do scripts/dev-server.py (que existe só por causa disso).
    Sem isso, editar JS/CSS localmente e recarregar a página pode continuar
    servindo a versão antiga por dias, e parece um bug no código quando não
    é. Em produção (ENV=production) mantém cache normal — é o que
    docs/DEPLOY.md já recomenda para esses arquivos."""

    async def get_response(self, path: str, scope):
        resposta = await super().get_response(path, scope)
        if not HTTPS_ONLY:
            resposta.headers["Cache-Control"] = "no-store, must-revalidate"
        return resposta


# --- Comunicados (escritório -> clientes) ---------------------------------
# A Acessórias não tem nenhum recurso de avisos/notícias (conferido na
# documentação oficial da API), então isto é 100% local — tabela
# comunicados em database.py. A equipe publica/remove em
# pages/equipe-comunicados.html; o cliente vê em portal-comunicados.html
# e os 3 mais recentes no card "Novidades" do Início.
#
# Regra de segurança: o cliente só enxerga comunicados gerais (sem
# empresa) ou da empresa_ativa DA SESSÃO — nunca de um identificador vindo
# da requisição. Escrita só com sessão de equipe.
import re  # noqa: E402
from datetime import timedelta, timezone  # noqa: E402

CATEGORIAS_COMUNICADO = {
    "comunicado": "Comunicado",
    "informativo": "Informativo",
    "institucional": "Institucional",
}
TITULO_COMUNICADO_MAX = 120
TEXTO_COMUNICADO_MAX = 3000
# Brasil não tem horário de verão desde 2019 — offset fixo evita depender
# do pacote tzdata no container só por causa disto.
_FUSO_BRASILIA = timezone(timedelta(hours=-3))
_MESES_EXTENSO = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def _somente_digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def _formatar_comunicado(linha) -> dict:
    # criado_em vem do datetime('now') do SQLite, ou seja, em UTC.
    try:
        momento = datetime.strptime(linha["criado_em"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        local = momento.astimezone(_FUSO_BRASILIA)
        data_extenso = f"{local.day:02d} de {_MESES_EXTENSO[local.month - 1]} de {local.year}"
        data_iso = local.date().isoformat()
    except (ValueError, TypeError):
        data_extenso, data_iso = "", ""
    return {
        "id": linha["id"],
        "titulo": linha["titulo"],
        "texto": linha["texto"],
        "categoria": linha["categoria"],
        "categoria_nome": CATEGORIAS_COMUNICADO.get(linha["categoria"], "Comunicado"),
        "exclusivo": bool(linha["empresa_digitos"]),
        "empresa_nome": linha["empresa_nome"] or "",
        "autor_nome": linha["autor_nome"],
        "data": data_extenso,
        "data_iso": data_iso,
    }


def _comunicados_do_cliente(request: Request, limite: int = 50) -> list[dict]:
    digitos = _somente_digitos(_identificador_ativo(request))
    with obter_conexao() as conexao:
        linhas = conexao.execute(
            """SELECT id, titulo, texto, categoria, empresa_digitos, empresa_nome, autor_nome, criado_em
               FROM comunicados
               WHERE removido_em IS NULL
                 AND (empresa_digitos IS NULL OR (? != '' AND empresa_digitos = ?))
               ORDER BY criado_em DESC, id DESC
               LIMIT ?""",
            (digitos, digitos, limite),
        ).fetchall()
    return [_formatar_comunicado(linha) for linha in linhas]


def _comunicados_recentes_template(request: Request, limite: int = 3) -> list[dict]:
    """Exposto ao Jinja como global (comunicados_recentes) pro card
    "Novidades" do Início — assim o Início ganha os comunicados sem mexer
    em _montar_contexto_inicio. Leitura local no SQLite, sem rede; sem
    sessão de cliente não devolve nada."""
    if not _tem_sessao(request):
        return []
    return _comunicados_do_cliente(request, limite)


templates.env.globals["comunicados_recentes"] = _comunicados_recentes_template


def _comunicados_nao_lidos(request: Request) -> int:
    """Comunicados visíveis pro cliente (mesmo filtro de
    _comunicados_do_cliente) publicados depois do último que ele viu —
    marca em comunicados_vistos, avançada ao abrir portal-comunicados.html."""
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        return 0
    digitos = _somente_digitos(_identificador_ativo(request))
    with obter_conexao() as conexao:
        linha = conexao.execute(
            """SELECT COUNT(*) FROM comunicados
               WHERE removido_em IS NULL
                 AND (empresa_digitos IS NULL OR (? != '' AND empresa_digitos = ?))
                 AND id > COALESCE((SELECT visto_ate_id FROM comunicados_vistos WHERE usuario_id = ?), 0)""",
            (digitos, digitos, usuario_id),
        ).fetchone()
    return linha[0]


def _sino(request: Request) -> dict:
    nao_lidos = _comunicados_nao_lidos(request)
    if not nao_lidos:
        rotulo = "Comunicados: nenhum não lido"
    elif nao_lidos == 1:
        rotulo = "Comunicados: 1 não lido"
    else:
        rotulo = f"Comunicados: {nao_lidos} não lidos"
    return {"nao_lidos": nao_lidos, "rotulo": rotulo}


def _marcar_comunicados_vistos(usuario_id: int, ate_id: int) -> int:
    """Avança a marca de "visto até" (nunca volta) e devolve a anterior —
    usada pra destacar o que é novo nesta visita."""
    with obter_conexao() as conexao:
        anterior = conexao.execute(
            "SELECT visto_ate_id FROM comunicados_vistos WHERE usuario_id = ?", (usuario_id,)
        ).fetchone()
        conexao.execute(
            """INSERT INTO comunicados_vistos (usuario_id, visto_ate_id) VALUES (?, ?)
               ON CONFLICT (usuario_id) DO UPDATE SET
                 visto_ate_id = MAX(visto_ate_id, excluded.visto_ate_id),
                 atualizado_em = datetime('now')""",
            (usuario_id, ate_id),
        )
    return anterior["visto_ate_id"] if anterior else 0


@app.get("/pages/portal-comunicados.html")
async def pagina_portal_comunicados(request: Request):
    guarda = _guarda_portal(request)
    if guarda:
        return guarda
    identificador = _identificador_ativo(request)
    # Única chamada à Acessórias aqui (cabeçalho), já cacheada por _get;
    # os comunicados em si são locais.
    empresa_dados = await acessorias.buscar_empresa(identificador) if identificador else None
    comunicados = _comunicados_do_cliente(request)
    # Marca antes de montar o cabeçalho, pra o sino já sair apagado aqui.
    visto_antes = _marcar_comunicados_vistos(
        request.session["usuario_id"], max((c["id"] for c in comunicados), default=0)
    )
    for comunicado in comunicados:
        comunicado["novo"] = comunicado["id"] > visto_antes
    contexto = _cabecalho(request, empresa_dados, identificador)
    contexto["comunicados"] = comunicados
    return templates.TemplateResponse(request, "portal-comunicados.html", contexto)


# --- Busca do topo do portal ----------------------------------------------
# Procura no que o cliente já vê nas páginas — documentos, obrigações,
# boletos (Acessórias) e comunicados (local) — sempre da empresa_ativa da
# sessão, nunca de um identificador vindo da requisição. Usa exatamente os
# mesmos parâmetros das páginas (Documentos: 365 dias; Obrigações e
# Financeiro: padrão), então quase sempre sai do cache de _get, sem rede.
# Cada resultado aponta pra página certa com ?destaque=… (portal.js realça
# a linha da tabela) ou, no caso de comunicado, pra âncora #comunicado-N.
import unicodedata  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

BUSCA_TERMO_MAX = 80
BUSCA_ITENS_POR_GRUPO = 5
# Atalhos pras próprias telas — "senha", "boleto", "ajuda" levam a algum
# lugar mesmo quando nenhum dado bate. Palavras já sem acento.
PAGINAS_BUSCA = [
    ("Início", "portal-inicio.html", "inicio painel resumo novidades vencimentos"),
    ("Documentos", "portal-documentos.html", "documentos arquivos guias balancete folha baixar download"),
    ("Obrigações", "portal-obrigacoes.html", "obrigacoes impostos guias prazos das gps dctfweb fgts"),
    ("Calendário", "portal-calendario.html", "calendario agenda mes prazos vencimentos"),
    ("Solicitações", "portal-solicitacoes.html", "solicitacoes pedidos tickets atendimento chamados"),
    ("Abrir uma solicitação", "portal-solicitacoes.html#nova-solicitacao", "nova solicitacao abrir pedido ajuda duvida anexo enviar"),
    ("Financeiro", "portal-financeiro.html", "financeiro boletos honorarios pagamentos nota fiscal pago"),
    ("Comunicados", "portal-comunicados.html", "comunicados avisos novidades noticias informativos"),
    ("Perfil da empresa", "portal-perfil.html", "perfil empresa cnpj dados cadastro contatos acessos"),
]


def _normalizar_busca(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto or "") if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.casefold().split())


def _bate(palavras: list[str], *campos: str) -> bool:
    texto = _normalizar_busca(" ".join(c for c in campos if c))
    return all(p in texto for p in palavras)


def _url_destaque(pagina: str, *termos: str) -> str:
    termos_validos = [("destaque", t) for t in termos if t]
    return f"{pagina}?{urlencode(termos_validos)}" if termos_validos else pagina


def _grupo_busca(titulo: str, url: str, itens: list[dict]) -> dict:
    return {"titulo": titulo, "url": url, "total": len(itens), "itens": itens[:BUSCA_ITENS_POR_GRUPO]}


@app.get("/api/busca")
async def api_busca(request: Request):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    termo = (request.query_params.get("q") or "").strip()[:BUSCA_TERMO_MAX]
    palavras = _normalizar_busca(termo).split()
    if len("".join(palavras)) < 2:
        return {"termo": termo, "grupos": []}

    identificador = _identificador_ativo(request)
    if identificador:
        documentos_brutos, obrigacoes_brutas, boletos_brutos = await asyncio.gather(
            acessorias.listar_documentos_entregues(identificador, dias_atras=365),
            acessorias.listar_obrigacoes(identificador),
            acessorias.listar_boletos(identificador),
        )
    else:
        documentos_brutos, obrigacoes_brutas, boletos_brutos = [], [], []

    documentos = [
        {
            "titulo": d["nome"],
            "detalhe": " · ".join(filter(None, [d["tipo"], f"ref. {d['referencia']}", d["data_envio"] and f"enviado em {d['data_envio']}"])),
            "url": _url_destaque("portal-documentos.html", d["nome"], d["referencia"], d["data_envio"]),
        }
        for d in _formatar_documentos(documentos_brutos)
        if _bate(palavras, d["nome"], d["tipo"], d["referencia"], d["data_envio"])
    ]
    obrigacoes = [
        {
            "titulo": o["nome"],
            "detalhe": " · ".join(filter(None, [o["competencia"] and f"competência {o['competencia']}", o["prazo"] and f"prazo {o['prazo']}", o["status"]])),
            "url": _url_destaque("portal-obrigacoes.html", o["nome"], o["competencia"], o["prazo"]),
        }
        for o in _formatar_obrigacoes(obrigacoes_brutas)
        if _bate(palavras, o["nome"], o["tipo"], o["competencia"], o["prazo"], o["status"])
    ]
    boletos = [
        {
            "titulo": f"Boleto {b['competencia']}".strip(),
            "detalhe": " · ".join(filter(None, [b["vencimento"] and f"vence {b['vencimento']}", b["valor"] and f"R$ {b['valor']}", b["status"]])),
            "url": _url_destaque("portal-financeiro.html", b["competencia"], b["vencimento"], b["valor"]),
        }
        for b in _formatar_boletos(boletos_brutos)
        if _bate(palavras, "boleto honorarios", b["competencia"], b["vencimento"], b["valor"], b["status"])
    ]
    comunicados = [
        {
            "titulo": c["titulo"],
            "detalhe": " · ".join(filter(None, [c["categoria_nome"], c["data"]])),
            "url": f"portal-comunicados.html#comunicado-{c['id']}",
        }
        for c in _comunicados_do_cliente(request)
        if _bate(palavras, c["titulo"], c["texto"], c["categoria_nome"])
    ]
    paginas = [
        {"titulo": titulo, "detalhe": "Ir para a página", "url": url}
        for titulo, url, chaves in PAGINAS_BUSCA
        if _bate(palavras, titulo, chaves)
    ]

    grupos = [
        _grupo_busca("Documentos", "portal-documentos.html", documentos),
        _grupo_busca("Obrigações", "portal-obrigacoes.html", obrigacoes),
        _grupo_busca("Boletos", "portal-financeiro.html", boletos),
        _grupo_busca("Comunicados", "portal-comunicados.html", comunicados),
        _grupo_busca("Páginas do portal", "", paginas),
    ]
    return {"termo": termo, "grupos": [g for g in grupos if g["total"]]}


@app.get("/pages/equipe-comunicados.html")
async def pagina_equipe_comunicados(request: Request):
    guarda = _guarda_equipe(request)
    if guarda:
        return guarda
    with obter_conexao() as conexao:
        linhas = conexao.execute(
            """SELECT id, titulo, texto, categoria, empresa_digitos, empresa_nome, autor_nome, criado_em
               FROM comunicados WHERE removido_em IS NULL
               ORDER BY criado_em DESC, id DESC LIMIT 200"""
        ).fetchall()
        # Sugestões pro campo de empresa: só quem tem login no portal
        # (consulta local, sem nenhuma chamada por empresa à Acessórias).
        empresas_portal = [
            linha["identificador_acessorias"]
            for linha in conexao.execute(
                "SELECT DISTINCT identificador_acessorias FROM usuario_empresas ORDER BY identificador_acessorias"
            )
        ]
    return templates.TemplateResponse(
        request,
        "equipe-comunicados.html",
        {
            "nome_usuario": request.session.get("funcionario_nome", "equipe"),
            "deve_trocar_senha": bool(request.session.get("funcionario_deve_trocar_senha")),
            "comunicados": [_formatar_comunicado(linha) for linha in linhas],
            "empresas_portal": empresas_portal,
            "categorias": CATEGORIAS_COMUNICADO,
            "titulo_max": TITULO_COMUNICADO_MAX,
            "texto_max": TEXTO_COMUNICADO_MAX,
        },
    )


def _e_json(request: Request) -> bool:
    # Exige Content-Type JSON: um <form> de outro site não consegue mandar
    # isso sem preflight de CORS — defesa extra além do SameSite=lax.
    return request.headers.get("content-type", "").split(";")[0].strip() == "application/json"


@app.post("/api/equipe/comunicados")
async def api_publicar_comunicado(request: Request):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)
    if not _e_json(request):
        return JSONResponse({"erro": "Formato inválido."}, status_code=415)
    try:
        corpo = await request.json()
    except ValueError:
        return JSONResponse({"erro": "Formato inválido."}, status_code=400)
    if not isinstance(corpo, dict):
        return JSONResponse({"erro": "Formato inválido."}, status_code=400)

    titulo = " ".join(str(corpo.get("titulo", "")).split())
    texto = str(corpo.get("texto", "")).replace("\r\n", "\n").strip()
    categoria = str(corpo.get("categoria", ""))
    destino = str(corpo.get("destino", "todos"))
    empresa = str(corpo.get("empresa", "")).strip()

    if len(titulo) < 3 or len(titulo) > TITULO_COMUNICADO_MAX:
        return JSONResponse(
            {"erro": f"O título precisa ter entre 3 e {TITULO_COMUNICADO_MAX} caracteres."}, status_code=400
        )
    if not texto or len(texto) > TEXTO_COMUNICADO_MAX:
        return JSONResponse(
            {"erro": f"Escreva o texto do comunicado (até {TEXTO_COMUNICADO_MAX} caracteres)."}, status_code=400
        )
    if categoria not in CATEGORIAS_COMUNICADO:
        return JSONResponse({"erro": "Categoria inválida."}, status_code=400)
    if destino not in ("todos", "empresa"):
        return JSONResponse({"erro": "Destino inválido."}, status_code=400)

    empresa_digitos = None
    empresa_nome = None
    if destino == "empresa":
        empresa_digitos = _somente_digitos(empresa)
        if len(empresa_digitos) not in (11, 14):
            return JSONResponse({"erro": "Informe um CNPJ (14 dígitos) ou CPF (11 dígitos) válido."}, status_code=400)
        dados = await acessorias.buscar_empresa(empresa_digitos)
        if dados:
            empresa_nome = dados.get("Fantasia") or dados.get("Razao") or dados.get("Identificador")
        else:
            # Acessórias fora do ar ou empresa inexistente: só aceita se a
            # empresa tiver login no portal (senão ninguém veria o aviso).
            with obter_conexao() as conexao:
                conhecidas = {
                    _somente_digitos(linha["identificador_acessorias"])
                    for linha in conexao.execute("SELECT DISTINCT identificador_acessorias FROM usuario_empresas")
                }
            if empresa_digitos not in conhecidas:
                return JSONResponse({"erro": "Empresa não encontrada na Acessórias."}, status_code=400)
            empresa_nome = empresa
        empresa_nome = (empresa_nome or "")[:200]

    with obter_conexao() as conexao:
        cursor = conexao.execute(
            """INSERT INTO comunicados
                   (titulo, texto, categoria, empresa_digitos, empresa_nome, autor_funcionario_id, autor_nome)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                titulo, texto, categoria, empresa_digitos, empresa_nome,
                request.session["funcionario_id"], request.session.get("funcionario_nome", "Equipe"),
            ),
        )
    return {"ok": True, "id": cursor.lastrowid}


@app.post("/api/equipe/comunicados/remover")
async def api_remover_comunicado(request: Request):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)
    if not _e_json(request):
        return JSONResponse({"erro": "Formato inválido."}, status_code=415)
    try:
        corpo = await request.json()
        comunicado_id = int(corpo.get("id"))
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"erro": "Comunicado inválido."}, status_code=400)

    with obter_conexao() as conexao:
        cursor = conexao.execute(
            "UPDATE comunicados SET removido_em = datetime('now') WHERE id = ? AND removido_em IS NULL",
            (comunicado_id,),
        )
    if cursor.rowcount == 0:
        return JSONResponse({"erro": "Comunicado não encontrado (talvez já removido)."}, status_code=404)
    return {"ok": True}

# --- Formulário de contato da landing page (leads) -----------------------
# A landing page (index.html + js/main.js) envia o formulário para
# POST /api/contato; o lead fica na tabela leads (ver database.py) e a
# equipe vê tudo em /pages/equipe-leads.html. Imports ficam aqui, junto do
# bloco, pra não mexer no topo do arquivo.
import json  # noqa: E402
import re  # noqa: E402
from contextlib import closing  # noqa: E402
from datetime import timedelta, timezone  # noqa: E402


LIMITE_CONTATO_POR_IP_HORA = 5
# Rede de segurança caso alguém troque de IP (ou forje X-Forwarded-For) pra
# fugir do limite por IP: acima disso, ninguém envia por uma hora.
LIMITE_CONTATO_GLOBAL_HORA = 60
TAMANHO_MAXIMO_CORPO_CONTATO = 16 * 1024
LEADS_POR_PAGINA = 25
# Brasil não tem horário de verão desde 2019 — offset fixo evita depender
# do pacote tzdata no container.
FUSO_BRASILIA = timezone(timedelta(hours=-3))

_LIMITES_CONTATO = {
    "nome": 100, "empresa": 80, "email": 254, "telefone": 25,
    "segmento": 60, "mensagem": 1000, "origem": 200,
}
_RE_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
_RE_CONTROLE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _limpar_linha(valor: str) -> str:
    """Campo de uma linha: tira caracteres de controle e junta espaços."""
    return " ".join(_RE_CONTROLE.sub(" ", valor).split())


def _limpar_texto(valor: str) -> str:
    """Campo de várias linhas (mensagem): mantém só a quebra de linha."""
    valor = valor.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    return _RE_CONTROLE.sub("", valor).strip()


def _validar_contato(corpo: dict) -> tuple[dict, dict]:
    """Devolve (dados limpos, erros por campo). Mensagens iguais às do
    js/main.js, pra pessoa ver o mesmo texto se a validação do navegador
    for contornada."""
    dados: dict[str, str] = {}
    erros: dict[str, str] = {}
    for campo, limite in _LIMITES_CONTATO.items():
        bruto = corpo.get(campo, "")
        if bruto is None:
            bruto = ""
        if not isinstance(bruto, str):
            erros[campo] = "Valor inválido."
            dados[campo] = ""
            continue
        limpo = _limpar_texto(bruto) if campo == "mensagem" else _limpar_linha(bruto)
        if len(limpo) > limite:
            erros[campo] = f"Use no máximo {limite} caracteres."
        dados[campo] = limpo

    if "nome" not in erros and len(dados["nome"]) < 2:
        erros["nome"] = "Informe o seu nome."
    if "email" not in erros:
        dados["email"] = dados["email"].lower()
        if not _RE_EMAIL.match(dados["email"]):
            erros["email"] = "Informe um e-mail válido."
    if "telefone" not in erros:
        digitos = re.sub(r"\D", "", dados["telefone"])
        if len(digitos) in (12, 13) and digitos.startswith("55"):
            digitos = digitos[2:]  # veio com o código do país
        if len(digitos) not in (10, 11) or digitos[0] == "0":
            erros["telefone"] = "Informe um WhatsApp com DDD."
        dados["telefone"] = digitos
    if corpo.get("consentimento") is not True:
        erros["consentimento"] = "É preciso autorizar o contato para enviar."
    return dados, erros


def _registrar_contato(dados: dict | None, ip: str, user_agent: str) -> int | str:
    """Confere o limite e grava, tudo numa transação só (BEGIN IMMEDIATE),
    pra dois envios simultâneos do mesmo IP não passarem os dois pelo
    limite. dados=None é envio barrado pela armadilha anti-robô: conta no
    limite, mas não vira lead. Devolve o id do lead, 0 (robô) ou
    "limite"."""
    with closing(obter_conexao()) as conexao, conexao:
        conexao.execute("BEGIN IMMEDIATE")
        conexao.execute("DELETE FROM contato_envios WHERE criado_em < datetime('now', '-1 day')")
        do_ip, total = conexao.execute(
            """SELECT COALESCE(SUM(ip = ?), 0), COUNT(*) FROM contato_envios
               WHERE criado_em >= datetime('now', '-1 hour')""",
            (ip,),
        ).fetchone()
        if do_ip >= LIMITE_CONTATO_POR_IP_HORA or total >= LIMITE_CONTATO_GLOBAL_HORA:
            return "limite"
        conexao.execute("INSERT INTO contato_envios (ip) VALUES (?)", (ip,))
        if dados is None:
            return 0
        cursor = conexao.execute(
            """INSERT INTO leads (nome, empresa, email, telefone, segmento, mensagem,
                                  origem, ip, user_agent, consentimento_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (dados["nome"], dados["empresa"], dados["email"], dados["telefone"], dados["segmento"],
             dados["mensagem"], dados["origem"], ip, user_agent),
        )
        return cursor.lastrowid


@app.post("/api/contato")
async def api_contato(request: Request):
    # Exigir JSON barra o envio por <form> de outro site (que só consegue
    # mandar text/plain ou urlencoded sem passar por CORS).
    if "application/json" not in request.headers.get("content-type", ""):
        return JSONResponse({"erro": "Formato de envio inválido."}, status_code=415)
    bruto = await request.body()
    if len(bruto) > TAMANHO_MAXIMO_CORPO_CONTATO:
        return JSONResponse({"erro": "Mensagem grande demais."}, status_code=413)
    try:
        corpo = json.loads(bruto)
    except ValueError:
        corpo = None
    if not isinstance(corpo, dict):
        return JSONResponse({"erro": "Formato de envio inválido."}, status_code=400)

    ip = _ip_cliente(request)
    user_agent = request.headers.get("user-agent", "")[:300]

    # Armadilha anti-robô (campo "site" escondido): responde como sucesso
    # pra não ensinar o robô a contorná-la, mas não guarda nada.
    if corpo.get("site"):
        await run_in_threadpool(_registrar_contato, None, ip, user_agent)
        return {"ok": True}

    dados, erros = _validar_contato(corpo)
    if erros:
        return JSONResponse(
            {"erro": "Revise os campos destacados para continuar.", "campos": erros}, status_code=400
        )

    resultado = await run_in_threadpool(_registrar_contato, dados, ip, user_agent)
    if resultado == "limite":
        return JSONResponse(
            {"erro": "Recebemos vários envios seguidos da sua conexão. Tente de novo mais tarde "
                     "ou fale com a gente pelo WhatsApp."},
            status_code=429,
        )

    # Lead gravado (id em `resultado`): aqui é o ponto para disparar o aviso
    # por e-mail ao escritório.
    return {"ok": True}


def _formatar_data_utc(texto: str | None) -> str:
    """SQLite grava datetime('now') em UTC; a equipe lê no horário de Brasília."""
    if not texto:
        return ""
    try:
        momento = datetime.strptime(texto, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return texto
    return momento.astimezone(FUSO_BRASILIA).strftime("%d/%m/%Y %H:%M")


def _formatar_telefone(digitos: str) -> str:
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return digitos


def _listar_leads(pagina: int) -> dict:
    with closing(obter_conexao()) as conexao:
        total = conexao.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        pendentes = conexao.execute("SELECT COUNT(*) FROM leads WHERE contatado_em IS NULL").fetchone()[0]
        total_paginas = max(1, -(-total // LEADS_POR_PAGINA))
        pagina = min(max(pagina, 1), total_paginas)
        linhas = conexao.execute(
            """SELECT id, nome, empresa, email, telefone, segmento, mensagem, origem,
                      criado_em, contatado_em, contatado_por
               FROM leads ORDER BY id DESC LIMIT ? OFFSET ?""",
            (LEADS_POR_PAGINA, (pagina - 1) * LEADS_POR_PAGINA),
        ).fetchall()
    leads = [
        {
            "id": linha["id"],
            "nome": linha["nome"],
            "empresa": linha["empresa"],
            "email": linha["email"],
            "telefone": _formatar_telefone(linha["telefone"]),
            "whatsapp": f"55{linha['telefone']}",
            "segmento": linha["segmento"],
            "mensagem": linha["mensagem"],
            "origem": linha["origem"],
            "recebido_em": _formatar_data_utc(linha["criado_em"]),
            "contatado": bool(linha["contatado_em"]),
            "contatado_em": _formatar_data_utc(linha["contatado_em"]),
            "contatado_por": linha["contatado_por"] or "",
        }
        for linha in linhas
    ]
    return {
        "leads": leads,
        "total": total,
        "pendentes": pendentes,
        "pagina": pagina,
        "total_paginas": total_paginas,
    }


@app.get("/pages/equipe-leads.html")
async def pagina_equipe_leads(request: Request):
    guarda = _guarda_equipe(request)
    if guarda:
        return guarda
    try:
        pagina = int(request.query_params.get("pagina", 1))
    except ValueError:
        pagina = 1
    contexto = await run_in_threadpool(_listar_leads, pagina)
    contexto.update({
        "nome_usuario": request.session.get("funcionario_nome", "equipe"),
        "deve_trocar_senha": bool(request.session.get("funcionario_deve_trocar_senha")),
    })
    resposta = templates.TemplateResponse(request, "equipe-leads.html", contexto)
    # Dados pessoais de quem pediu contato: nada de guardar em cache.
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


def _alternar_contatado(lead_id: int, funcionario: str) -> dict | None:
    with closing(obter_conexao()) as conexao, conexao:
        linha = conexao.execute("SELECT contatado_em FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if not linha:
            return None
        if linha["contatado_em"]:
            conexao.execute("UPDATE leads SET contatado_em = NULL, contatado_por = NULL WHERE id = ?", (lead_id,))
        else:
            conexao.execute(
                "UPDATE leads SET contatado_em = datetime('now'), contatado_por = ? WHERE id = ?",
                (funcionario, lead_id),
            )
        atual = conexao.execute(
            "SELECT contatado_em, contatado_por FROM leads WHERE id = ?", (lead_id,)
        ).fetchone()
    return {
        "contatado": bool(atual["contatado_em"]),
        "contatado_em": _formatar_data_utc(atual["contatado_em"]),
        "contatado_por": atual["contatado_por"] or "",
    }


@app.post("/api/equipe/leads/alternar-contatado")
async def api_alternar_lead_contatado(request: Request):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)
    try:
        corpo = await request.json()
        lead_id = int(corpo.get("id"))
    except (ValueError, TypeError, AttributeError):
        return JSONResponse({"erro": "Lead inválido."}, status_code=400)

    funcionario = request.session.get("funcionario_nome", "equipe")
    resultado = await run_in_threadpool(_alternar_contatado, lead_id, funcionario)
    if resultado is None:
        return JSONResponse({"erro": "Lead não encontrado."}, status_code=404)
    return {"ok": True, **resultado}

# --- Senha: troca, "esqueceu sua senha?" e primeiro acesso por e-mail -----

def _ip_cliente(request: Request) -> str:
    # Em produção o IP vem do X-Real-IP, que a borda do Railway preenche.
    # Nunca de X-Forwarded-For: o visitante consegue mandar esse cabeçalho
    # já preenchido e burlar os limites por IP.
    if HTTPS_ONLY:
        ip = request.headers.get("x-real-ip", "").strip()
        if ip:
            return ip[:64]
    return (request.client.host if request.client else "") or "desconhecido"


async def _corpo_json(request: Request) -> dict:
    try:
        corpo = await request.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _validar_nova_senha(nova_senha: str, confirmacao: str) -> JSONResponse | None:
    if not nova_senha or nova_senha != confirmacao:
        return JSONResponse({"erro": "As senhas não coincidem."}, status_code=400)
    if len(nova_senha) < TAMANHO_MINIMO_SENHA:
        return JSONResponse(
            {"erro": f"Use uma senha com pelo menos {TAMANHO_MINIMO_SENHA} caracteres."}, status_code=400
        )
    return None


async def _trocar_senha_da_conta(
    request: Request, tipo: str, conta_id: int, troca_obrigatoria_na_sessao: bool
) -> JSONResponse | None:
    """Usado por /api/trocar-senha e /api/equipe/trocar-senha. Exige a
    senha atual, a não ser na troca obrigatória logo depois de entrar com
    a senha provisória (a pessoa acabou de digitá-la no login). Só conta
    como troca obrigatória se a sessão E o banco ainda disserem que sim —
    se a senha já foi trocada por outro caminho (ex.: link do e-mail),
    uma sessão antiga não ganha passe livre. Devolve a resposta de erro,
    ou None quando a senha foi trocada."""
    corpo = await _corpo_json(request)
    senha_atual = str(corpo.get("senhaAtual", ""))
    nova_senha = str(corpo.get("novaSenha", ""))
    confirmacao = str(corpo.get("confirmacao", ""))

    erro = _validar_nova_senha(nova_senha, confirmacao)
    if erro:
        return erro

    tabela = "funcionarios" if tipo == "equipe" else "usuarios"
    with obter_conexao() as conexao:
        conta = conexao.execute(
            f"SELECT email, senha_hash, deve_trocar_senha FROM {tabela} WHERE id = ?", (conta_id,)
        ).fetchone()
    if not conta:
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    troca_obrigatoria = troca_obrigatoria_na_sessao and bool(conta["deve_trocar_senha"])
    if not troca_obrigatoria:
        if not senha_atual:
            return JSONResponse({"erro": "Informe sua senha atual.", "exigeSenhaAtual": True}, status_code=400)
        # Mesmo contador do login: uma sessão roubada não vira um jeito de
        # chutar a senha atual sem limite.
        ip = _ip_cliente(request)
        if login_bloqueado(conta["email"], ip):
            return JSONResponse(
                {"erro": "Muitas tentativas. Aguarde alguns minutos e tente de novo.", "exigeSenhaAtual": True},
                status_code=429,
            )
        if not await run_in_threadpool(verificar_senha, senha_atual, conta["senha_hash"]):
            registrar_falha_login(conta["email"], ip)
            return JSONResponse({"erro": "Senha atual incorreta.", "exigeSenhaAtual": True}, status_code=400)

    # Principalmente com a senha provisória comum do lote inicial
    # (criar_usuarios_em_massa.py --senha-comum): "trocar" pela mesma senha
    # deixaria a conta aberta pra qualquer outro cliente que a conhece.
    if await run_in_threadpool(verificar_senha, nova_senha, conta["senha_hash"]):
        return JSONResponse({"erro": "A nova senha precisa ser diferente da atual."}, status_code=400)

    novo_hash = await run_in_threadpool(gerar_hash, nova_senha)
    # Uma senha por e-mail: se a mesma pessoa tem conta de cliente e de
    # equipe (login único), as duas mudam juntas.
    with obter_conexao() as conexao:
        for tabela_conta in ("usuarios", "funcionarios"):
            conexao.execute(
                f"UPDATE {tabela_conta} SET senha_hash = ?, deve_trocar_senha = 0 WHERE email = ?",
                (novo_hash, conta["email"]),
            )
    return None


MENSAGEM_REDEFINICAO_NEUTRA = (
    "Se este e-mail estiver cadastrado no portal, você vai receber em instantes um link "
    "para definir uma nova senha. Confira também a caixa de spam."
)


def _enviar_link_redefinicao(tipo: str, email: str) -> None:
    """Roda em segundo plano (BackgroundTasks → threadpool), depois que a
    resposta já saiu: o tempo de resposta é o mesmo exista a conta ou não,
    e o SMTP (bloqueante) nunca trava o event loop. Nada aqui vai pro log
    além de avisos genéricos — nunca o token nem o link."""
    if not email_envio.smtp_configurado():
        print("AVISO: pedido de redefinição de senha recebido, mas o SMTP não está configurado "
              "(SMTP_USUARIO/SMTP_SENHA) — nenhum e-mail foi enviado. Ver backend/.env.example.")
        return
    # Login único: procura primeiro na área pedida e depois na outra. Como
    # a senha é uma só por e-mail, redefinir uma conta vale pras duas.
    ordem = (("equipe", "funcionarios"), ("cliente", "usuarios"))
    if tipo != "equipe":
        ordem = ordem[::-1]
    conta = None
    with obter_conexao() as conexao:
        for tipo_conta, tabela in ordem:
            conta = conexao.execute(f"SELECT id, email, nome FROM {tabela} WHERE email = ?", (email,)).fetchone()
            if conta:
                tipo = tipo_conta
                break
    if not conta:
        return
    token = emitir_token_redefinicao(tipo, conta["id"])
    email_envio.enviar_link_redefinicao(conta["email"], conta["nome"], token)


@app.post("/api/esqueci-senha")
async def esqueci_senha(request: Request, tarefas: BackgroundTasks):
    """Sem autoatendimento de cadastro: isso só manda link pra quem já tem
    conta criada pelo escritório. A resposta é sempre a mesma, exista o
    e-mail ou não — não dá pra usar isso pra descobrir quem é cliente."""
    corpo = await _corpo_json(request)
    email = str(corpo.get("email", "")).strip().lower()
    tipo = "equipe" if corpo.get("tipo") == "equipe" else "cliente"

    if not email or "@" not in email or len(email) > TAMANHO_MAXIMO_EMAIL:
        return JSONResponse({"erro": "Informe um e-mail válido."}, status_code=400)

    ip = _ip_cliente(request)
    if redefinicao_bloqueada(email, ip):
        return JSONResponse(
            {"erro": "Muitos pedidos seguidos. Aguarde um pouco e tente de novo."}, status_code=429
        )
    registrar_pedido_redefinicao(email, ip)

    tarefas.add_task(_enviar_link_redefinicao, tipo, email)
    return {"ok": True, "mensagem": MENSAGEM_REDEFINICAO_NEUTRA}


@app.post("/api/redefinir-senha/validar")
async def validar_link_redefinicao(request: Request):
    """Só pra página avisar logo de cara que o link expirou, em vez de
    deixar a pessoa digitar a senha nova duas vezes à toa."""
    corpo = await _corpo_json(request)
    return {"valido": token_redefinicao_valido(str(corpo.get("token", "")))}


@app.post("/api/redefinir-senha")
async def redefinir_senha(request: Request):
    corpo = await _corpo_json(request)
    token = str(corpo.get("token", ""))
    nova_senha = str(corpo.get("novaSenha", ""))
    confirmacao = str(corpo.get("confirmacao", ""))

    erro = _validar_nova_senha(nova_senha, confirmacao)
    if erro:
        return erro

    resultado = await run_in_threadpool(consumir_token_redefinicao, token, nova_senha)
    if not resultado:
        return JSONResponse(
            {"erro": "Este link é inválido, já foi usado ou expirou. Peça um novo.", "linkInvalido": True},
            status_code=400,
        )

    tipo, conta_id = resultado
    email = email_da_conta(tipo, conta_id)
    if email:
        # Provou que é dono da caixa de e-mail — destrava o login dele.
        limpar_falhas_login(email)
    return {"ok": True, "destino": "login.html"}

# --- Painel da equipe: detalhe e resposta de solicitação ----------------
# Tudo aqui exige sessão de FUNCIONÁRIO (_tem_sessao_equipe) — sessão de
# cliente não serve. O SolID vem da URL, mas só aceita dígitos: nunca
# monta caminho da Acessórias com texto livre do navegador.

STATUS_EDICAO_SOLICITACAO = {"R", "C", "F"}  # Resolvendo, Cliente, Finalizada (documentação de POST /requests/{id})
TAMANHO_MAXIMO_COMENTARIO = 5000
TAMANHO_MAXIMO_CORPO_JSON = 32 * 1024


def _sol_id_valido(sol_id: str) -> bool:
    return sol_id.isascii() and sol_id.isdigit() and len(sol_id) <= 12


def _data_solicitacao(texto: str) -> date | None:
    """A Acessórias manda datas de solicitação como "DD/MM/AAAA HH:MM:SS";
    prazo pode vir só com a data, e às vezes em ISO — aceita os três."""
    texto = (texto or "").strip()
    return _data(texto.split(" ")[0], "%d/%m/%Y") or _data(texto[:10])


def _formatar_detalhe_solicitacao(item: dict) -> dict:
    # O texto dos comentários vem da Acessórias já escapado como HTML
    # ("MARTINS &amp; GUERRA") — desfaz aqui; o navegador mostra tudo via
    # textContent, então nada disso vira HTML de verdade.
    from html import unescape

    status = item.get("SolStatus", "")
    prazo = _data_solicitacao(item.get("SolDTPrazo", ""))
    interacoes = []
    for cmt in item.get("SolInteracoes", []):
        anexos = [
            {"nome": str(anexo.get("Nome") or "Anexo"), "url": anexo["Url"]}
            for anexo in (cmt.get("CmtAnx") or [])
            if isinstance(anexo, dict) and str(anexo.get("Url", "")).startswith("https://")
        ]
        interacoes.append({
            "autor": unescape(str(cmt.get("CmtUsuario", ""))),
            "data": cmt.get("CmtDH", ""),
            "privado": cmt.get("CmtTipo", "") != "Público",
            "texto": unescape(str(cmt.get("CmtText", ""))),
            "anexos": anexos,
        })
    responsaveis = item.get("SolOfficeResp") or []
    return {
        "id": item.get("SolID", ""),
        "assunto": item.get("SolAssunto", ""),
        "empresa": item.get("EmpNome") or item.get("EmpCNPJ", ""),
        "departamento": item.get("DptoNome", ""),
        "tipo": item.get("SolTipo", ""),
        "interna": item.get("SolTipo", "") == "Interna",
        "solicitante": item.get("SolUsuario", ""),
        "responsaveis": ", ".join(str(r) for r in responsaveis) if isinstance(responsaveis, list) else str(responsaveis),
        "abertura": item.get("SolDHAbertura", ""),
        "ultima_atualizacao": item.get("SolDHUAt", ""),
        "prazo": prazo.strftime("%d/%m/%Y") if prazo else "",
        "status": status,
        "classe_status": _STATUS_PARA_CLASSE.get(status, "andamento"),
        "finalizada": status == "Finalizada",
        "interacoes": interacoes,
    }


@app.get("/api/equipe/solicitacoes/{sol_id}")
async def api_equipe_detalhe_solicitacao(request: Request, sol_id: str):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)
    if not _sol_id_valido(sol_id):
        return JSONResponse({"erro": "Solicitação inválida."}, status_code=400)

    item = await acessorias.buscar_solicitacao(sol_id)
    if not item:
        return JSONResponse(
            {"erro": "Não conseguimos carregar esta solicitação na Acessórias. Tente de novo."}, status_code=502
        )
    return {"ok": True, "solicitacao": _formatar_detalhe_solicitacao(item)}


@app.post("/api/equipe/solicitacoes/{sol_id}/atualizar")
async def api_equipe_atualizar_solicitacao(request: Request, sol_id: str):
    """Comentar + definir status (e opcionalmente prazo) num envio só —
    a Acessórias exige as duas coisas juntas. Se a solicitação estiver
    finalizada e o status escolhido não for "Finalizada", manda
    reabrir=1 sozinho: é isso que a equipe quis dizer."""
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)
    if not _sol_id_valido(sol_id):
        return JSONResponse({"erro": "Solicitação inválida."}, status_code=400)
    # Só JSON: um <form> de outro site não consegue mandar
    # application/json sem passar pelo preflight de CORS (que não
    # liberamos) — defesa extra além do SameSite=Lax do cookie.
    if not request.headers.get("content-type", "").startswith("application/json"):
        return JSONResponse({"erro": "Formato de envio inválido."}, status_code=415)
    try:
        if int(request.headers.get("content-length", "0")) > TAMANHO_MAXIMO_CORPO_JSON:
            return JSONResponse({"erro": "Comentário grande demais."}, status_code=413)
        corpo = await request.json()
    except ValueError:
        return JSONResponse({"erro": "Formato de envio inválido."}, status_code=400)
    if not isinstance(corpo, dict):
        return JSONResponse({"erro": "Formato de envio inválido."}, status_code=400)

    comentario = str(corpo.get("comentario", "")).strip()
    status_sol = str(corpo.get("status", ""))
    privado = corpo.get("privado") is True
    prazo_texto = str(corpo.get("prazo", "") or "").strip()

    if not comentario:
        return JSONResponse({"erro": "Escreva um comentário — a Acessórias exige um ao atualizar."}, status_code=400)
    if len(comentario) > TAMANHO_MAXIMO_COMENTARIO:
        return JSONResponse(
            {"erro": f"Comentário passa de {TAMANHO_MAXIMO_COMENTARIO} caracteres — resuma um pouco."}, status_code=400
        )
    if status_sol not in STATUS_EDICAO_SOLICITACAO:
        return JSONResponse({"erro": "Escolha um status válido."}, status_code=400)
    prazo = None
    if prazo_texto:
        prazo_data = _data(prazo_texto)
        if not prazo_data or len(prazo_texto) != 10:
            return JSONResponse({"erro": "Prazo inválido."}, status_code=400)
        prazo = prazo_data.isoformat()

    # Lido do cache na maioria das vezes (a equipe acabou de abrir o
    # detalhe) — confirma que a solicitação existe e diz se precisa reabrir.
    atual = await acessorias.buscar_solicitacao(sol_id)
    if not atual:
        return JSONResponse(
            {"erro": "Não conseguimos carregar esta solicitação na Acessórias. Tente de novo."}, status_code=502
        )
    finalizada = atual.get("SolStatus") == "Finalizada"
    if finalizada and status_sol == "F":
        return JSONResponse(
            {"erro": "Esta solicitação já está finalizada. Para reabrir, escolha Resolvendo ou Com o cliente."},
            status_code=400,
        )
    if status_sol == "C" and atual.get("SolTipo") == "Interna":
        return JSONResponse({"erro": "Solicitação interna não pode ficar com o status Com o cliente."}, status_code=400)

    resultado = await acessorias.atualizar_solicitacao(
        sol_id, comentario, status_sol, privado=privado, reabrir=finalizada, data_prazo=prazo,
    )
    if "Erro" in resultado:
        return JSONResponse({"erro": resultado["Erro"]}, status_code=400)

    # Devolve o detalhe já atualizado (o cache foi invalidado na escrita),
    # pra tela redesenhar o histórico e a etiqueta de status sem outro clique.
    novo = await acessorias.buscar_solicitacao(sol_id)
    return {"ok": True, "solicitacao": _formatar_detalhe_solicitacao(novo) if novo else None}


# --- Tour guiado do Henrique (js/tour.js) -------------------------------
# Lista fechada: o id vem da página, mas só estes são aceitos.
TOURS_CLIENTE = {"inicio", "comunicados", "solicitacoes", "documentos", "obrigacoes",
                 "calendario", "financeiro", "perfil"}
TOURS_EQUIPE = {"equipe-atendimento", "equipe-comunicados", "equipe-leads"}
STATUS_TOUR = {"concluido": "concluido", "pulado": "pulado"}


def _tours_vistos(tipo: str, conta_id: int) -> list[str]:
    with obter_conexao() as conexao:
        return [linha["tour"] for linha in conexao.execute(
            "SELECT tour FROM tours_vistos WHERE tipo = ? AND conta_id = ?", (tipo, conta_id)
        )]


def _salvar_tour(tipo: str, conta_id: int, tour: str, status: str) -> None:
    with obter_conexao() as conexao:
        conexao.execute(
            """INSERT INTO tours_vistos (tipo, conta_id, tour, status) VALUES (?, ?, ?, ?)
               ON CONFLICT (tipo, conta_id, tour) DO UPDATE SET status = excluded.status,
               visto_em = datetime('now')""",
            (tipo, conta_id, tour, status),
        )


@app.get("/api/tours")
async def api_tours_cliente(request: Request):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada."}, status_code=401)
    return {"vistos": await run_in_threadpool(_tours_vistos, "cliente", request.session["usuario_id"])}


@app.post("/api/tours/{tour}")
async def api_salvar_tour_cliente(request: Request, tour: str):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada."}, status_code=401)
    status = STATUS_TOUR.get(str((await _corpo_json(request)).get("status", "")))
    if tour not in TOURS_CLIENTE or not status:
        return JSONResponse({"erro": "Tour inválido."}, status_code=400)
    await run_in_threadpool(_salvar_tour, "cliente", request.session["usuario_id"], tour, status)
    return {"ok": True}


@app.get("/api/equipe/tours")
async def api_tours_equipe(request: Request):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada."}, status_code=401)
    return {"vistos": await run_in_threadpool(_tours_vistos, "equipe", request.session["funcionario_id"])}


@app.post("/api/equipe/tours/{tour}")
async def api_salvar_tour_equipe(request: Request, tour: str):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada."}, status_code=401)
    status = STATUS_TOUR.get(str((await _corpo_json(request)).get("status", "")))
    if tour not in TOURS_EQUIPE or not status:
        return JSONResponse({"erro": "Tour inválido."}, status_code=400)
    await run_in_threadpool(_salvar_tour, "equipe", request.session["funcionario_id"], tour, status)
    return {"ok": True}


# Um app só para os dois domínios: www.facchiniassessoria.com.br é a lead
# page, portal.facchiniassessoria.com.br cai direto no login.
def _no_portal(request: Request) -> bool:
    return (request.url.hostname or "").startswith("portal.")


@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/index.html", methods=["GET", "HEAD"])
async def raiz(request: Request):
    if _no_portal(request):
        return RedirectResponse("/pages/login.html", status_code=303)
    return FileResponse(RAIZ / "index.html")


@app.api_route("/robots.txt", methods=["GET", "HEAD"])
async def robots(request: Request):
    if _no_portal(request):
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return FileResponse(RAIZ / "robots.txt")


@app.api_route("/sitemap.xml", methods=["GET", "HEAD"])
async def sitemap():
    return FileResponse(RAIZ / "sitemap.xml")


@app.api_route("/site.webmanifest", methods=["GET", "HEAD"])
async def manifesto():
    return FileResponse(RAIZ / "site.webmanifest", media_type="application/manifest+json")


# Só as pastas públicas — nunca a raiz do projeto, que expõe backend/.env,
# o banco SQLite e o código-fonte. Páginas do portal com rota própria
# (acima) têm precedência sobre o estático de /pages.
for _pasta in ("css", "js", "assets", "pages"):
    app.mount(f"/{_pasta}", ArquivosEstaticos(directory=RAIZ / _pasta), name=_pasta)
