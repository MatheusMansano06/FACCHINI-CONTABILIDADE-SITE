/* =============================================================
   Painel da equipe — Comunicados: publicar e remover, exclusivo
   desta página. Endpoints: POST /api/equipe/comunicados e
   POST /api/equipe/comunicados/remover (backend/app.py). Toda a
   validação de verdade é no servidor; aqui é só conforto.
   ============================================================= */
'use strict';

async function enviarJson(url, corpo) {
  const resposta = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
  });
  const dados = await resposta.json().catch(() => ({}));
  return { ok: resposta.ok, dados };
}

function iniciarFormularioComunicado() {
  const form = document.querySelector('[data-formulario-comunicado]');
  if (!form) return;

  const retorno = form.querySelector('[data-retorno-comunicado]');
  const botaoEnviar = form.querySelector('button[type="submit"]');
  const campoEmpresa = form.querySelector('[data-campo-empresa]');
  const texto = form.querySelector('[data-texto-comunicado]');
  const contador = form.querySelector('[data-contador-texto]');

  const mostrarErro = (mensagem) => {
    retorno.textContent = mensagem;
    retorno.classList.add('esta-erro');
  };

  // Campo de CNPJ só aparece quando o destino é uma empresa específica.
  const atualizarDestino = () => {
    const especifica = form.elements.destino.value === 'empresa';
    campoEmpresa.hidden = !especifica;
    form.elements.empresa.required = especifica;
  };
  form.querySelectorAll('[data-destino]').forEach((radio) => radio.addEventListener('change', atualizarDestino));
  atualizarDestino();

  const atualizarContador = () => {
    contador.textContent = `${texto.value.length} / ${texto.maxLength}`;
  };
  texto.addEventListener('input', atualizarContador);
  atualizarContador();

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();

    const corpo = {
      titulo: form.elements.titulo.value.trim(),
      categoria: form.elements.categoria.value,
      texto: texto.value.trim(),
      destino: form.elements.destino.value,
      empresa: form.elements.empresa.value.trim(),
    };

    if (corpo.titulo.length < 3) return mostrarErro('Escreva um título (pelo menos 3 caracteres).');
    if (!corpo.texto) return mostrarErro('Escreva o texto do comunicado.');
    if (corpo.destino === 'empresa' && !corpo.empresa) return mostrarErro('Informe o CNPJ ou CPF da empresa.');

    retorno.classList.remove('esta-erro');
    retorno.textContent = 'Publicando…';
    botaoEnviar.disabled = true;

    try {
      const { ok, dados } = await enviarJson('/api/equipe/comunicados', corpo);
      if (ok) {
        retorno.textContent = 'Comunicado publicado! Atualizando a lista…';
        // Recarregar é mais simples (e mais seguro) que montar o item novo
        // à mão: a lista sai do servidor já escapada pelo Jinja.
        window.location.reload();
        return;
      }
      mostrarErro(dados.erro || 'Não foi possível publicar. Tente de novo.');
    } catch {
      mostrarErro('Falha de conexão. Verifique sua internet e tente de novo.');
    } finally {
      botaoEnviar.disabled = false;
    }
  });
}

function iniciarRemoverComunicado() {
  document.querySelectorAll('[data-remover-comunicado]').forEach((botao) => {
    botao.addEventListener('click', async () => {
      const item = botao.closest('.comunicado');
      const titulo = item?.querySelector('.comunicado__titulo')?.textContent || 'este comunicado';
      if (!window.confirm(`Remover "${titulo}" do portal? Os clientes deixam de ver na hora.`)) return;

      botao.disabled = true;
      try {
        const { ok, dados } = await enviarJson('/api/equipe/comunicados/remover', {
          id: Number(botao.dataset.removerComunicado),
        });
        if (ok) {
          item?.remove();
          return;
        }
        window.alert(dados.erro || 'Não foi possível remover. Tente de novo.');
      } catch {
        window.alert('Falha de conexão. Verifique sua internet e tente de novo.');
      } finally {
        botao.disabled = false;
      }
    });
  });
}

iniciarFormularioComunicado();
iniciarRemoverComunicado();
