"""Conexão e schema do SQLite usado pelo login.

Um arquivo único (facchini.db), fora do controle de versão — cada
ambiente (local, produção) tem o seu.
"""
import os
import sqlite3
from pathlib import Path

# Em produção aponta pro volume persistente (ex.: /data/facchini.db no
# Railway) — o disco do container é apagado a cada deploy.
CAMINHO_DB = Path(os.environ.get("FACCHINI_DB_PATH") or Path(__file__).parent / "facchini.db")


def obter_conexao() -> sqlite3.Connection:
    conexao = sqlite3.connect(CAMINHO_DB)
    conexao.row_factory = sqlite3.Row
    return conexao


def inicializar_schema() -> None:
    with obter_conexao() as conexao:
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL,
                nome TEXT NOT NULL,
                deve_trocar_senha INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        colunas = {linha["name"] for linha in conexao.execute("PRAGMA table_info(usuarios)")}
        if "deve_trocar_senha" not in colunas:
            conexao.execute("ALTER TABLE usuarios ADD COLUMN deve_trocar_senha INTEGER NOT NULL DEFAULT 1")
        # Um cliente pode ter mais de uma empresa vinculada ao mesmo e-mail
        # (troca de empresa dentro do portal) — por isso é tabela à parte,
        # não uma coluna em usuarios.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS usuario_empresas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                identificador_acessorias TEXT NOT NULL,
                apelido TEXT,
                UNIQUE (usuario_id, identificador_acessorias)
            )
        """)
        # Índice local de "e-mail de contato -> em quais empresas ele
        # aparece na Acessórias". A API só deixa consultar contatos de uma
        # empresa por vez (não existe busca pelo lado do contato), então
        # backend/indexar_contatos.py varre todas as empresas de vez em
        # quando e guarda aqui — create_user.py lê daqui, não da API direto.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS contatos_acessorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                identificador_acessorias TEXT NOT NULL,
                nome_contato TEXT NOT NULL,
                atualizado_em TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (email, identificador_acessorias)
            )
        """)
        conexao.execute("CREATE INDEX IF NOT EXISTS idx_contatos_email ON contatos_acessorias (email)")

        # Login da equipe (painel interno) — tabela própria, separada de
        # usuarios de propósito: são níveis de acesso bem diferentes (um
        # funcionário vê solicitações de toda a Facchini, um cliente só
        # vê a própria empresa), então não faz sentido misturar no mesmo
        # login nem na mesma sessão.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS funcionarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                senha_hash TEXT NOT NULL,
                nome TEXT NOT NULL,
                deve_trocar_senha INTEGER NOT NULL DEFAULT 1,
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Histórico de acessos (item 11 da referência do usuário sobre o
        # Acessórias) — não existe na API deles, é 100% nosso. Guarda
        # e-mail/nome em vez de FK pra usuarios/funcionarios de propósito:
        # um só registro cobre os dois tipos de login sem duplicar tabela,
        # e continua legível mesmo se a conta for removida depois.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS historico_acessos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                nome TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('cliente', 'equipe')),
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conexao.execute("CREATE INDEX IF NOT EXISTS idx_historico_email ON historico_acessos (email)")

        # "Marcar como pago" (item 6 da referência) — a API de invoices da
        # Acessórias é só leitura, não existe endpoint pra escrever status
        # de pagamento lá. Fica só local, e como eles não devolvem nenhum
        # ID de boleto (só Competencia/Vencimento/Valor/Status), a chave
        # composta (empresa + vencimento + valor + competência) é o que
        # temos pra identificar "o mesmo boleto" de forma estável.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS boletos_pagos_local (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identificador_acessorias TEXT NOT NULL,
                vencimento TEXT NOT NULL,
                valor TEXT NOT NULL,
                competencia TEXT NOT NULL,
                marcado_em TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (identificador_acessorias, vencimento, valor, competencia)
            )
        """)

        # Comunicados do escritório pros clientes — a API da Acessórias não
        # tem nada de avisos/notícias (conferido na documentação oficial),
        # então é 100% nosso, publicado pela equipe em
        # pages/equipe-comunicados.html. empresa_digitos NULL = vale pra
        # todos os clientes; preenchido = só aquela empresa. Guarda só os
        # dígitos do CNPJ/CPF porque usuario_empresas guarda formatado
        # ("12.345.678/0001-90") e a equipe pode digitar de qualquer jeito —
        # comparar só dígitos dos dois lados evita "não achou" por pontuação.
        # Remover é lógico (removido_em), não DELETE: fica o histórico de
        # quem publicou o quê, caso um cliente pergunte depois.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS comunicados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                texto TEXT NOT NULL,
                categoria TEXT NOT NULL CHECK (categoria IN ('comunicado', 'informativo', 'institucional')),
                empresa_digitos TEXT,
                empresa_nome TEXT,
                autor_funcionario_id INTEGER,
                autor_nome TEXT NOT NULL,
                criado_em TEXT NOT NULL DEFAULT (datetime('now')),
                removido_em TEXT
            )
        """)
        conexao.execute(
            "CREATE INDEX IF NOT EXISTS idx_comunicados_empresa ON comunicados (empresa_digitos, removido_em)"
        )
