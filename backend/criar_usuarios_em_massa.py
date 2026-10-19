#!/usr/bin/env python3
"""Cria login pra todo cliente já identificado no índice local de contatos
(gerado por indexar_contatos.py) — em vez de rodar create_user.py cliente
por cliente, isso faz de uma vez só pra todo mundo que já apareceu como
contato em alguma empresa na Acessórias. Não bate na API de novo: os
dados já foram puxados quando o índice foi gerado, então isso só
materializa login local a partir do que já está em contatos_acessorias.

Cada conta nova recebe sua própria senha temporária aleatória (nunca uma
senha fixa compartilhada) e troca obrigatória no primeiro acesso — mesma
regra já usada em create_user.py e criar_funcionario.py, só que em lote.

Seguro rodar de novo: nunca sobrescreve um login que já existe (login
manual continua com a senha que tiver), só cria o que falta e sempre
revincula TODAS as empresas encontradas pro mesmo e-mail no índice.

Uso:
    cd backend
    python3 criar_usuarios_em_massa.py
"""
import asyncio

from dotenv import load_dotenv

load_dotenv()

from auth import gerar_hash, gerar_senha_temporaria  # noqa: E402
from database import inicializar_schema, obter_conexao  # noqa: E402


async def main() -> None:
    inicializar_schema()

    with obter_conexao() as conexao:
        linhas = conexao.execute(
            "SELECT email, identificador_acessorias, nome_contato FROM contatos_acessorias ORDER BY email"
        ).fetchall()

    por_email: dict[str, dict] = {}
    for linha in linhas:
        entrada = por_email.setdefault(linha["email"], {"nome": linha["nome_contato"], "identificadores": []})
        entrada["identificadores"].append(linha["identificador_acessorias"])

    print(f"{len(por_email)} clientes distintos encontrados no índice local.")

    criados = 0
    ja_existiam = 0
    empresas_vinculadas = 0
    senhas_geradas: dict[str, str] = {}

    with obter_conexao() as conexao:
        for email, dados in por_email.items():
            existente = conexao.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
            if existente:
                usuario_id = existente["id"]
                ja_existiam += 1
            else:
                senha_temporaria = gerar_senha_temporaria()
                senhas_geradas[email] = senha_temporaria
                cursor = conexao.execute(
                    "INSERT INTO usuarios (email, senha_hash, nome) VALUES (?, ?, ?)",
                    (email, gerar_hash(senha_temporaria), dados["nome"]),
                )
                usuario_id = cursor.lastrowid
                criados += 1

            for identificador in dados["identificadores"]:
                resultado = conexao.execute(
                    """INSERT INTO usuario_empresas (usuario_id, identificador_acessorias)
                       VALUES (?, ?)
                       ON CONFLICT (usuario_id, identificador_acessorias) DO NOTHING""",
                    (usuario_id, identificador),
                )
                if resultado.rowcount:
                    empresas_vinculadas += 1

    print(f"Contas novas criadas: {criados}")
    print(f"Contas que já existiam (login preservado, só religuei empresas): {ja_existiam}")
    print(f"Vínculos empresa-cliente novos: {empresas_vinculadas}")
    if senhas_geradas:
        print("Senha temporária de cada conta nova (troca obrigatória no primeiro acesso):")
        for email, senha in senhas_geradas.items():
            print(f"  {email}: {senha}")


if __name__ == "__main__":
    asyncio.run(main())
