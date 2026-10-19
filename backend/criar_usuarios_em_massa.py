#!/usr/bin/env python3
"""Cria login pra todo cliente já identificado no índice local de contatos
(gerado por indexar_contatos.py) — em vez de rodar create_user.py cliente
por cliente, isso faz de uma vez só pra todo mundo que já apareceu como
contato em alguma empresa na Acessórias. Não bate na API de novo: os
dados já foram puxados quando o índice foi gerado, então isso só
materializa login local a partir do que já está em contatos_acessorias.

Por padrão cada conta nova recebe sua própria senha temporária aleatória
e troca obrigatória no primeiro acesso — mesma regra já usada em
create_user.py e criar_funcionario.py, só que em lote. As senhas geradas
são impressas no fim, pra repassar a cada cliente.

Com --senha-comum, todas as contas NOVAS desta execução recebem uma mesma
senha provisória, digitada na hora (getpass, duas vezes, nunca aparece na
tela nem fica no código ou no histórico do terminal) — o escritório comunica
essa senha aos clientes e cada um é obrigado a trocar no primeiro acesso
(deve_trocar_senha = 1; o portal não aceita "trocar" pela mesma senha).
Enquanto um cliente não troca, qualquer pessoa que saiba a senha comum e o
e-mail dele entra na conta — por isso vale avisar a todos pra trocar logo,
ou mandar o link de "Esqueceu sua senha?" (primeiro acesso por e-mail).
Contas que já existiam não são tocadas, com ou sem a opção.

Seguro rodar de novo: nunca sobrescreve um login que já existe (login
manual continua com a senha que tiver), só cria o que falta e sempre
revincula TODAS as empresas encontradas pro mesmo e-mail no índice.

Uso:
    cd backend
    python3 criar_usuarios_em_massa.py                 # senha aleatória por conta
    python3 criar_usuarios_em_massa.py --senha-comum   # uma senha provisória pra todas as novas
"""
import argparse
import asyncio

from dotenv import load_dotenv

load_dotenv()

from auth import gerar_hash, gerar_senha_temporaria, ler_senha_confirmada  # noqa: E402
from database import inicializar_schema, obter_conexao  # noqa: E402


async def main(senha_comum: str | None = None) -> None:
    inicializar_schema()
    # Um hash só pra senha comum: bcrypt já embute um salt aleatório, e
    # gerar um por conta só deixaria o lote centenas de vezes mais lento.
    hash_senha_comum = gerar_hash(senha_comum) if senha_comum else None

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
                if hash_senha_comum:
                    senha_hash = hash_senha_comum
                else:
                    senha_temporaria = gerar_senha_temporaria()
                    senhas_geradas[email] = senha_temporaria
                    senha_hash = gerar_hash(senha_temporaria)
                cursor = conexao.execute(
                    "INSERT INTO usuarios (email, senha_hash, nome, deve_trocar_senha) VALUES (?, ?, ?, 1)",
                    (email, senha_hash, dados["nome"]),
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
    elif hash_senha_comum and criados:
        print("Todas as contas novas usam a senha provisória comum digitada agora "
              "(troca obrigatória no primeiro acesso).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cria login pra todo cliente do índice local de contatos.")
    parser.add_argument(
        "--senha-comum",
        action="store_true",
        help="pede (sem mostrar na tela) uma senha provisória única pra todas as contas novas",
    )
    argumentos = parser.parse_args()

    senha_comum = None
    if argumentos.senha_comum:
        print("Senha provisória comum para todas as contas NOVAS (troca obrigatória no primeiro acesso).")
        senha_comum = ler_senha_confirmada("Senha provisória")
        if not senha_comum:
            raise SystemExit(1)

    asyncio.run(main(senha_comum))
