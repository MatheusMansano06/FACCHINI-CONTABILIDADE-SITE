/* =============================================================
   Central de Atendimento — exclusivo desta página:
   1. filtros (status recarrega a página com ?status=, prioridade
      filtra só a página atual no navegador);
   2. detalhe de cada solicitação (histórico) com formulário pra
      comentar, mudar status, finalizar ou reabrir.
   Tudo montado com DOM/textContent — nada de innerHTML (CSP estrita
   e o texto vem de clientes, então nunca é tratado como HTML).
   ============================================================= */
'use strict';

const CLASSES_STATUS = ['andamento', 'respondido', 'concluido', 'atrasada'];

function iniciarFiltrosAtendimento() {
  const formulario = document.querySelector('[data-formulario-filtro]');
  const filtroStatus = document.querySelector('[data-filtro-status]');
  const filtroPrioridade = document.querySelector('[data-filtro-prioridade]');
  const botaoFiltrar = document.querySelector('[data-botao-filtrar]');
  const tabela = document.querySelector('[data-tabela-atendimentos]');
  const vazio = document.querySelector('[data-atendimentos-vazio]');

  // Com JS, trocar o status já recarrega — o botão "Filtrar" é só o
  // caminho de quem está sem JavaScript.
  if (formulario && filtroStatus) {
    if (botaoFiltrar) botaoFiltrar.hidden = true;
    filtroStatus.addEventListener('change', () => formulario.submit());
  }

  if (!tabela || !filtroPrioridade) return;
  const linhas = Array.from(tabela.querySelectorAll('tr[data-solicitacao]'));
  if (!linhas.length) return; // tabela já mostra "nenhuma solicitação", nada a filtrar

  filtroPrioridade.hidden = false;
  filtroPrioridade.addEventListener('change', () => {
    const prioridade = filtroPrioridade.value;
    let algumaVisivel = false;

    linhas.forEach((linha) => {
      const mostrar = !prioridade || linha.dataset.prioridade === prioridade;
      linha.hidden = !mostrar;
      const detalhe = linha.nextElementSibling;
      if (detalhe && detalhe.matches('[data-detalhe]')) {
        detalhe.hidden = !mostrar || !linha.classList.contains('esta-aberta');
      }
      if (mostrar) algumaVisivel = true;
    });

    tabela.closest('table').hidden = !algumaVisivel;
    if (vazio) vazio.hidden = algumaVisivel;
  });
}

/* ----------------------------- detalhe ----------------------------- */

function criarElemento(tag, classe, texto) {
  const elemento = document.createElement(tag);
  if (classe) elemento.className = classe;
  if (texto) elemento.textContent = texto;
  return elemento;
}

function desenharHistorico(lista, interacoes) {
  lista.replaceChildren();
  if (!interacoes.length) {
    lista.append(criarElemento('li', 'atendimento-historico__vazio', 'Nenhuma interação registrada.'));
    return;
  }

  interacoes.forEach((interacao) => {
    const item = criarElemento('li', 'atendimento-historico__item');
    if (interacao.privado) item.classList.add('atendimento-historico__item--privado');

    const meta = criarElemento('p', 'atendimento-historico__meta');
    meta.append(criarElemento('strong', '', interacao.autor || '—'));
    meta.append(criarElemento('span', '', interacao.data || ''));
    if (interacao.privado) meta.append(criarElemento('span', '', 'Interno'));
    item.append(meta);

    if (interacao.texto) item.append(criarElemento('p', 'atendimento-historico__texto', interacao.texto));

    if (interacao.anexos && interacao.anexos.length) {
      const anexos = criarElemento('p', 'atendimento-historico__anexos');
      interacao.anexos.forEach((anexo) => {
        // O servidor só repassa URLs https:// — confere de novo aqui.
        if (!/^https:\/\//.test(anexo.url)) return;
        const link = criarElemento('a', '', anexo.nome || 'Anexo');
        link.href = anexo.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        anexos.append(link);
      });
      item.append(anexos);
    }
    lista.append(item);
  });
  // Mais recente fica embaixo (ordem de conversa) — já rola até ela.
  lista.scrollTop = lista.scrollHeight;
}

function atualizarLinhaPrincipal(linha, solicitacao) {
  const classe = CLASSES_STATUS.includes(solicitacao.classe_status) ? solicitacao.classe_status : 'andamento';
  const etiqueta = linha.querySelector('[data-etiqueta-status]');
  if (etiqueta) {
    etiqueta.textContent = solicitacao.status;
    etiqueta.className = `etiqueta-status etiqueta-status--${classe}`;
  }
  linha.dataset.status = classe;
}

function preencherDetalhe(detalhe, solicitacao) {
  detalhe.querySelectorAll('[data-campo]').forEach((campo) => {
    const valor = solicitacao[campo.dataset.campo];
    campo.textContent = valor ? String(valor) : '—';
  });
  desenharHistorico(detalhe.querySelector('[data-historico]'), solicitacao.interacoes || []);

  const form = detalhe.querySelector('[data-formulario-resposta]');
  const select = form.elements.status;
  const opcaoCliente = form.querySelector('[data-opcao-cliente]');
  const opcaoFinalizar = form.querySelector('[data-opcao-finalizar]');

  // Regras da própria Acessórias: solicitação interna não aceita status
  // "Cliente" e todo comentário nela já é interno; finalizada só sai
  // desse estado reabrindo (Resolvendo/Cliente).
  opcaoCliente.disabled = solicitacao.interna;
  opcaoFinalizar.disabled = solicitacao.finalizada;
  if (select.selectedOptions[0]?.disabled) select.value = 'R';
  form.querySelector('[data-campo-privado]').hidden = solicitacao.interna;
  form.querySelector('[data-aviso-reabrir]').hidden = !solicitacao.finalizada;
}

async function carregarDetalhe(detalhe, solId) {
  const estado = detalhe.querySelector('[data-detalhe-estado]');
  const conteudo = detalhe.querySelector('[data-detalhe-conteudo]');
  estado.classList.remove('esta-erro');
  estado.textContent = 'Carregando histórico…';

  try {
    const resposta = await fetch(`/api/equipe/solicitacoes/${encodeURIComponent(solId)}`, {
      headers: { Accept: 'application/json' },
    });
    const dados = await resposta.json().catch(() => ({}));
    if (resposta.status === 401) {
      window.location.href = '/pages/equipe-login.html';
      return;
    }
    if (!resposta.ok || !dados.solicitacao) {
      estado.textContent = dados.erro || 'Não foi possível carregar a solicitação. Tente de novo.';
      estado.classList.add('esta-erro');
      return;
    }
    preencherDetalhe(detalhe, dados.solicitacao);
    estado.textContent = '';
    conteudo.hidden = false;
  } catch {
    estado.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
    estado.classList.add('esta-erro');
  }
}

function ligarFormulario(detalhe, linha, solId) {
  const form = detalhe.querySelector('[data-formulario-resposta]');
  const retorno = form.querySelector('[data-retorno-resposta]');
  const botao = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    retorno.classList.remove('esta-erro');

    const comentario = form.elements.comentario.value.trim();
    if (!comentario) {
      retorno.textContent = 'Escreva um comentário — a Acessórias exige um a cada atualização.';
      retorno.classList.add('esta-erro');
      form.elements.comentario.focus();
      return;
    }

    retorno.textContent = 'Enviando…';
    botao.disabled = true;
    try {
      const resposta = await fetch(`/api/equipe/solicitacoes/${encodeURIComponent(solId)}/atualizar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          comentario,
          status: form.elements.status.value,
          prazo: form.elements.prazo.value,
          privado: form.elements.privado.checked,
        }),
      });
      const dados = await resposta.json().catch(() => ({}));

      if (resposta.status === 401) {
        window.location.href = '/pages/equipe-login.html';
        return;
      }
      if (!resposta.ok) {
        retorno.textContent = dados.erro || 'Não foi possível atualizar. Tente de novo.';
        retorno.classList.add('esta-erro');
        return;
      }

      form.reset();
      if (dados.solicitacao) {
        preencherDetalhe(detalhe, dados.solicitacao);
        atualizarLinhaPrincipal(linha, dados.solicitacao);
      }
      retorno.textContent = 'Atualização enviada para a Acessórias.';
    } catch {
      retorno.textContent = 'Falha de conexão. Verifique sua internet e tente de novo.';
      retorno.classList.add('esta-erro');
    } finally {
      botao.disabled = false;
    }
  });
}

function criarDetalhe(modelo, linha, solId) {
  const detalhe = modelo.content.firstElementChild.cloneNode(true);

  // ids únicos por solicitação, pra cada <label> apontar pro seu campo.
  detalhe.querySelectorAll('[data-rotulo]').forEach((rotulo) => {
    const nome = rotulo.dataset.rotulo;
    const id = `resposta-${nome}-${solId}`;
    detalhe.querySelector(`[name="${nome}"]`).id = id;
    rotulo.htmlFor = id;
  });
  detalhe.id = `detalhe-${solId}`;

  ligarFormulario(detalhe, linha, solId);
  linha.after(detalhe);
  return detalhe;
}

function iniciarDetalhes() {
  const modelo = document.querySelector('[data-modelo-detalhe]');
  const tabela = document.querySelector('[data-tabela-atendimentos]');
  if (!modelo || !tabela) return;

  tabela.querySelectorAll('tr[data-solicitacao]').forEach((linha) => {
    const solId = linha.dataset.solicitacao;
    const botao = linha.querySelector('[data-abrir-detalhe]');
    if (!botao || !/^\d+$/.test(solId)) return;

    botao.hidden = false;
    botao.setAttribute('aria-controls', `detalhe-${solId}`);
    let detalhe = null;

    botao.addEventListener('click', () => {
      const abrir = botao.getAttribute('aria-expanded') !== 'true';
      botao.setAttribute('aria-expanded', String(abrir));
      botao.textContent = abrir ? 'Fechar' : 'Abrir';
      linha.classList.toggle('esta-aberta', abrir);

      if (!abrir) {
        if (detalhe) detalhe.hidden = true;
        return;
      }
      if (!detalhe) {
        detalhe = criarDetalhe(modelo, linha, solId);
        carregarDetalhe(detalhe, solId);
      }
      detalhe.hidden = false;
    });
  });
}

iniciarFiltrosAtendimento();
iniciarDetalhes();
