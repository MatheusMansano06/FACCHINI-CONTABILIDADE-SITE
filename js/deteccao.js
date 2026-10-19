/* Marca que o JavaScript está ativo antes da primeira pintura.
   Sem isso, as animações de revelação deixariam o conteúdo invisível
   caso o JS falhe ou esteja desligado. Carregado de forma síncrona no <head>. */
document.documentElement.classList.add('js-ativo');
