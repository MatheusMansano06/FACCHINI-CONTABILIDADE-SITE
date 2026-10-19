/* =============================================================
   Painel da equipe — comportamento da casca (sidebar + topo +
   aviso de troca de senha). Cópia de portal.js com os endpoints
   trocados pra /api/equipe/* — arquivo próprio porque o painel da
   equipe é uma sessão totalmente separada do portal do cliente,
   nunca deve dividir código que dependa de qual delas está ativa.
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
      const resposta = await fetch('/api/equipe/trocar-senha', {
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
iniciarAvisoSenha();
