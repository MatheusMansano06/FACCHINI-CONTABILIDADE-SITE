# Site Facchini Assessoria Contábil

Landing page de captação de leads em HTML, CSS e JavaScript estáticos — sem
framework, sem build. O login e o portal do cliente (`pages/login.html` e
`pages/portal-inicio.html`) são servidos pelo backend em `backend/`
(FastAPI + SQLite), que também cuida da sessão do cliente.

```bash
# lead page sozinha (sem login/portal, não precisa do backend)
python3 -m http.server 4173   # depois abra http://127.0.0.1:4173

# site completo, com login e portal funcionando — ver backend/README abaixo
cd backend && venv/bin/uvicorn app:app --reload --port 8000
```

## Estrutura

```
index.html              página única (a lead page)
css/
  fonts.css             @font-face das fontes auto-hospedadas
  base.css              tokens de design, reset, tipografia e botões
  site.css              seções da página e responsividade
js/
  deteccao.js           marca que há JS antes da primeira pintura
  main.js               menu, revelações, contadores, máscara e formulário
assets/
  fonts/                Archivo e Inter (subset latino, .woff2)
  icons/                favicons gerados a partir do símbolo da marca
  images/               fotos otimizadas em WebP + variantes responsivas
  images/originais/     PNGs em alta — fonte de verdade, fora do deploy
  logo/                 logo com fundo transparente (versão original e branca)
backend/                API de login + SQLite — ver seção abaixo
docs/DEPLOY.md          publicação, backend em produção e dados pendentes
pages/
  login.html            tela de acesso do cliente
  portal-inicio.html    painel do cliente após o login
```

## Login e portal do cliente

Autenticação real, com senha com hash (bcrypt) e sessão em cookie assinado —
ver detalhes de execução e publicação em [docs/DEPLOY.md](docs/DEPLOY.md).

- **Sem autocadastro.** Contas são criadas pelo administrador, rodando
  `backend/create_user.py` direto no servidor — não existe tela de "criar
  conta" nem endpoint público para isso. Decisão de produto já tomada.
- **Banco:** SQLite (`backend/facchini.db`), um arquivo por ambiente — não
  entra no controle de versão.
- **Sessão:** cookie assinado (`itsdangerous`, via `SessionMiddleware` do
  Starlette), válido por 8 horas. `/logout` encerra a sessão — é um link
  comum, funciona mesmo sem JavaScript.
- **Força bruta:** 5 tentativas erradas por usuário bloqueiam novas
  tentativas por 15 minutos (em memória — reinicia com o processo).
- **Páginas do portal** (`pages/portal-*.html`) são interceptadas pelo
  backend antes de serem entregues: sem sessão válida, o pedido vai para
  `pages/login.html`. Cada página nova do portal ganha a mesma rota de
  verificação em `backend/app.py` — ver comentário lá.

## pages/portal-inicio.html — painel do cliente após o login

Segue a mesma arquitetura de páginas isoladas: `css/portal-shell.css`
(sidebar, topo, cartões, tabela — a "casca" que toda página futura do
portal vai reaproveitar) e `css/portal-inicio.css` (só o que é desta
tela: banner, acesso rápido, novidades). `js/portal.js` cuida do menu
lateral no mobile e do menu do usuário; nenhum dos três arquivos é
carregado pelo `index.html` nem pelo `login.html`.

A tela usa `height: 100svh` com o conteúdo principal rolando por dentro
de si mesmo (não a página toda) — pensada para caber sem precisar rolar
em monitores Full HD (1920×1080) ou maiores. Em janelas mais baixas que
isso, o conteúdo ainda rola, mas só dentro da área principal — a sidebar
e o topo continuam sempre fixos.

## pages/login.html — tela de acesso do cliente

Interface pronta, sem autenticação real ainda. Fica isolada de propósito:

- `css/login.css` e `js/login.js` são exclusivos dessa página — nenhum dos dois
  é referenciado pelo `index.html`, nem o contrário. `login.css` só depende de
  `base.css` (tokens e o componente `.botao`, que é intencionalmente
  compartilhado). Isso significa que mexer no CSS/JS da lead page não pode
  quebrar o login, e vice-versa.
- O sprite de ícones do login é próprio (`i-usuario`, `i-cadeado`, `i-olho`),
  duplicado do padrão do `index.html` em vez de compartilhado — mesmo motivo.
- Não existe link de "criar conta": contas serão criadas pelo administrador,
  sem autoatendimento. Isso é uma decisão de produto já tomada; o *sistema*
  que cria essas contas ainda não existe.
- O formulário valida os campos e mostra "login ainda não conectado" no
  envio — não há backend. Quando houver, o bloco de `fetch` entra em
  `js/login.js` sem tocar no resto do arquivo (mostrar/ocultar senha e
  validação continuam do jeito que estão).
- `<meta name="robots" content="noindex, nofollow">` — página de login não
  deve aparecer em busca.

## Antes de publicar

Há dados de exemplo no site (telefone, e-mail, redes sociais, domínio) **e as
respostas da seção "Dúvidas" são um rascunho com promessas comerciais** que
precisam da confirmação da Facchini. A lista completa está em
[docs/DEPLOY.md](docs/DEPLOY.md).

## Como a página está montada

| Seção | O que faz |
|---|---|
| Hero | Título revelado por máscara + paralaxe da foto ligada ao scroll |
| Números | Barras douradas (o símbolo do logo) que se desenham, com contadores |
| Soluções | Bento grid: um bloco dominante e seis de apoio |
| Tecnologia | Abas horizontais: os 5 recursos em uma tela, exploráveis por clique |
| Segmentos | Faixa contínua que desliza sozinha e pausa no hover |
| Dúvidas | Acordeão de objeções, exclusivo, em HTML puro (`<details name>`) |
| Contato | Formulário de 3 campos + extras recolhidos |

Fora do fluxo: barra de progresso da leitura no topo e barra fixa de CTA que
aparece depois do hero e some ao chegar no formulário.

## Decisões que valem conhecer

**As escolhas de conversão vieram de dados, não de gosto.** CTA único (converte
~29% mais que páginas com vários), formulário no ponto ótimo de 3 campos, texto
em linguagem simples (converte cerca de 2x mais que texto corporativo) e uma
seção dedicada a tratar objeções — o item de maior impacto isolado.

**Movimento em CSS, não em JavaScript.** A paralaxe do hero e a barra de
progresso usam `animation-timeline`, que roda no compositor: nenhum listener de
scroll, nenhum custo de INP. O JS cuida só do que depende de estado. Onde o
navegador não suporta, as animações somem e o layout continua intacto.

**Interação é opcional, nunca obrigatória.** A seção de tecnologia usa abas
(padrão ARIA `tablist`, com setas, Home e End no teclado) em vez de prender a
rolagem: quem quiser explorar os cinco recursos clica, quem não quiser passa
direto. Sem JavaScript as abas somem e os cinco recursos viram uma lista.

**Tipografia do hero.** O Archivo é variável em dois eixos, peso e largura. O
título usa `font-stretch: 78%` com peso 900 — a letra condensada permite um
corpo bem maior dentro da mesma coluna, o que dá o peso de cartaz institucional
sem estourar o layout. O eixo de largura custa ~53 KB a mais no arquivo da fonte.

**Sem framework.** É uma página institucional: um framework acrescentaria peso de
build e superfície de dependências sem resolver nenhum problema que ela tenha.

**Fontes auto-hospedadas.** Nada é pedido ao Google Fonts em produção — o navegador
do visitante não conversa com servidores de terceiros. Isso evita o compartilhamento
de IP que a LGPD trata como dado pessoal, e corta um DNS + TLS do carregamento.

**CSP restritiva.** `default-src 'self'` sem `unsafe-inline`: não há script nem estilo
embutido no HTML, e nenhum handler `onclick`. Um script injetado por um invasor não
executa. Por isso o `js/deteccao.js` é um arquivo separado em vez de uma linha inline.

**Sem `innerHTML`.** Todo texto dinâmico é escrito com `textContent`, o que torna
impossível injetar HTML pelos campos do formulário.

**Imagens.** Os PNGs originais somavam 18 MB; em WebP com variantes responsivas
somam 1,2 MB — cerca de 93% a menos, sem diferença visível.

**Funciona sem JavaScript.** Conteúdo, layout e navegação por âncora não dependem de
JS. Sem ele, perdem-se apenas as animações, a máscara de telefone e o menu-gaveta.

**Acessibilidade.** Marcos semânticos, hierarquia de headings sem saltos, foco visível,
`prefers-reduced-motion`, todos os campos com label e contraste de 7:1 ou mais
(AA pede 4,5:1).
