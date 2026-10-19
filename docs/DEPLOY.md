# Publicação e configuração

## Como está publicado

| Endereço | Onde roda | O que serve |
|---|---|---|
| `www.facchiniassessoria.com.br` | Railway | Lead page (`index.html`) e política de privacidade |
| `portal.facchiniassessoria.com.br` | Railway | Login e portal do cliente e da equipe |
| `facchiniassessoria.com.br` (sem www) | Locaweb | Só redireciona para o `www` (via `.htaccess`) |
| E-mail `@facchiniassessoria.com.br` | Locaweb | Caixas postais (MX/SPF) — **não mexer** |
| Zona DNS | Locaweb | Aponta os domínios acima |

O `www` e o `portal` são **o mesmo app** (FastAPI em `backend/app.py`), num
único serviço do Railway. O app decide o que entregar pelo domínio do pedido
(`_no_portal` em `backend/app.py`): no `portal.` a raiz vai para o login e o
`robots.txt` bloqueia tudo; em qualquer outro domínio (inclusive `localhost`)
a raiz é a lead page.

## 0. PRIORIDADE — as respostas da seção "Dúvidas" são um rascunho

A seção `#duvidas` do `index.html` responde cinco objeções comuns, e as respostas
foram **escritas como sugestão, não apuradas com a Facchini**. Elas contêm
promessas comerciais concretas:

- que a transição do contador antigo é feita pelo escritório e a empresa não para;
- que a proposta é fechada e **sem taxa escondida**;
- que o atendimento cobre **todo o Brasil**;
- que **cada cliente tem um contador responsável, com nome e telefone**;
- que os documentos ficam em nuvem com acesso controlado e tratamento LGPD.

Cada uma dessas frases é um compromisso que o cliente vai cobrar. **Conferir e
corrigir uma por uma.** Se alguma não for verdade hoje, apagar a pergunta
inteira é melhor do que suavizar a resposta.

## 1. Pendências de conteúdo

| Onde | O que falta |
|---|---|
| `index.html` | Link do LinkedIn aponta para `https://www.linkedin.com/` genérico — trocar pela página da empresa |
| `index.html` | "+16 anos" e "+1.000 empresas" — confirmar se seguem corretos |
| `index.html` | JSON-LD: endereço completo (hoje só cidade/UF) |
| `pages/politica-de-privacidade.html` | Versão **provisória**: revisar com o jurídico e completar CNPJ e endereço |

Já resolvido: domínio real em canonical/Open Graph/`robots.txt`/`sitemap.xml`,
e-mail de contato (`contato@facchiniassessoria.com.br`), WhatsApp e Instagram.

## 2. Formulário de contato

Hoje o formulário **valida os dados no navegador e abre o WhatsApp** — os
leads não são gravados em lugar nenhum.

Para receber os leads por e-mail ou gravá-los num banco, preencha
`CONFIG.endpointFormulario` em `js/main.js`. Ele envia um `POST` com JSON:

```json
{ "nome": "", "empresa": "", "email": "", "telefone": "", "segmento": "", "mensagem": "", "origem": "/" }
```

O caminho mais simples é uma rota nova no próprio `backend/app.py` (mesmo
domínio, a CSP já permite). **Ao apontar para um domínio externo** (Formspree,
Web3Forms etc.), é obrigatório liberá-lo na CSP do `index.html`, senão o
navegador bloqueia o envio:

```
connect-src 'self' https://seu-endpoint.exemplo;
form-action 'self' https://seu-endpoint.exemplo;
```

Quem receber os dados precisa, obrigatoriamente: validar tudo de novo no
servidor; tratar os dados como texto (nunca interpolar em HTML ou SQL cru);
limitar requisições por IP (o campo-armadilha só barra robôs simples); e
registrar a base legal do consentimento LGPD com data/hora e IP.

## 3. Railway (site e portal)

Projeto **`facchini-portal`**, serviço **`portal`**, ambiente `production`.

### Como o build funciona

| Arquivo | Papel |
|---|---|
| `requirements.txt` (raiz) | Dependências Python. `backend/requirements.txt` só aponta para ele (`-r ../requirements.txt`) |
| `railpack.json` | Comando de start: `cd backend && uvicorn app:app --host 0.0.0.0 --port $PORT ...` |
| `railway.json` | Healthcheck em `/pages/login.html` e reinício automático em falha |

O builder do Railway copia só o `requirements.txt` da raiz antes de instalar —
por isso as versões ficam nele, não em `backend/`.

### Publicar uma alteração

Não há deploy automático por Git. A partir da raiz do projeto:

```bash
railway up --service portal --ci
```

Sobe a pasta respeitando o `.gitignore` (nunca envia `.env`, banco, `venv` ou
`assets/images/originais/`) e mostra o log do build. Termina com
`Deploy complete` ou `Deploy failed`.

### Variáveis de ambiente

| Variável | Valor / para quê |
|---|---|
| `SESSION_SECRET` | Assina o cookie de sessão. Com `ENV=production` e sem ela, o app **se recusa a subir**. Gerar com `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ACESSORIAS_API_TOKEN` | Token da API da Acessórias (no Acessórias: engrenagem → "API Token") |
| `ENV` | `production` — cookie só via HTTPS e cabeçalho HSTS |
| `FACCHINI_DB_PATH` | `/data/facchini.db` — o banco fica no volume |
| `PORT` | `8080` — mesma porta configurada nos domínios |
| `RESEND_API_KEY` | Chave (só envio) da API do **Resend**, que manda os e-mails de "Esqueceu sua senha?". O Railway bloqueia SMTP de saída no plano Hobby, por isso o envio é por API. Domínio verificado no Resend com 3 registros DNS na Locaweb: `TXT resend._domainkey`, `CNAME rsend`, `CNAME send` |
| `EMAIL_REMETENTE` | `portal@facchiniassessoria.com.br` (caixa criada só pro site) |
| `SMTP_USUARIO`, `SMTP_SENHA` | Alternativa ao Resend (só funciona no plano Pro do Railway). Opcionais: `SMTP_HOST`, `SMTP_PORT`, `URL_PORTAL` |

Segredos são definidos por quem tem o valor, direto no terminal, sem exibi-lo:

```bash
railway variables --service portal --set "NOME=valor"
```

### Banco de dados (volume)

O SQLite fica no volume `portal-dados`, montado em `/data`. O disco do
container é apagado a cada deploy; o volume não. O schema é criado/migrado
sozinho na inicialização (`inicializar_schema()` em `backend/database.py`).

**Nunca copie o `backend/facchini.db` do seu computador para produção.** O
banco local tem contas criadas com a antiga senha padrão fixa.

### Domínios e DNS

| Domínio | Registro na zona DNS da Locaweb |
|---|---|
| `portal.facchiniassessoria.com.br` | `CNAME portal → y8hxr2ki.up.railway.app` + `TXT _railway-verify.portal` |
| `www.facchiniassessoria.com.br` | `CNAME www → 2ytu9q4f.up.railway.app` + `TXT _railway-verify.www` |

Os TXT `_railway-verify.*` provam ao Railway que o domínio é nosso — não
apagar. Também ficam na zona (não apagar): o TXT `google-site-verification=...` na raiz (verificação do Google Search Console, feita em 19/10/2026) e os registros do Resend (`TXT resend._domainkey`, `CNAME rsend`, `CNAME send`). O certificado HTTPS é emitido e renovado pelo Railway. Se ele travar
em "issuing" ou falhar com erro interno, peça uma nova emissão (no painel do
domínio no Railway, ou pela API) — o do `www` precisou de duas tentativas.

O domínio sem `www` não pode apontar para o Railway: o Railway exige CNAME, e
CNAME não pode coexistir com os registros de e-mail (MX/TXT) na raiz. Por
isso ele fica na Locaweb, redirecionando (seção 5).

### Segurança no servidor

- Só `css/`, `js/`, `assets/` e `pages/` são servidos como arquivo estático —
  **nunca** a raiz do projeto (que expõe `backend/.env`, o banco e o código).
  Arquivos da raiz que precisam ser públicos (`index.html`, `robots.txt`,
  `sitemap.xml`, `site.webmanifest`) têm rota própria em `backend/app.py`.
- Os cabeçalhos HTTP de segurança são enviados pelo próprio app (middleware
  `cabecalhos_seguranca`): `X-Content-Type-Options`, `Referrer-Policy`,
  `Content-Security-Policy: frame-ancestors 'none'`, `Permissions-Policy` e,
  em produção, `Strict-Transport-Security`. A CSP completa continua no
  `<meta>` de cada página.
- Cache: em produção os arquivos estáticos saem com `ETag`/`Last-Modified`
  (o navegador revalida). Em desenvolvimento o cache é desligado. Ao trocar
  uma imagem com o mesmo nome, acrescente `?v=2` no link se quiser forçar.

## 4. Contas de acesso

Não existe autocadastro (decisão de produto): contas são criadas pelo
administrador, rodando scripts dentro do servidor. Toda conta criada ou com
senha redefinida pelo administrador nasce com **troca obrigatória**: enquanto
a senha provisória não for trocada, o servidor bloqueia portal e painel
(páginas e APIs) e manda para `pages/trocar-senha.html`
(`exigir_troca_de_senha` em `backend/app.py`). O cliente também pode criar a
própria senha pelo "Esqueceu sua senha?" (link por e-mail, vale 1 hora).

As contas do lote inicial (223 clientes e 4 da equipe, migradas em
19/10/2026) usam a senha provisória comum do escritório.

Em produção, os scripts rodam dentro do container do Railway, que enxerga o
volume e as variáveis:

```bash
railway ssh --service portal
cd /app/backend
```

| Script | Para quê |
|---|---|
| `python indexar_contatos.py` | Varre todas as empresas na Acessórias e guarda "e-mail de contato → empresas". Leva alguns minutos (respeita o limite de 100 req/min). Rodar antes dos outros e sempre que o cadastro mudar bastante |
| `python criar_usuarios_em_massa.py` | Cria um login para cada e-mail do índice, com senha temporária individual, e lista `e-mail: senha` no fim. Nunca sobrescreve conta existente |
| `python create_user.py` | Cria ou redefine um cliente específico (interativo; acha as outras empresas pelo índice) |
| `python criar_funcionario.py` | Cria ou redefine um login da equipe (painel de atendimento) |

As senhas listadas por `criar_usuarios_em_massa.py` aparecem só no terminal
de quem rodou: entregue a cada cliente por um canal individual e não guarde a
lista.

## 5. Locaweb (DNS, e-mail e redirecionamento)

Plano **Hospedagem I**. Depois da migração do site para o Railway, ela cuida só de:

- **Zona DNS** — painel DNS da Locaweb. Os registros de e-mail (MX, SPF,
  `autodiscover`, `pop`, `imap`, `smtp`, `webmail`) **não podem ser alterados**.
- **E-mail** — as caixas `@facchiniassessoria.com.br`.
- **Redirecionamento do domínio sem www** — a hospedagem serve só um
  `.htaccess` que manda tudo para `https://www.facchiniassessoria.com.br`.

### Subir o redirecionamento

```bash
scripts/montar-locaweb.sh
scripts/subir-locaweb.sh
```

O primeiro gera `deploy-locaweb/.htaccess` a partir de `.htaccess-locaweb`; o
segundo envia por FTP para `public_html/` (pede a senha do FTP, usuário
`facchiniassessoria1`). `scripts/listar-ftp.sh` só lista as pastas, para
conferir. O FTP da Locaweb **não tem criptografia** — não rode em Wi-Fi público.

Para o `https://facchiniassessoria.com.br` redirecionar sem alerta, o
certificado Let's Encrypt do domínio precisa ser emitido no painel da
hospedagem (Informações de domínio → Let's Encrypt).

### Histórico

Em 18/10/2026 a hospedagem respondia 403/404 para qualquer arquivo: tinha sido
migrada para um servidor novo e o IP do domínio não foi atualizado. O suporte
(protocolo 2610182397493) corrigiu o registro A para `179.188.54.225`. Se o
domínio sem www voltar a falhar, cite esse protocolo.

## 6. Rodar localmente

```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env        # preencher ACESSORIAS_API_TOKEN; SESSION_SECRET é opcional local
venv/bin/uvicorn app:app --reload --port 8000
```

Abra <http://127.0.0.1:8000>: a raiz é a lead page e o login fica em
`/pages/login.html`. Para simular o domínio do portal:

```bash
curl -H "Host: portal.facchiniassessoria.com.br" http://127.0.0.1:8000/
```

**Não defina `ENV=production` localmente** (sem HTTPS o cookie de sessão não
"cola" e o login parece não funcionar). Precisa ser via servidor: abrir o
`index.html` direto pelo `file://` quebra as fontes e a CSP.

## 7. O que nunca vai para produção

- `assets/images/originais/` — PNGs em alta (18 MB), fonte para reprocessar
  as imagens. Fora do Git e bloqueados no `robots.txt`.
- `backend/.env`, `backend/facchini.db`, `backend/venv/` — específicos de cada
  ambiente, todos no `.gitignore` (e, por isso, fora do `railway up`).
- `.claude/` — configuração local de desenvolvimento.
