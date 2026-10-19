#!/usr/bin/env python3
"""Constrói o índice local "e-mail de contato -> quais empresas" a partir
de TODAS as empresas cadastradas na Acessórias.

Por quê: a API só deixa consultar os contatos de uma empresa por vez
(GET /companies/{id}?contacts) — não existe uma busca "em quais empresas
esta pessoa aparece". Sem esse índice, criar o login de alguém que atende
várias empresas exigia o administrador já saber (e digitar) o CNPJ de
cada uma na mão. Rodando isso uma vez, create_user.py passa a encontrar
as outras empresas sozinho a partir do e-mail.

Respeita o limite de 100 requisições/minuto da Acessórias: processa em
lotes com pausa entre eles. Para ~280 empresas isso leva alguns minutos —
não precisa rodar toda hora, só quando o cadastro de clientes na
Acessórias mudar bastante (ou nunca ter sido rodado ainda).

Uso:
    cd backend
    python3 indexar_contatos.py
"""
import asyncio
import time

from dotenv import load_dotenv

load_dotenv()

import acessorias  # noqa: E402
from database import inicializar_schema, obter_conexao  # noqa: E402

TAMANHO_LOTE = 30  # bem abaixo do limite de 100/min — 80 na prática estourava
# o limite (a lista de empresas paginada já consome uma fatia da cota, e as
# chamadas de um lote saem quase todas juntas, não espalhadas no minuto)
PAUSA_ENTRE_LOTES_SEGUNDOS = 65


async def main() -> None:
    inicializar_schema()

    print("Buscando lista de empresas na Acessórias...")
    empresas = await acessorias.listar_todas_empresas()
    # dict.fromkeys em vez de set(): remove duplicata (a mesma empresa pode
    # aparecer em duas páginas do ListAll) mantendo a ordem original.
    identificadores = list(dict.fromkeys(e["Identificador"] for e in empresas if e.get("Identificador")))
    print(f"{len(identificadores)} empresas encontradas. Buscando contatos de cada uma "
          f"(em lotes de {TAMANHO_LOTE}, respeitando o limite de requisições da Acessórias)...")

    encontrados: list[tuple[str, str, str]] = []  # (email, identificador, nome_contato)
    for inicio in range(0, len(identificadores), TAMANHO_LOTE):
        lote = identificadores[inicio:inicio + TAMANHO_LOTE]
        resultados = await asyncio.gather(*(acessorias.listar_contatos(i) for i in lote))
        for identificador, contatos in zip(lote, resultados):
            for contato in contatos:
                email = contato.get("E-mail", "").strip().lower()
                if email:
                    encontrados.append((email, identificador, contato.get("Nome", "")))

        processadas = min(inicio + TAMANHO_LOTE, len(identificadores))
        print(f"  {processadas}/{len(identificadores)} empresas processadas...")
        if processadas < len(identificadores):
            time.sleep(PAUSA_ENTRE_LOTES_SEGUNDOS)

    with obter_conexao() as conexao:
        conexao.execute("DELETE FROM contatos_acessorias")
        conexao.executemany(
            """INSERT OR IGNORE INTO contatos_acessorias (email, identificador_acessorias, nome_contato)
               VALUES (?, ?, ?)""",
            encontrados,
        )

    print(f"\nÍndice atualizado: {len(encontrados)} contatos encontrados em {len(identificadores)} empresas.")


if __name__ == "__main__":
    asyncio.run(main())
