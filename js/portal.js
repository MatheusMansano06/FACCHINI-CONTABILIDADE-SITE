/* =============================================================
   Portal do cliente — comportamento da casca (sidebar + topo).
   Compartilhado por toda página do portal; não depende de main.js
   nem de login.js, e nenhum dos dois depende deste arquivo.
   Comportamento específico de uma página do portal (se algum dia
   precisar) deve morar num js próprio dela, como o padrão já
   estabelecido em login.js — não aqui.
   ============================================================= */
'use strict';

/* -------------------------------------------- sidebar no mobile */
function iniciarSidebar() {
  const sidebar = document.querySelector('[data-sidebar]');
  const abrir = document.querySelector('[data-abrir-sidebar]');
  const fundo = document.querySelector('[data-fundo-sidebar]');
  if (!sidebar || !abrir || !fundo) return;

  const alternar = (aberta) => {
    sidebar.classList.toggle('esta-aberta', aberta);
    abrir.setAttribute('aria-expanded', String(aberta));
    fundo.hidden = !aberta;
    document.body.classList.toggle('corpo-travado', aberta);
  };

  abrir.addEventListener('click', () => alternar(!sidebar.classList.contains('esta-aberta')));
  fundo.addEventListener('click', () => alternar(false));
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sidebar.classList.contains('esta-aberta')) alternar(false);
  });

  window.matchMedia('(min-width: 981px)').addEventListener('change', (e) => {
    if (e.matches) alternar(false);
  });
}

/* ------------------------------------- menu do usuário (topo) */
function iniciarMenuUsuario() {
  const botao = document.querySelector('[data-menu-usuario]');
  const dropdown = document.querySelector('[data-dropdown-usuario]');
  if (!botao || !dropdown) return;

  const alternar = (aberto) => {
    dropdown.hidden = !aberto;
    botao.setAttribute('aria-expanded', String(aberto));
  };

  botao.addEventListener('click', (e) => {
    e.stopPropagation();
    alternar(dropdown.hidden);
  });

  document.addEventListener('click', (e) => {
    if (!dropdown.hidden && !dropdown.contains(e.target)) alternar(false);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !dropdown.hidden) {
      alternar(false);
      botao.focus();
    }
  });
}

/* ----------------------------------------------------------- busca
   Digita -> GET /api/busca (o servidor procura só na empresa da
   sessão) -> lista de resultados montada com createElement/textContent.
   Setas navegam, Enter abre o primeiro, Esc fecha. */
const normalizarBusca = (texto) =>
  (texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();

function iniciarBusca() {
  const form = document.querySelector('[data-busca-portal]');
  const campo = form?.querySelector('input[type="search"]');
  if (!form || !campo) return;

  const painel = document.createElement('div');
  painel.className = 'busca-resultados';
  painel.id = 'busca-resultados';
  painel.hidden = true;
  const aviso = document.createElement('p');
  aviso.className = 'sr-apenas';
  aviso.setAttribute('aria-live', 'polite');
  form.append(painel, aviso);
  campo.setAttribute('aria-controls', painel.id);
  campo.setAttribute('aria-expanded', 'false');

  let espera = null;
  let controle = null;
  let ultimoTermo = '';

  const abrir = (aberto) => {
    painel.hidden = !aberto;
    campo.setAttribute('aria-expanded', String(aberto));
  };
  const links = () => Array.from(painel.querySelectorAll('a'));
  // Só caminhos nossos (as URLs vêm do servidor, mas não custa conferir).
  const urlSegura = (url) => /^portal-[a-z-]+\.html([?#].*)?$/.test(url || '');

  const item = (titulo, detalhe, url) => {
    const link = document.createElement('a');
    link.className = 'busca-resultados__item';
    link.href = url;
    const forte = document.createElement('strong');
    forte.textContent = titulo;
    link.append(forte);
    if (detalhe) {
      const pequeno = document.createElement('small');
      pequeno.textContent = detalhe;
      link.append(pequeno);
    }
    const li = document.createElement('li');
    li.append(link);
    return li;
  };

  const mostrar = (termo, grupos) => {
    painel.replaceChildren();
    let total = 0;
    grupos.forEach((grupo, i) => {
      const itens = (grupo.itens || []).filter((r) => urlSegura(r.url));
      if (!itens.length) return;
      total += grupo.total;
      const bloco = document.createElement('section');
      bloco.className = 'busca-resultados__grupo';
      const titulo = document.createElement('h2');
      titulo.className = 'busca-resultados__titulo';
      titulo.id = `busca-grupo-${i}`;
      titulo.textContent = grupo.titulo;
      bloco.setAttribute('aria-labelledby', titulo.id);
      const lista = document.createElement('ul');
      lista.className = 'busca-resultados__lista';
      itens.forEach((r) => lista.append(item(r.titulo, r.detalhe, r.url)));
      bloco.append(titulo, lista);
      if (grupo.total > itens.length && urlSegura(grupo.url)) {
        const mais = document.createElement('a');
        mais.className = 'busca-resultados__mais';
        mais.href = grupo.url;
        mais.textContent = `Ver todos (${grupo.total}) em ${grupo.titulo}`;
        bloco.append(mais);
      }
      painel.append(bloco);
    });
    if (!total) {
      const vazio = document.createElement('p');
      vazio.className = 'busca-resultados__vazio';
      vazio.textContent = `Nada encontrado para “${termo}”. Tente outra palavra, como o nome da guia ou o mês (ex.: 03/2026).`;
      painel.append(vazio);
    }
    aviso.textContent = total ? `${total} resultado${total > 1 ? 's' : ''} para ${termo}` : 'Nenhum resultado';
    abrir(true);
  };

  const buscar = async () => {
    const termo = campo.value.trim();
    if (normalizarBusca(termo).replace(/ /g, '').length < 2) {
      ultimoTermo = '';
      controle?.abort();
      abrir(false);
      return;
    }
    if (termo === ultimoTermo && !painel.hidden) return;
    ultimoTermo = termo;
    controle?.abort();
    controle = new AbortController();
    aviso.textContent = 'Buscando…';
    try {
      const resposta = await fetch(`/api/busca?q=${encodeURIComponent(termo)}`, {
        credentials: 'same-origin',
        signal: controle.signal,
      });
      if (resposta.status === 401) {
        window.location.href = 'login.html';
        return;
      }
      const dados = await resposta.json();
      if (!resposta.ok) throw new Error(dados.erro);
      if (campo.value.trim() === termo) mostrar(termo, dados.grupos || []);
    } catch (erro) {
      if (erro.name === 'AbortError') return;
      ultimoTermo = '';
      painel.replaceChildren();
      const falha = document.createElement('p');
      falha.className = 'busca-resultados__vazio';
      falha.textContent = 'Não foi possível buscar agora. Tente de novo em instantes.';
      painel.append(falha);
      aviso.textContent = falha.textContent;
      abrir(true);
    }
  };

  campo.addEventListener('input', () => {
    clearTimeout(espera);
    espera = setTimeout(buscar, 300);
  });
  campo.addEventListener('focus', () => {
    if (painel.childElementCount && campo.value.trim() === ultimoTermo) abrir(true);
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearTimeout(espera);
    await buscar();
    const primeiro = links()[0];
    if (primeiro) window.location.href = primeiro.href;
  });

  form.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !painel.hidden) {
      abrir(false);
      campo.focus();
      return;
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const todos = links();
    if (painel.hidden || !todos.length) return;
    e.preventDefault();
    const atual = todos.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') {
      todos[Math.min(atual + 1, todos.length - 1)].focus();
    } else if (atual <= 0) {
      campo.focus();
    } else {
      todos[atual - 1].focus();
    }
  });

  document.addEventListener('click', (e) => {
    if (!painel.hidden && !form.contains(e.target)) abrir(false);
  });
}

/* Chegou por um resultado da busca (?destaque=…): realça a(s) linha(s)
   da tabela que têm todos os termos e rola até a primeira. */
function destacarResultadoBusca() {
  const termos = new URLSearchParams(window.location.search).getAll('destaque').map(normalizarBusca).filter(Boolean);
  if (!termos.length) return;
  const linhas = Array.from(document.querySelectorAll('.portal__conteudo tbody tr')).filter((linha) => {
    const texto = normalizarBusca(linha.textContent);
    return termos.every((termo) => texto.includes(termo));
  });
  if (!linhas.length) return;
  linhas.forEach((linha) => linha.classList.add('linha-destacada'));
  const suave = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  linhas[0].scrollIntoView({ block: 'center', behavior: suave ? 'smooth' : 'auto' });
}

/* ---------------- campo "senha atual" (troca de senha fora do 1º acesso) ----------------
   Na troca obrigatória logo depois de entrar com a senha provisória o
   servidor não pede a senha atual (a pessoa acabou de digitá-la). Fora
   disso ele responde exigeSenhaAtual — e aí o campo aparece. Se a página
   já trouxer o campo no HTML (input name="senhaAtual", opcionalmente num
   bloco [data-bloco-senha-atual] com hidden), usa ele; senão cria aqui
   mesmo, sem innerHTML, com a mesma estrutura dos outros campos. */
function garantirCampoSenhaAtual(form) {
  const existente = form.elements.senhaAtual;
  if (existente) {
    const bloco = existente.closest('[data-bloco-senha-atual]');
    if (bloco) bloco.hidden = false;
    return existente;
  }

  const svgNS = 'http://www.w3.org/2000/svg';
  const campo = document.createElement('div');
  campo.className = 'campo';
  campo.setAttribute('data-bloco-senha-atual', '');

  const rotulo = document.createElement('label');
  rotulo.htmlFor = 'aviso-senha-atual';
  rotulo.textContent = 'Senha atual';

  const caixa = document.createElement('div');
  caixa.className = 'campo__caixa';
  const icone = document.createElementNS(svgNS, 'svg');
  icone.setAttribute('class', 'icone campo__icone');
  icone.setAttribute('aria-hidden', 'true');
  const uso = document.createElementNS(svgNS, 'use');
  uso.setAttribute('href', '#i-cadeado');
  icone.appendChild(uso);

  const entrada = document.createElement('input');
  entrada.type = 'password';
  entrada.id = 'aviso-senha-atual';
  entrada.name = 'senhaAtual';
  entrada.autocomplete = 'current-password';
  entrada.placeholder = 'Digite sua senha atual';
  entrada.required = true;

  caixa.append(icone, entrada);
  campo.append(rotulo, caixa);
  form.insertBefore(campo, form.querySelector('.campo'));
  return entrada;
}

/* ------------------------- aviso flutuante: trocar senha ------------------------- */
function iniciarAvisoSenha() {
  const aviso = document.querySelector('[data-aviso-senha]');
  if (!aviso) return; // servidor não renderizou => conta já trocou a senha

  const fechar = aviso.querySelector('[data-fechar-aviso-senha]');
  // Só esconde nesta visita — a conta continua marcada pra trocar, então
  // o aviso volta a aparecer no próximo login (decisão de produto).
  fechar?.addEventListener('click', () => { aviso.hidden = true; });

  const botaoAlternar = aviso.querySelector('[data-alternar-senha]');
  const campoSenha = aviso.querySelector('[data-campo-senha]');
  botaoAlternar?.addEventListener('click', () => {
    const oculta = campoSenha.type === 'password';
    campoSenha.type = oculta ? 'text' : 'password';
    botaoAlternar.setAttribute('aria-pressed', String(oculta));
    botaoAlternar.setAttribute('aria-label', oculta ? 'Ocultar senha' : 'Mostrar senha');
    botaoAlternar.querySelector('use').setAttribute('href', oculta ? '#i-olho' : '#i-olho-fechado');
  });

  const form = aviso.querySelector('[data-formulario-troca-senha]');
  const retorno = aviso.querySelector('[data-retorno-troca-senha]');
  const botaoSalvar = form.querySelector('button[type="submit"]');
  if (form.hasAttribute('data-exige-senha-atual')) garantirCampoSenhaAtual(form);

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();

    const novaSenha = form.elements.novaSenha.value;
    const confirmacao = form.elements.confirmacao.value;
    const campoAtual = form.elements.senhaAtual;
    const pedeSenhaAtual = Boolean(campoAtual && !campoAtual.closest('[hidden]'));
    const senhaAtual = pedeSenhaAtual ? campoAtual.value : '';

    if (pedeSenhaAtual && !senhaAtual) {
      retorno.textContent = 'Informe sua senha atual.';
      retorno.classList.add('esta-erro');
      campoAtual.focus();
      return;
    }
    if (novaSenha.length < 8) {
      retorno.textContent = 'Use uma senha com pelo menos 8 caracteres.';
      retorno.classList.add('esta-erro');
      return;
    }
    if (novaSenha !== confirmacao) {
      retorno.textContent = 'As senhas não coincidem.';
      retorno.classList.add('esta-erro');
      return;
    }

    retorno.classList.remove('esta-erro');
    retorno.textContent = 'Salvando…';
    botaoSalvar.disabled = true;

    try {
      const resposta = await fetch('/api/trocar-senha', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pedeSenhaAtual ? { senhaAtual, novaSenha, confirmacao } : { novaSenha, confirmacao }),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        aviso.hidden = true;
        return;
      }

      if (dados.exigeSenhaAtual) {
        const campo = garantirCampoSenhaAtual(form);
        if (pedeSenhaAtual) campo.value = '';
        campo.focus();
      }
      retorno.textContent = dados.erro || 'Não foi possível salvar. Tente de novo.';
      retorno.classList.add('esta-erro');
    } catch {
      retorno.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
      retorno.classList.add('esta-erro');
    } finally {
      botaoSalvar.disabled = false;
    }
  });
}

iniciarSidebar();
iniciarMenuUsuario();
iniciarBusca();
destacarResultadoBusca();
iniciarAvisoSenha();
