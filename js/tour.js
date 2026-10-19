/* =============================================================
   Tour guiado do Henrique.
   Cada página declara <body data-tour="id" data-tour-area="cliente|equipe">
   e o roteiro fica em js/tour-roteiros.js (window.TOUR_ROTEIROS[id]).
   Primeira visita: abre sozinho. Depois: "Rever tour desta tela" no
   menu do usuário. O que já foi visto fica salvo no servidor por conta.
   Primeiro e último passo (sem alvo) = cena em tela cheia com o Henrique;
   os do meio = foco de luz no elemento + balão explicando.
   ============================================================= */
'use strict';

(() => {
  const id = document.body.dataset.tour;
  const area = document.body.dataset.tourArea === 'equipe' ? 'equipe' : 'cliente';
  const roteiro = (window.TOUR_ROTEIROS || {})[id];
  if (!id || !roteiro || roteiro.length < 2) return;

  const API = area === 'equipe' ? '/api/equipe/tours' : '/api/tours';
  const FOTO = '../assets/images/henrique-recorte.webp';
  const AVATAR = '../assets/images/henrique-avatar.webp';
  const NOME = 'Henrique · Facchini';
  const MOVIMENTO_REDUZIDO = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const MARGEM = 8;
  const LARGURA_BALAO = 380;
  const ALTURA_BALAO = 270;

  const el = (tag, classe, texto) => {
    const no = document.createElement(tag);
    if (classe) no.className = classe;
    if (texto != null) no.textContent = texto;
    return no;
  };

  const visivel = (alvo) => {
    if (!alvo) return false;
    const r = alvo.getBoundingClientRect();
    const estilo = getComputedStyle(alvo);
    // fora da tela na horizontal = escondido (ex.: menu lateral recolhido no celular);
    // abaixo da dobra não conta, o tour rola até ele
    const naHorizontal = r.right > 4 && r.left < window.innerWidth - 4;
    return r.width > 4 && r.height > 4 && naHorizontal && estilo.visibility !== 'hidden' && estilo.display !== 'none';
  };

  async function jaVisto() {
    try {
      const resposta = await fetch(API, { credentials: 'same-origin' });
      if (!resposta.ok) return true; // sem sessão ou erro: não abre sozinho
      const dados = await resposta.json();
      return (dados.vistos || []).includes(id);
    } catch {
      return true;
    }
  }

  function salvar(status) {
    fetch(`${API}/${encodeURIComponent(id)}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status }),
    }).catch(() => {});
  }

  /* ---------- digitação letra a letra ---------- */
  function digitar(alvo, texto, aoTerminar) {
    const paragrafos = texto.split('\n');
    alvo.replaceChildren();
    const ps = paragrafos.map(() => alvo.appendChild(el('p')));
    const cursor = el('span', 'tour-cursor');
    if (MOVIMENTO_REDUZIDO) {
      paragrafos.forEach((t, i) => { ps[i].textContent = t; });
      aoTerminar();
      return () => {};
    }
    let p = 0;
    let c = 0;
    let parado = false;
    const terminar = () => {
      if (parado) return;
      parado = true;
      clearInterval(timer);
      paragrafos.forEach((t, i) => { ps[i].textContent = t; });
      cursor.remove();
      aoTerminar();
    };
    const timer = setInterval(() => {
      if (p >= paragrafos.length) return terminar();
      c += 1;
      ps[p].textContent = paragrafos[p].slice(0, c);
      ps[p].appendChild(cursor);
      if (c >= paragrafos[p].length) { p += 1; c = 0; }
    }, 20);
    return terminar;
  }

  /* ---------- o tour ---------- */
  function abrir() {
    if (document.querySelector('.tour')) return;

    // passos do meio cujo elemento não existe ou está escondido (ex.: menu
    // lateral no celular, tabela vazia) são pulados em vez de apontar pro nada
    const passos = roteiro.filter((p, i) => i === 0 || i === roteiro.length - 1 || !p.alvo || visivel(document.querySelector(p.alvo)));
    const meio = passos.length - 2;

    const raiz = el('div', 'tour');
    raiz.setAttribute('role', 'dialog');
    raiz.setAttribute('aria-modal', 'true');
    raiz.setAttribute('aria-label', 'Tour guiado com o Henrique');

    // o resto da página fica inerte enquanto o tour está aberto
    const irmaos = [...document.body.children];
    irmaos.forEach((n) => n.setAttribute('inert', ''));
    const overflowAntes = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focoAntes = document.activeElement;
    document.body.appendChild(raiz);

    let i = 0;
    let pararDigitacao = () => {};
    let medir = () => {};

    const fechar = (status) => {
      pararDigitacao();
      window.removeEventListener('resize', reposicionar);
      raiz.remove();
      irmaos.forEach((n) => n.removeAttribute('inert'));
      document.body.style.overflow = overflowAntes;
      if (focoAntes && focoAntes.focus) focoAntes.focus();
      salvar(status);
    };
    const proximo = () => { if (i >= passos.length - 1) fechar('concluido'); else { i += 1; desenhar(); } };
    const anterior = () => { if (i > 0) { i -= 1; desenhar(); } };
    const reposicionar = () => medir();
    window.addEventListener('resize', reposicionar);

    raiz.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') fechar('pulado');
      if (e.key === 'ArrowRight' && raiz.querySelector('.tour-balao')) proximo();
      if (e.key === 'ArrowLeft' && raiz.querySelector('.tour-balao')) anterior();
    });

    function cena(passo, ultimo) {
      const cenaEl = el('div', 'tour-cena');
      cenaEl.dataset.falando = '';

      const palco = el('div', 'tour-cena__palco');
      palco.appendChild(el('span', 'tour-cena__halo'));
      const figura = el('figure', 'tour-cena__figura');
      const foto = el('img');
      foto.src = FOTO;
      foto.alt = 'Henrique, da Facchini Assessoria Contábil';
      foto.width = 600;
      foto.height = 750;
      figura.appendChild(foto);
      palco.appendChild(figura);
      if (ultimo && i > 0) palco.appendChild(el('span', 'tour-cena__festa', '🎉'));

      const corpo = el('div', 'tour-cena__corpo');
      const balao = el('div', 'tour-cena__balao');
      const textoLeitor = el('p', 'sr-apenas', `${passo.titulo}. ${passo.texto}`);
      textoLeitor.setAttribute('aria-live', 'polite');
      const texto = el('div', 'tour-cena__texto');
      texto.setAttribute('aria-hidden', 'true');
      balao.append(textoLeitor, texto);

      const acoes = el('div', 'tour-cena__acoes');
      acoes.setAttribute('inert', '');
      const botao = el('button', 'tour-botao tour-botao--grande', ultimo ? 'Concluir' : (meio > 0 ? 'Me mostra →' : 'Entendi'));
      botao.type = 'button';
      botao.addEventListener('click', proximo);
      acoes.appendChild(botao);
      if (!ultimo) {
        const pular = el('button', 'tour-link', 'Agora não, pular');
        pular.type = 'button';
        pular.addEventListener('click', () => fechar('pulado'));
        acoes.appendChild(pular);
      } else if (i > 0) {
        const voltar = el('button', 'tour-link', 'Voltar uma dica');
        voltar.type = 'button';
        voltar.addEventListener('click', anterior);
        acoes.appendChild(voltar);
      }
      corpo.append(balao, acoes);

      const sair = el('button', 'tour-sair', 'Sair do tour ✕');
      sair.type = 'button';
      sair.addEventListener('click', () => fechar('pulado'));

      cenaEl.append(palco, corpo, sair);

      // leve efeito 3D acompanhando o mouse
      if (!MOVIMENTO_REDUZIDO) {
        cenaEl.addEventListener('pointermove', (e) => {
          cenaEl.style.setProperty('--mx', ((e.clientX / window.innerWidth) - 0.5).toFixed(3));
          cenaEl.style.setProperty('--my', ((e.clientY / window.innerHeight) - 0.5).toFixed(3));
        });
      }

      const liberar = () => {
        delete cenaEl.dataset.falando;
        acoes.removeAttribute('inert');
        acoes.dataset.pronto = '';
        botao.focus();
      };
      pararDigitacao = digitar(texto, `${passo.titulo}\n${passo.texto}`, liberar);
      balao.addEventListener('click', () => pararDigitacao());
      raiz.replaceChildren(cenaEl);
      sair.focus();
    }

    function balaoDoPasso(passo) {
      const alvo = passo.alvo ? document.querySelector(passo.alvo) : null;
      const camada = el('div');
      const foco = el('div', alvo ? 'tour-foco' : 'tour-escuro');
      foco.setAttribute('aria-hidden', 'true');

      const balao = el('div', 'tour-balao');
      const cabeca = el('div', 'tour-balao__cabeca');
      const avatar = el('img', 'tour-balao__avatar');
      avatar.src = AVATAR;
      avatar.alt = '';
      avatar.width = 42;
      avatar.height = 42;
      cabeca.append(avatar, el('span', 'tour-nome', NOME), el('span', 'tour-contagem', `${i} de ${meio}`));
      const titulo = el('h2', null, passo.titulo);
      titulo.id = 'tour-titulo';
      const texto = el('p', null, passo.texto);
      texto.id = 'tour-texto';
      raiz.setAttribute('aria-labelledby', 'tour-titulo');
      raiz.setAttribute('aria-describedby', 'tour-texto');

      const pontos = el('div', 'tour-pontos');
      pontos.setAttribute('aria-hidden', 'true');
      for (let k = 1; k <= meio; k += 1) {
        const ponto = el('span');
        if (k === i) ponto.dataset.atual = '';
        if (k < i) ponto.dataset.feito = '';
        pontos.appendChild(ponto);
      }

      const acoes = el('div', 'tour-balao__acoes');
      const pular = el('button', 'tour-link', 'Pular tour');
      pular.type = 'button';
      pular.addEventListener('click', () => fechar('pulado'));
      acoes.append(pular, el('span', 'tour-espaco'));
      if (i > 0) {
        const voltar = el('button', 'tour-voltar', 'Voltar');
        voltar.type = 'button';
        voltar.addEventListener('click', anterior);
        acoes.appendChild(voltar);
      }
      const seguir = el('button', 'tour-botao', 'Entendi →');
      seguir.type = 'button';
      seguir.addEventListener('click', proximo);
      acoes.appendChild(seguir);

      balao.append(cabeca, titulo, texto, pontos, acoes);
      camada.append(foco, balao);
      raiz.replaceChildren(camada);

      if (alvo) {
        const alto = alvo.getBoundingClientRect().height > window.innerHeight * 0.55;
        alvo.scrollIntoView({ block: alto ? 'start' : 'center', behavior: 'instant' });
      }

      medir = () => {
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const largura = Math.min(LARGURA_BALAO, vw - 32);
        balao.style.width = `${largura}px`;
        balao.style.top = balao.style.bottom = balao.style.left = balao.style.right = '';
        if (!alvo) {
          balao.style.left = `${(vw - largura) / 2}px`;
          balao.style.top = `${Math.max(16, vh / 2 - ALTURA_BALAO / 2)}px`;
          return;
        }
        const r = alvo.getBoundingClientRect();
        const topo = Math.max(MARGEM, r.top - MARGEM);
        const base = Math.min(vh - MARGEM, r.bottom + MARGEM);
        const esq = Math.max(MARGEM, r.left - MARGEM);
        const dir = Math.min(vw - MARGEM, r.right + MARGEM);
        Object.assign(foco.style, { top: `${topo}px`, left: `${esq}px`, width: `${dir - esq}px`, height: `${base - topo}px` });

        const esquerda = Math.min(Math.max(16, esq + (dir - esq) / 2 - largura / 2), vw - largura - 16);
        if (vh - base >= ALTURA_BALAO + 14) {
          Object.assign(balao.style, { left: `${esquerda}px`, top: `${base + 14}px` });
        } else if (topo >= ALTURA_BALAO + 14) {
          Object.assign(balao.style, { left: `${esquerda}px`, bottom: `${vh - topo + 14}px` });
        } else {
          // o elemento ocupa a tela: balão flutua no canto, por cima
          Object.assign(balao.style, { right: '16px', bottom: '16px' });
        }
      };
      medir();
      requestAnimationFrame(medir);
      seguir.focus();
    }

    function desenhar() {
      pararDigitacao();
      pararDigitacao = () => {};
      const passo = passos[i];
      const ultimo = i === passos.length - 1;
      if (!passo.alvo && (i === 0 || ultimo)) cena(passo, ultimo);
      else balaoDoPasso(passo);
    }

    desenhar();
  }

  /* ---------- "Rever tour desta tela" no menu do usuário ---------- */
  function adicionarItemNoMenu() {
    const menu = document.querySelector('[data-dropdown-usuario]');
    if (!menu || menu.querySelector('[data-rever-tour]')) return;
    const item = el('a', 'tour-rever-item');
    item.href = '#';
    item.setAttribute('role', 'menuitem');
    item.dataset.reverTour = '';
    const foto = el('img');
    foto.src = AVATAR;
    foto.alt = '';
    foto.width = 22;
    foto.height = 22;
    item.append(foto, document.createTextNode(' Rever tour desta tela'));
    item.addEventListener('click', (e) => {
      e.preventDefault();
      menu.hidden = true;
      document.querySelector('[data-menu-usuario]')?.setAttribute('aria-expanded', 'false');
      abrir();
    });
    menu.prepend(item);
  }

  adicionarItemNoMenu();

  // espera a página terminar de carregar (imagens mudam posições) antes de medir
  const iniciar = async () => {
    if (await jaVisto()) return;
    // não atrapalha a troca obrigatória de senha, se ainda estiver na tela
    if (document.querySelector('[data-aviso-senha]:not([hidden])')) return;
    abrir();
  };
  if (document.readyState === 'complete') iniciar();
  else window.addEventListener('load', iniciar, { once: true });
})();
