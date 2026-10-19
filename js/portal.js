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

/* ------------------------------------------------- busca (stub) */
function iniciarBusca() {
  const form = document.querySelector('[data-busca-portal]');
  if (!form) return;

  // Ainda não existe backend de busca — só evita recarregar a página
  // enquanto ele não existe. Ver docs/DEPLOY.md.
  form.addEventListener('submit', (e) => e.preventDefault());
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

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();

    const novaSenha = form.elements.novaSenha.value;
    const confirmacao = form.elements.confirmacao.value;

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
        body: JSON.stringify({ novaSenha, confirmacao }),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        aviso.hidden = true;
        return;
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
iniciarAvisoSenha();
