# Publicação e configuração

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
corrigir uma por uma antes de publicar.** Se alguma não for verdade hoje,
apagar a pergunta inteira é melhor do que suavizar a resposta.

## 1. Dados que precisam ser preenchidos antes de ir ao ar

O site está com dados de exemplo em alguns pontos. **Nenhum deles pode ir para produção como está.**

| Onde | O que trocar |
|---|---|
| `index.html` | `<link rel="canonical">` — domínio real |
| `index.html` | URLs de Open Graph (`og:url`, `og:image`) |
| `index.html` | Link do WhatsApp no formulário e no rodapé |
| `index.html` | Instagram e LinkedIn da empresa |
| `index.html` | Endereço, telefone e e-mail do escritório |
| `index.html` | JSON-LD: conferir endereço completo e adicionar `telephone` |
| `index.html` | `href="#"` da Política de Privacidade (2 ocorrências) |
| `index.html` | "+16 anos" e "+1.000 empresas" — confirmar se seguem corretos |
| `js/main.js` | `CONFIG.whatsapp` — formato `55` + DDD + número |
| `robots.txt` / `sitemap.xml` | domínio real |

Para localizar tudo de uma vez:

```bash
grep -rn "TODO\|facchinicontabil.com.br\|5519000000000" index.html js/ robots.txt sitemap.xml
```

## 2. Formulário de contato

Hoje o formulário **valida os dados no navegador e abre o WhatsApp** — não existe backend.

Para receber os leads por e-mail ou gravá-los num banco, preencha `CONFIG.endpointFormulario`
em `js/main.js`. Ele envia um `POST` com JSON:

```json
{ "nome": "", "empresa": "", "email": "", "telefone": "", "segmento": "", "mensagem": "", "origem": "/" }
```

**Ao apontar para um domínio externo** (Formspree, Web3Forms, uma função serverless etc.),
é obrigatório liberá-lo na CSP do `index.html`, senão o navegador bloqueia o envio:

```
connect-src 'self' https://seu-endpoint.exemplo;
form-action 'self' https://seu-endpoint.exemplo;
```

### O que o backend ainda precisa fazer

A validação no navegador é conveniência, não segurança — ela pode ser contornada.
Quem receber os dados precisa, obrigatoriamente:

- validar todos os campos de novo no servidor;
- tratar os dados como texto ao gravar ou exibir (nunca interpolar em HTML ou SQL cru);
- aplicar limite de requisições por IP (o campo-armadilha do formulário barra apenas robôs simples);
- registrar a base legal do consentimento LGPD junto com data/hora e IP.

## 3. Backend do login (FastAPI + SQLite)

`pages/login.html` e `pages/portal-inicio.html` não são mais arquivos
estáticos "soltos" — o backend em `backend/` (FastAPI) é quem serve o
site inteiro agora, porque ele precisa interceptar o pedido das páginas
do portal e checar a sessão antes de entregá-las. Isso muda a hospedagem:
**precisa de um servidor que rode um processo Python continuamente**, não
serve mais hospedagem puramente estática (item 4 abaixo detalha).

### Rodando o backend

```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env        # preencher SESSION_SECRET (ver instrução no arquivo)
venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

Isso serve **o site inteiro** (lead page, login e portal) em
`http://servidor:8000` — não só a API. Normalmente fica atrás de um Nginx
que faz proxy da porta 80/443 para a 8000 e cuida do TLS.

### Criando contas de cliente

Não existe autocadastro (decisão de produto). Para dar acesso a um
cliente nomeado, direto no servidor:

```bash
cd backend && venv/bin/python3 create_user.py
```

Pede e-mail, nome e senha, e cria (ou atualiza a senha de) o usuário no
SQLite.

### Variáveis de ambiente obrigatórias em produção

| Variável | Para quê |
|---|---|
| `SESSION_SECRET` | Assina o cookie de sessão. Gerar com `python3 -c "import secrets; print(secrets.token_hex(32))"` — com `ENV=production` e sem essa variável, o backend **se recusa a subir**. Em desenvolvimento, sem ela, gera uma chave aleatória por execução (sessões caem a cada restart). |
| `ENV=production` | Faz o cookie de sessão exigir HTTPS (`Secure`). Sem HTTPS na frente, **não defina isso**, ou o login trava. |

### Manter o processo no ar

Um `uvicorn` rodando direto no terminal cai quando a sessão SSH fecha.
Em produção, gerencie o processo com `systemd`, `supervisor` ou
`pm2`/`forever` (o que já existir no servidor). O essencial: o comando é
sempre `venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000` a partir de
`backend/`, com `SESSION_SECRET` e `ENV=production` no ambiente.

### Se a hospedagem só rodar PHP (hospedagem compartilhada, sem processo Python)

Esse backend precisa de um servidor que execute um processo Python
próprio (VPS/Cloud). Hospedagem compartilhada tradicional (cPanel, só
PHP+MySQL) não roda o FastAPI como está — nesse caso o backend teria que
ser reescrito em PHP antes de publicar. Confirme com a hospedagem qual é
o tipo de plano antes de seguir com o deploy.

## 4. Cabeçalhos de segurança no servidor

A CSP já vai no `<meta>` do HTML, mas três proteções **só funcionam como header HTTP**.
Configure no servidor ou na CDN:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: frame-ancestors 'none'
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

`frame-ancestors` é o que impede o site de ser embutido em um iframe de terceiros
(clickjacking) — e é ignorado quando declarado via `<meta>`.

## 5. O que subir para o servidor

Suba tudo, **exceto**:

- `assets/images/originais/` — PNGs em alta (18 MB). São a fonte para reprocessar os
  assets, não são usados pelo site. Já estão no `.gitignore` e bloqueados no `robots.txt`.
- `.claude/` — configuração local de desenvolvimento.
- `backend/venv/`, `backend/facchini.db`, `backend/.env` — específicos de cada
  ambiente; recriar no servidor (item 3 acima), nunca copiar do seu computador.

Não há build no frontend (HTML/CSS/JS estáticos), mas **agora precisa de um
servidor que rode o backend Python** (item 3) — hospedagem puramente estática
(Netlify, Vercel, Cloudflare Pages, GitHub Pages) não serve mais sozinha,
porque nenhuma delas mantém um processo FastAPI no ar. Um VPS/Cloud com
Nginx na frente do Uvicorn funciona.

### Cache recomendado

```
assets/*   →  Cache-Control: public, max-age=31536000, immutable
css/*, js/*  →  Cache-Control: public, max-age=86400
index.html   →  Cache-Control: no-cache
```

Ao trocar uma imagem ou o CSS, mude o nome do arquivo (ou acrescente `?v=2` no link)
para o cache longo não servir a versão antiga.

## 6. Rodar localmente

```bash
# só a lead page (sem login/portal, não precisa do backend)
python3 -m http.server 4173
```

Depois abra <http://127.0.0.1:4173>. Precisa ser via servidor: abrir o `index.html`
direto pelo `file://` quebra as fontes e a CSP.

Para testar login e portal, use o backend (item 3) — ele serve o site
inteiro, inclusive a lead page, em `http://127.0.0.1:8000`.
