/* =============================================================
   Facchini Assessoria Contábil — comportamento da landing page.
   Vanilla JS, sem dependências. Todo conteúdo dinâmico é escrito
   com textContent (nunca innerHTML) para eliminar risco de XSS.

   O movimento ligado ao scroll (paralaxe do hero e barra de progresso)
   é feito em CSS puro com animation-timeline — aqui ficam só os
   comportamentos que dependem de estado.
   ============================================================= */
'use strict';

const CONFIG = {
  /* Endpoint que recebe os leads: POST /api/contato em backend/app.py, no
     mesmo domínio da página (a CSP connect-src 'self' já permite). Se
     ficar vazio, o formulário volta a só validar e abrir o WhatsApp. */
  endpointFormulario: '/api/contato',

  whatsapp: '551933811008',
};

const reduzirMovimento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const temObservador = 'IntersectionObserver' in window;

/* ------------------------------------------------ menu mobile */
function iniciarMenu() {
  const menu = document.querySelector('[data-menu]');
  const abrir = document.querySelector('[data-menu-abrir]');
  const fechar = document.querySelector('[data-menu-fechar]');
  const fundo = document.querySelector('[data-menu-fundo]');
  if (!menu || !abrir || !fundo) return;

  const alternar = (aberto) => {
    menu.classList.toggle('esta-aberto', aberto);
    abrir.setAttribute('aria-expanded', String(aberto));
    fundo.hidden = !aberto;
    document.body.classList.toggle('corpo-travado', aberto);
    if (aberto) {
      menu.querySelector('a, button')?.focus();
    } else {
      abrir.focus();
    }
  };

  abrir.addEventListener('click', () => alternar(true));
  fechar?.addEventListener('click', () => alternar(false));
  fundo.addEventListener('click', () => alternar(false));

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && menu.classList.contains('esta-aberto')) alternar(false);
  });

  menu.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener('click', () => alternar(false));
  });

  window.matchMedia('(min-width: 1081px)').addEventListener('change', (e) => {
    if (e.matches && menu.classList.contains('esta-aberto')) alternar(false);
  });
}

/* ------------------------------------------- cabeçalho ao rolar */
function iniciarCabecalho() {
  const cabecalho = document.querySelector('[data-cabecalho]');
  if (!cabecalho) return;

  const atualizar = () => cabecalho.classList.toggle('esta-preso', window.scrollY > 24);
  atualizar();
  window.addEventListener('scroll', atualizar, { passive: true });
}

/* --------------------------------------- revelação ao entrar na tela */
function iniciarRevelacao() {
  const alvos = document.querySelectorAll('[data-revelar]');
  if (!alvos.length) return;

  if (reduzirMovimento || !temObservador) {
    alvos.forEach((el) => el.classList.add('visivel'));
    return;
  }

  const observador = new IntersectionObserver((entradas) => {
    entradas.forEach((entrada, indice) => {
      // Numa rolagem rápida (ou ao abrir direto numa âncora) o elemento pode
      // passar inteiro pela tela entre dois quadros e nunca ser reportado como
      // intersectando. Nesse caso ele já ficou para trás: revela na hora.
      const jaPassou = entrada.boundingClientRect.bottom < 0;
      if (!entrada.isIntersecting && !jaPassou) return;

      const atraso = entrada.isIntersecting ? indice * 70 : 0;
      setTimeout(() => entrada.target.classList.add('visivel'), atraso);
      observador.unobserve(entrada.target);
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.12 });

  alvos.forEach((el) => observador.observe(el));
}

/* ------------------------------------------ link ativo na navegação */
function iniciarNavegacaoAtiva() {
  const links = [...document.querySelectorAll('.navegacao__link[href^="#"]')];
  const secoes = links
    .map((link) => document.querySelector(link.getAttribute('href')))
    .filter(Boolean);
  if (!secoes.length || !temObservador) return;

  // Guardar quem está visível, em vez de reagir ao último evento recebido:
  // numa rolagem rápida os eventos chegam fora de ordem e o link ativo
  // ficava preso numa seção que já tinha passado.
  const visiveis = new Set();

  const observador = new IntersectionObserver((entradas) => {
    entradas.forEach((entrada) => {
      if (entrada.isIntersecting) visiveis.add(entrada.target);
      else visiveis.delete(entrada.target);
    });

    // Sem nenhuma seção na faixa central, mantém o destaque anterior
    if (!visiveis.size) return;

    const atual = secoes.find((s) => visiveis.has(s));
    links.forEach((link) => {
      link.classList.toggle('esta-ativo', link.getAttribute('href') === `#${atual.id}`);
    });
  }, { rootMargin: '-45% 0px -50% 0px' });

  secoes.forEach((secao) => observador.observe(secao));
}

/* ------------------------------------------------- contadores */
function iniciarContadores() {
  const alvos = document.querySelectorAll('[data-contador]');
  if (!alvos.length) return;

  const formatar = (n) => n.toLocaleString('pt-BR');

  const animar = (el) => {
    const destino = Number(el.dataset.contador);
    const prefixo = el.dataset.prefixo || '';
    if (!Number.isFinite(destino)) return;

    if (reduzirMovimento) {
      el.textContent = prefixo + formatar(destino);
      return;
    }

    const duracao = 1400;
    const inicio = performance.now();

    const passo = (agora) => {
      const progresso = Math.min((agora - inicio) / duracao, 1);
      const suave = 1 - Math.pow(1 - progresso, 3);
      el.textContent = prefixo + formatar(Math.round(destino * suave));
      if (progresso < 1) requestAnimationFrame(passo);
    };

    requestAnimationFrame(passo);
  };

  if (!temObservador) {
    alvos.forEach(animar);
    return;
  }

  const observador = new IntersectionObserver((entradas) => {
    entradas.forEach((entrada) => {
      if (!entrada.isIntersecting) return;
      animar(entrada.target);
      observador.unobserve(entrada.target);
    });
  }, { threshold: 0.6 });

  alvos.forEach((el) => observador.observe(el));
}

/* ------------------- abas dos recursos do app (padrão ARIA tablist) */
function iniciarAbas() {
  const bloco = document.querySelector('[data-abas]');
  if (!bloco) return;

  const abas = [...bloco.querySelectorAll('[role="tab"]')];
  const paineis = abas.map((aba) => document.getElementById(aba.getAttribute('aria-controls')));
  if (!abas.length || paineis.some((p) => !p)) return;

  const selecionar = (indice, moverFoco = true) => {
    abas.forEach((aba, i) => {
      const ativa = i === indice;
      aba.setAttribute('aria-selected', String(ativa));
      // Só a aba ativa fica no caminho do Tab; entre as abas navega-se por setas
      aba.tabIndex = ativa ? 0 : -1;
      paineis[i].hidden = !ativa;
    });
    if (moverFoco) abas[indice].focus();
  };

  abas.forEach((aba, i) => {
    aba.addEventListener('click', () => selecionar(i, false));

    aba.addEventListener('keydown', (e) => {
      const teclas = {
        ArrowRight: (i + 1) % abas.length,
        ArrowLeft: (i - 1 + abas.length) % abas.length,
        Home: 0,
        End: abas.length - 1,
      };
      if (!(e.key in teclas)) return;
      e.preventDefault();
      selecionar(teclas[e.key]);
    });
  });

  // Painéis só ganham papel de tabpanel agora: sem JS eles são texto comum
  paineis.forEach((painel) => {
    painel.tabIndex = 0;
  });

  selecionar(0, false);
}

/* --------------------------- faixa contínua de segmentos (marquee) */
function iniciarFaixa() {
  const faixa = document.querySelector('[data-faixa]');
  const copia = document.querySelector('[data-faixa-copia]');
  if (!faixa || !copia) return;

  const original = faixa.querySelector('.faixa__trilho');
  if (!original || original === copia) return;

  // Duplicar o conteúdo é o que faz o laço não ter emenda. A cópia já está
  // marcada como aria-hidden no HTML, então não duplica para leitores de tela.
  [...original.children].forEach((item) => copia.appendChild(item.cloneNode(true)));
  copia.querySelectorAll('img').forEach((img) => img.setAttribute('alt', ''));

  faixa.classList.add('faixa--pronta');

  // Animação infinita fora da tela é bateria gasta à toa: congela quando
  // a faixa não está visível e retoma quando volta.
  if (!temObservador) return;
  new IntersectionObserver(([entrada]) => {
    faixa.classList.toggle('faixa--parada', !entrada.isIntersecting);
  }, { threshold: 0 }).observe(faixa);
}

/* ----------------------------------- barra fixa de conversão */
function iniciarBarraCta() {
  const barra = document.querySelector('[data-barra-cta]');
  const hero = document.querySelector('#topo');
  const contato = document.querySelector('#contato');
  if (!barra || !hero || !contato || !temObservador) return;

  barra.hidden = false;

  // Só aparece no meio do caminho: depois do hero e antes do formulário,
  // que é justamente onde a pessoa está lendo e não tem um CTA à vista.
  const estado = { passouHero: false, chegouContato: false };

  const atualizar = () => {
    barra.classList.toggle('esta-visivel', estado.passouHero && !estado.chegouContato);
  };

  new IntersectionObserver(([e]) => {
    estado.passouHero = !e.isIntersecting;
    atualizar();
  }, { threshold: 0.15 }).observe(hero);

  new IntersectionObserver(([e]) => {
    estado.chegouContato = e.isIntersecting;
    atualizar();
  }, { threshold: 0.05 }).observe(contato);
}

/* ------------------------------------------- máscara de telefone */
function iniciarMascaras() {
  document.querySelectorAll('[data-mascara="telefone"]').forEach((campo) => {
    campo.addEventListener('input', () => {
      const digitos = campo.value.replace(/\D/g, '').slice(0, 11);
      let saida = digitos;

      if (digitos.length > 2) {
        const resto = digitos.slice(2);
        const corte = digitos.length > 10 ? 5 : 4;
        saida = `(${digitos.slice(0, 2)}) ${resto.slice(0, corte)}`;
        if (resto.length > corte) saida += `-${resto.slice(corte)}`;
      } else if (digitos.length > 0) {
        saida = `(${digitos}`;
      }

      campo.value = saida;
    });
  });
}

/* -------------------------------------------------- formulário */
const REGRAS = {
  nome: {
    valido: (v) => v.trim().length >= 2,
    erro: 'Informe o seu nome.',
  },
  email: {
    valido: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.trim()),
    erro: 'Informe um e-mail válido.',
  },
  telefone: {
    valido: (v) => {
      const d = v.replace(/\D/g, '');
      return d.length === 10 || d.length === 11;
    },
    erro: 'Informe um WhatsApp com DDD.',
  },
  consentimento: {
    valido: (_v, campo) => campo.checked,
    erro: 'É preciso autorizar o contato para enviar.',
  },
};

function marcarCampo(campo, erro) {
  const alvoErro = document.querySelector(`[data-erro-de="${campo.name}"]`);
  if (alvoErro) alvoErro.textContent = erro;
  campo.closest('.campo')?.classList.toggle('campo--invalido', Boolean(erro));
  campo.setAttribute('aria-invalid', String(Boolean(erro)));
}

function validarCampo(campo) {
  const regra = REGRAS[campo.name];
  if (!regra) return true;

  const ok = regra.valido(campo.value, campo);
  marcarCampo(campo, ok ? '' : regra.erro);
  return ok;
}

function iniciarFormulario() {
  const form = document.querySelector('[data-formulario]');
  if (!form) return;

  const retorno = form.querySelector('[data-retorno]');
  const botao = form.querySelector('[data-enviar]');
  const rotuloBotao = botao?.firstChild?.textContent?.trim() ?? 'Enviar';

  const responder = (texto, tipo) => {
    if (!retorno) return;
    retorno.textContent = texto;
    retorno.classList.toggle('esta-ok', tipo === 'ok');
    retorno.classList.toggle('esta-erro', tipo === 'erro');
  };

  const valorDe = (nome) => form.elements[nome]?.value.trim() ?? '';

  // Valida ao sair do campo; em tempo real só depois do primeiro erro
  Object.keys(REGRAS).forEach((nome) => {
    const campo = form.elements[nome];
    if (!campo) return;
    campo.addEventListener('blur', () => validarCampo(campo));
    campo.addEventListener('input', () => {
      if (campo.closest('.campo')?.classList.contains('campo--invalido')) validarCampo(campo);
    });
  });

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();

    // Armadilha anti-robô: se estiver preenchida, encerra sem avisar o bot
    if (form.elements.site?.value) return;

    const invalidos = Object.keys(REGRAS)
      .map((nome) => form.elements[nome])
      .filter((campo) => campo && !validarCampo(campo));

    if (invalidos.length) {
      responder('Revise os campos destacados para continuar.', 'erro');
      invalidos[0].focus();
      return;
    }

    const dados = {
      nome: valorDe('nome'),
      empresa: valorDe('empresa'),
      email: valorDe('email'),
      telefone: valorDe('telefone'),
      segmento: valorDe('segmento'),
      mensagem: valorDe('mensagem'),
      origem: window.location.pathname,
      consentimento: Boolean(form.elements.consentimento?.checked),
    };

    // Sem endpoint configurado, o WhatsApp é o caminho que realmente funciona hoje
    if (!CONFIG.endpointFormulario) {
      const texto = encodeURIComponent(
        `Olá! Sou ${dados.nome}${dados.empresa ? ` (${dados.empresa})` : ''}. ` +
        `${dados.mensagem || 'Gostaria de falar com um especialista.'}`
      );
      window.open(`https://wa.me/${CONFIG.whatsapp}?text=${texto}`, '_blank', 'noopener');
      responder('Abrimos o WhatsApp para você falar com a nossa equipe agora.', 'ok');
      return;
    }

    botao.disabled = true;
    if (botao.firstChild) botao.firstChild.textContent = 'Enviando… ';
    responder('', null);

    try {
      const resposta = await fetch(CONFIG.endpointFormulario, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(dados),
        signal: AbortSignal.timeout?.(15000),
      });
      const corpo = await resposta.json().catch(() => ({}));

      if (resposta.ok) {
        form.reset();
        responder(
          `Obrigado, ${dados.nome.split(' ')[0]}! Recebemos sua mensagem e um especialista ` +
          'retorna em até 1 dia útil.',
          'ok'
        );
        return;
      }

      // Erros de validação do servidor: destaca os mesmos campos que a
      // validação do navegador destacaria
      if (resposta.status === 400 && corpo.campos) {
        const campos = Object.entries(corpo.campos)
          .map(([nome, erro]) => {
            const campo = form.elements[nome];
            if (!campo) return null;
            marcarCampo(campo, String(erro));
            const extra = campo.closest('details');
            if (extra) extra.open = true;
            return campo;
          })
          .filter(Boolean);
        responder(corpo.erro || 'Revise os campos destacados para continuar.', 'erro');
        campos[0]?.focus();
        return;
      }

      if (resposta.status === 429) {
        responder(
          corpo.erro || 'Recebemos vários envios seguidos. Tente mais tarde ou chame no WhatsApp logo abaixo.',
          'erro'
        );
        return;
      }

      throw new Error(`HTTP ${resposta.status}`);
    } catch {
      responder(
        'Não foi possível enviar agora. Tente de novo em instantes ou chame no WhatsApp logo abaixo.',
        'erro'
      );
    } finally {
      botao.disabled = false;
      if (botao.firstChild) botao.firstChild.textContent = `${rotuloBotao} `;
    }
  });
}

/* ------------------------------------------------- ano do rodapé */
function iniciarAno() {
  const alvo = document.querySelector('[data-ano]');
  if (alvo) alvo.textContent = String(new Date().getFullYear());
}

/* ------------------------------------------------------ partida */
iniciarMenu();
iniciarCabecalho();
iniciarRevelacao();
iniciarNavegacaoAtiva();
iniciarContadores();
iniciarAbas();
iniciarFaixa();
iniciarBarraCta();
iniciarMascaras();
iniciarFormulario();
iniciarAno();
