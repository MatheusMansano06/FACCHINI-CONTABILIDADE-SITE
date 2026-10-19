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
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # precisa rodar antes de importar acessorias (lê env em cada chamada, mas o token já deve estar carregado)

import acessorias  # noqa: E402
from auth import (  # noqa: E402
    TAMANHO_MINIMO_SENHA,
    gerar_hash,
    identificador_bloqueado,
    limpar_tentativas,
    registrar_tentativa_falha,
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
    mecanismo — auth.registrar_tentativa_falha)."""
    with obter_conexao() as conexao:
        conexao.execute(
            "INSERT INTO historico_acessos (email, nome, tipo) VALUES (?, ?, ?)",
            (email, nome, tipo),
        )


@app.post("/api/login")
async def login(request: Request):
    corpo = await request.json()
    email = str(corpo.get("usuario", "")).strip().lower()
    senha = str(corpo.get("senha", ""))

    if not email or not senha:
        return JSONResponse({"erro": "Informe usuário e senha."}, status_code=400)

    if identificador_bloqueado(email):
        return JSONResponse(
            {"erro": "Muitas tentativas. Aguarde alguns minutos e tente de novo."},
            status_code=429,
        )

    with obter_conexao() as conexao:
        usuario = conexao.execute(
            "SELECT id, nome, senha_hash, deve_trocar_senha FROM usuarios WHERE email = ?", (email,)
        ).fetchone()

        if not usuario or not verificar_senha(senha, usuario["senha_hash"]):
            registrar_tentativa_falha(email)
            return JSONResponse({"erro": "Usuário ou senha incorretos."}, status_code=401)

        empresas = [
            linha["identificador_acessorias"]
            for linha in conexao.execute(
                "SELECT identificador_acessorias FROM usuario_empresas WHERE usuario_id = ? ORDER BY id",
                (usuario["id"],),
            )
        ]

    limpar_tentativas(email)
    _registrar_acesso(email, usuario["nome"], "cliente")
    deve_trocar_senha = bool(usuario["deve_trocar_senha"])
    request.session["usuario_id"] = usuario["id"]
    request.session["nome"] = usuario["nome"]
    request.session["empresas"] = empresas
    request.session["deve_trocar_senha"] = deve_trocar_senha

    # Uma empresa só: entra direto nela, sem tela extra. Mais de uma: cai
    # numa tela de escolha primeiro (mesmo padrão da própria Acessórias) —
    # empresa_ativa fica vazia até o cliente escolher.
    if len(empresas) == 1:
        request.session["empresa_ativa"] = empresas[0]
        destino = "portal-inicio.html"
    else:
        request.session["empresa_ativa"] = None
        destino = "selecionar-empresa.html" if empresas else "portal-inicio.html"

    return {"ok": True, "destino": destino}


@app.post("/api/trocar-senha")
async def trocar_senha(request: Request):
    if not _tem_sessao(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    corpo = await request.json()
    nova_senha = str(corpo.get("novaSenha", ""))
    confirmacao = str(corpo.get("confirmacao", ""))

    if not nova_senha or nova_senha != confirmacao:
        return JSONResponse({"erro": "As senhas não coincidem."}, status_code=400)
    if len(nova_senha) < TAMANHO_MINIMO_SENHA:
        return JSONResponse(
            {"erro": f"Use uma senha com pelo menos {TAMANHO_MINIMO_SENHA} caracteres."}, status_code=400
        )

    senha_hash = gerar_hash(nova_senha)
    with obter_conexao() as conexao:
        conexao.execute(
            "UPDATE usuarios SET senha_hash = ?, deve_trocar_senha = 0 WHERE id = ?",
            (senha_hash, request.session["usuario_id"]),
        )

    # Sem redirecionamento: o cliente continua na mesma página do portal,
    # só o aviso flutuante some. Trocou aqui, não aparece mais em nenhum
    # login futuro — mas se só fechar sem trocar, volta a aparecer na
    # próxima vez que entrar (deve_trocar_senha continua 1 no banco).
    request.session["deve_trocar_senha"] = False
    return {"ok": True}


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

@app.post("/api/equipe/login")
async def equipe_login(request: Request):
    corpo = await request.json()
    email = str(corpo.get("usuario", "")).strip().lower()
    senha = str(corpo.get("senha", ""))

    if not email or not senha:
        return JSONResponse({"erro": "Informe usuário e senha."}, status_code=400)

    if identificador_bloqueado(email):
        return JSONResponse(
            {"erro": "Muitas tentativas. Aguarde alguns minutos e tente de novo."},
            status_code=429,
        )

    with obter_conexao() as conexao:
        funcionario = conexao.execute(
            "SELECT id, nome, senha_hash, deve_trocar_senha FROM funcionarios WHERE email = ?", (email,)
        ).fetchone()

    if not funcionario or not verificar_senha(senha, funcionario["senha_hash"]):
        registrar_tentativa_falha(email)
        return JSONResponse({"erro": "Usuário ou senha incorretos."}, status_code=401)

    limpar_tentativas(email)
    _registrar_acesso(email, funcionario["nome"], "equipe")
    request.session["funcionario_id"] = funcionario["id"]
    request.session["funcionario_nome"] = funcionario["nome"]
    request.session["funcionario_deve_trocar_senha"] = bool(funcionario["deve_trocar_senha"])
    return {"ok": True, "destino": "equipe-atendimento.html"}


@app.post("/api/equipe/trocar-senha")
async def equipe_trocar_senha(request: Request):
    if not _tem_sessao_equipe(request):
        return JSONResponse({"erro": "Sessão expirada. Faça login de novo."}, status_code=401)

    corpo = await request.json()
    nova_senha = str(corpo.get("novaSenha", ""))
    confirmacao = str(corpo.get("confirmacao", ""))

    if not nova_senha or nova_senha != confirmacao:
        return JSONResponse({"erro": "As senhas não coincidem."}, status_code=400)
    if len(nova_senha) < TAMANHO_MINIMO_SENHA:
        return JSONResponse(
            {"erro": f"Use uma senha com pelo menos {TAMANHO_MINIMO_SENHA} caracteres."}, status_code=400
        )

    senha_hash = gerar_hash(nova_senha)
    with obter_conexao() as conexao:
        conexao.execute(
            "UPDATE funcionarios SET senha_hash = ?, deve_trocar_senha = 0 WHERE id = ?",
            (senha_hash, request.session["funcionario_id"]),
        )

    request.session["funcionario_deve_trocar_senha"] = False
    return {"ok": True}


@app.get("/equipe/logout")
async def equipe_logout(request: Request):
    request.session.pop("funcionario_id", None)
    request.session.pop("funcionario_nome", None)
    request.session.pop("funcionario_deve_trocar_senha", None)
    return RedirectResponse("/pages/equipe-login.html", status_code=303)


def _tem_sessao_equipe(request: Request) -> bool:
    return bool(request.session.get("funcionario_id"))


def _guarda_equipe(request: Request) -> RedirectResponse | None:
    if not _tem_sessao_equipe(request):
        return RedirectResponse("/pages/equipe-login.html", status_code=303)
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


# Um app só para os dois domínios: www.facchiniassessoria.com.br é a lead
# page, portal.facchiniassessoria.com.br cai direto no login.
def _no_portal(request: Request) -> bool:
    return (request.url.hostname or "").startswith("portal.")


@app.get("/")
@app.get("/index.html")
async def raiz(request: Request):
    if _no_portal(request):
        return RedirectResponse("/pages/login.html", status_code=303)
    return FileResponse(RAIZ / "index.html")


@app.get("/robots.txt")
async def robots(request: Request):
    if _no_portal(request):
        return PlainTextResponse("User-agent: *\nDisallow: /\n")
    return FileResponse(RAIZ / "robots.txt")


@app.get("/sitemap.xml")
async def sitemap():
    return FileResponse(RAIZ / "sitemap.xml")


@app.get("/site.webmanifest")
async def manifesto():
    return FileResponse(RAIZ / "site.webmanifest", media_type="application/manifest+json")


# Só as pastas públicas — nunca a raiz do projeto, que expõe backend/.env,
# o banco SQLite e o código-fonte. Páginas do portal com rota própria
# (acima) têm precedência sobre o estático de /pages.
for _pasta in ("css", "js", "assets", "pages"):
    app.mount(f"/{_pasta}", ArquivosEstaticos(directory=RAIZ / _pasta), name=_pasta)
