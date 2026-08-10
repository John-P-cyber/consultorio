(() => {
    const API_ORIGIN = window.location.origin;
    const METODOS_SEGUROS = new Set(['GET', 'HEAD', 'OPTIONS']);
    const ROTAS_SEM_RENOVACAO = [
        '/auth/login', '/auth/refresh', '/auth/mfa/', '/auth/registrar',
        '/auth/solicitar-recuperacao', '/auth/redefinir-senha'
    ];
    const fetchBase = window.fetch.bind(window);
    let renovacaoEmCurso = null;

    // Remove credenciais deixadas por versões anteriores. O código da clínica
    // não é uma credencial e pode continuar salvo apenas como conveniência.
    localStorage.removeItem('token');
    localStorage.removeItem('role');
    localStorage.removeItem('clinica_nome');

    const lerCookie = nome => document.cookie
        .split('; ')
        .find(item => item.startsWith(`${nome}=`))
        ?.split('=')
        .slice(1)
        .join('=');

    const cookieCsrf = () => decodeURIComponent(
        lerCookie('__Host-clinica_csrf') || lerCookie('clinica_csrf') || ''
    );

    const urlAbsoluta = input => {
        const valor = typeof input === 'string' ? input : input.url;
        return new URL(valor, window.location.href);
    };

    const preparar = (input, init = {}) => {
        const url = urlAbsoluta(input);
        if (url.origin !== API_ORIGIN) return init;
        const metodo = String(init.method || (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
        const headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : undefined) || {});
        if (!METODOS_SEGUROS.has(metodo)) {
            const csrf = cookieCsrf();
            if (csrf) headers.set('X-CSRF-Token', csrf);
        }
        return {...init, headers, credentials: 'same-origin'};
    };

    const podeRenovar = url => !ROTAS_SEM_RENOVACAO.some(rota => url.pathname.startsWith(rota));

    const renovar = async () => {
        if (!renovacaoEmCurso) {
            renovacaoEmCurso = fetchBase(`${API_ORIGIN}/auth/refresh`, preparar('/auth/refresh', {method: 'POST'}))
                .then(resposta => resposta.ok)
                .catch(() => false)
                .finally(() => { renovacaoEmCurso = null; });
        }
        return renovacaoEmCurso;
    };

    window.fetch = async (input, init = {}) => {
        const url = urlAbsoluta(input);
        const resposta = await fetchBase(input, preparar(input, init));
        if (url.origin !== API_ORIGIN || resposta.status !== 401 || !podeRenovar(url) || init.__semRetry) {
            return resposta;
        }
        if (await renovar()) {
            return fetchBase(input, preparar(input, {...init, __semRetry: true}));
        }
        if (!['/login.html', '/recuperar-senha.html'].includes(window.location.pathname)) {
            window.location.replace('login.html');
        }
        return resposta;
    };

    window.escapeHTML = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
    })[char]);

    window.mensagemErroAPI = dados => {
        if (!dados) return 'Ocorreu um erro inesperado.';
        if (typeof dados.detail === 'string') return dados.detail;
        if (Array.isArray(dados.detail)) return dados.detail.map(item => item.msg || 'Dado inválido').join(' ');
        return dados.mensagem || 'Ocorreu um erro inesperado.';
    };

    const aviso = (message, kind = 'error') => {
        document.querySelector('.app-toast')?.remove();
        const toast = document.createElement('div');
        toast.className = 'app-toast';
        toast.dataset.kind = kind;
        toast.setAttribute('role', 'status');
        toast.textContent = String(message);
        document.body.appendChild(toast);
        window.setTimeout(() => toast.remove(), 4200);
    };

    window.alert = message => aviso(
        message,
        /sucesso|cadastrado|marcada|gravado|salvo|enviada|confirmada|encerrada/i.test(String(message)) ? 'success' : 'error'
    );
    window.mostrarSucesso = message => aviso(message, 'success');

    window.obterSessao = async () => {
        const resposta = await window.fetch(`${API_ORIGIN}/auth/me`);
        if (!resposta.ok) return null;
        return resposta.json();
    };

    window.exigirSessao = async roleEsperada => {
        const sessao = await window.obterSessao();
        if (!sessao || (roleEsperada && sessao.role !== roleEsperada)) {
            window.location.replace('login.html');
            return null;
        }
        return sessao;
    };

    window.encerrarSessao = async () => {
        try {
            await window.fetch(`${API_ORIGIN}/auth/logout`, {method: 'POST'});
        } finally {
            localStorage.removeItem('token');
            localStorage.removeItem('role');
            localStorage.removeItem('clinica_nome');
            window.location.replace('login.html');
        }
    };

    const criarElemento = (tag, classe, texto) => {
        const elemento = document.createElement(tag);
        if (classe) elemento.className = classe;
        if (texto !== undefined) elemento.textContent = String(texto);
        return elemento;
    };

    const formatarDataHora = valor => {
        const data = new Date(valor);
        return Number.isNaN(data.getTime()) ? '' : data.toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    };

    const renderizarGraficoBarras = artefato => {
        const rotulos = Array.isArray(artefato.rotulos) ? artefato.rotulos.map(String) : [];
        const valores = Array.isArray(artefato.valores) ? artefato.valores.map(item => Math.max(0, Number(item) || 0)) : [];
        const total = Math.min(rotulos.length, valores.length, 12);
        if (!total) return null;
        const card = criarElemento('section', 'botia-artifact botia-chart');
        card.setAttribute('aria-label', artefato.descricao || artefato.titulo || 'Gráfico de barras');
        card.appendChild(criarElemento('h4', 'botia-artifact-title', artefato.titulo || 'Resumo'));
        const maximo = Math.max(...valores.slice(0, total), 1);
        const lista = criarElemento('div', 'botia-bars');
        for (let indice = 0; indice < total; indice += 1) {
            const linha = criarElemento('div', 'botia-bar-row');
            linha.appendChild(criarElemento('span', 'botia-bar-label', rotulos[indice]));
            const trilho = criarElemento('span', 'botia-bar-track');
            const barra = criarElemento('span', 'botia-bar-fill');
            barra.style.width = `${Math.max(3, (valores[indice] / maximo) * 100)}%`;
            trilho.appendChild(barra);
            linha.appendChild(trilho);
            linha.appendChild(criarElemento('strong', 'botia-bar-value', valores[indice]));
            lista.appendChild(linha);
        }
        card.appendChild(lista);
        if (artefato.descricao) card.appendChild(criarElemento('p', 'botia-artifact-note', artefato.descricao));
        return card;
    };

    const renderizarCartao = artefato => {
        const itens = Array.isArray(artefato.itens) ? artefato.itens : [];
        if (!itens.length) return null;
        const card = criarElemento('section', 'botia-artifact botia-confirmation');
        card.appendChild(criarElemento('h4', 'botia-artifact-title', artefato.titulo || 'Confirmação'));
        const lista = criarElemento('dl', 'botia-details');
        itens.slice(0, 8).forEach(item => {
            const grupo = criarElemento('div', 'botia-detail');
            grupo.appendChild(criarElemento('dt', '', item.rotulo || 'Informação'));
            grupo.appendChild(criarElemento('dd', '', item.valor ?? ''));
            lista.appendChild(grupo);
        });
        card.appendChild(lista);
        return card;
    };

    const iniciarBotIA = async () => {
        if (window.location.pathname.endsWith('/login.html')) return;
        let statusAssistente;
        try {
            const resposta = await fetchBase(`${API_ORIGIN}/assistente/status`, preparar('/assistente/status'));
            if (!resposta.ok) return;
            statusAssistente = await resposta.json();
        } catch (_) {
            return;
        }

        const raiz = criarElemento('aside', 'botia-widget');
        raiz.setAttribute('aria-label', 'Assistente virtual da clínica');
        const alternar = criarElemento('button', 'botia-toggle');
        alternar.type = 'button';
        alternar.setAttribute('aria-label', 'Abrir o BotIA');
        alternar.setAttribute('aria-expanded', 'false');
        alternar.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5.75A3.75 3.75 0 0 1 8.75 2h6.5A3.75 3.75 0 0 1 19 5.75v7.5A3.75 3.75 0 0 1 15.25 17H10l-4.85 3.64A1 1 0 0 1 3.55 19.8L4.02 16A3.74 3.74 0 0 1 5 13.25v-7.5Z"/><circle cx="8.5" cy="9.5" r="1"/><circle cx="12" cy="9.5" r="1"/><circle cx="15.5" cy="9.5" r="1"/></svg><span>BotIA</span>';

        const painel = criarElemento('section', 'botia-panel');
        painel.hidden = true;
        painel.setAttribute('role', 'dialog');
        painel.setAttribute('aria-label', 'Conversa com o BotIA');
        const cabecalho = criarElemento('header', 'botia-header');
        const identidade = criarElemento('div', 'botia-identity');
        const avatar = criarElemento('span', 'botia-avatar', 'IA');
        const titulo = criarElemento('div');
        titulo.appendChild(criarElemento('strong', '', 'BotIA'));
        titulo.appendChild(criarElemento('span', '', 'Assistente seguro da clínica'));
        identidade.append(avatar, titulo);
        const acoes = criarElemento('div', 'botia-header-actions');
        const nova = criarElemento('button', '', '+');
        nova.type = 'button';
        nova.title = 'Iniciar nova conversa';
        nova.setAttribute('aria-label', 'Iniciar nova conversa');
        const fechar = criarElemento('button', '', '×');
        fechar.type = 'button';
        fechar.title = 'Fechar';
        fechar.setAttribute('aria-label', 'Fechar o BotIA');
        acoes.append(nova, fechar);
        cabecalho.append(identidade, acoes);

        const avisoPrivacidade = criarElemento('p', 'botia-privacy', 'Respostas limitadas ao seu perfil e aos dados da sua clínica. Não envie senhas.');
        const mensagens = criarElemento('div', 'botia-messages');
        mensagens.setAttribute('role', 'log');
        mensagens.setAttribute('aria-live', 'polite');
        const rodape = criarElemento('form', 'botia-composer');
        const entrada = document.createElement('textarea');
        entrada.rows = 1;
        entrada.maxLength = 2000;
        entrada.placeholder = 'Como posso ajudar?';
        entrada.setAttribute('aria-label', 'Mensagem para o BotIA');
        const enviar = criarElemento('button', 'botia-send');
        enviar.type = 'submit';
        enviar.setAttribute('aria-label', 'Enviar mensagem');
        enviar.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3.4 20.4 17.45-7.48a1 1 0 0 0 0-1.84L3.4 3.6a1 1 0 0 0-1.35 1.16L3.8 11H12a1 1 0 1 1 0 2H3.8l-1.75 6.24A1 1 0 0 0 3.4 20.4Z"/></svg>';
        rodape.append(entrada, enviar);
        painel.append(cabecalho, avisoPrivacidade, mensagens, rodape);
        raiz.append(painel, alternar);
        document.body.appendChild(raiz);

        let conversaId = null;
        let carregada = false;
        let enviando = false;

        const rolarAteFim = () => { mensagens.scrollTop = mensagens.scrollHeight; };
        const limparMensagens = () => { mensagens.replaceChildren(); };
        const adicionarMensagem = (papel, conteudo, artefatos = [], horario = null) => {
            const item = criarElemento('article', `botia-message botia-message-${papel}`);
            item.appendChild(criarElemento('div', 'botia-bubble', conteudo));
            (Array.isArray(artefatos) ? artefatos : []).forEach(artefato => {
                const visual = artefato?.tipo === 'grafico_barras'
                    ? renderizarGraficoBarras(artefato)
                    : artefato?.tipo === 'agendamento' ? renderizarCartao(artefato) : null;
                if (visual) item.appendChild(visual);
            });
            if (horario) item.appendChild(criarElemento('time', 'botia-time', formatarDataHora(horario)));
            mensagens.appendChild(item);
            rolarAteFim();
            return item;
        };
        const mostrarBoasVindas = () => {
            limparMensagens();
            const textos = {
                paciente: 'Olá! Posso mostrar médicos e horários, consultar suas próximas consultas e ajudar a agendar.',
                medico: 'Olá! Posso consultar sua agenda e gerar gráficos dos seus próprios atendimentos.',
                admin: 'Olá! Posso explicar o portal e apresentar um resumo operacional da sua clínica.'
            };
            adicionarMensagem('assistant', statusAssistente.disponivel
                ? (textos[statusAssistente.role] || 'Olá! Como posso ajudar com o portal?')
                : 'O assistente foi desativado pelo administrador da plataforma.');
        };
        const carregarConversa = async () => {
            if (carregada) return;
            carregada = true;
            mostrarBoasVindas();
            if (!statusAssistente.disponivel) return;
            try {
                const resposta = await window.fetch(`${API_ORIGIN}/assistente/conversas/atual`);
                if (!resposta.ok) return;
                const conversa = await resposta.json();
                if (!conversa?.id) return;
                conversaId = conversa.id;
                limparMensagens();
                conversa.mensagens.forEach(item => adicionarMensagem(item.papel, item.conteudo, item.artefatos, item.criado_em));
            } catch (_) {
                adicionarMensagem('assistant', 'Não foi possível recuperar a conversa anterior agora.');
            }
        };
        const definirAberto = aberto => {
            painel.hidden = !aberto;
            alternar.setAttribute('aria-expanded', String(aberto));
            alternar.setAttribute('aria-label', aberto ? 'Fechar o BotIA' : 'Abrir o BotIA');
            if (aberto) {
                carregarConversa();
                window.setTimeout(() => entrada.focus(), 50);
            }
        };
        alternar.addEventListener('click', () => definirAberto(painel.hidden));
        fechar.addEventListener('click', () => definirAberto(false));
        nova.addEventListener('click', async () => {
            if (enviando) return;
            if (conversaId) {
                try { await window.fetch(`${API_ORIGIN}/assistente/conversas/${conversaId}`, {method: 'DELETE'}); } catch (_) { /* nova conversa local */ }
            }
            conversaId = null;
            mostrarBoasVindas();
            entrada.focus();
        });
        entrada.addEventListener('keydown', evento => {
            if (evento.key === 'Enter' && !evento.shiftKey) {
                evento.preventDefault();
                rodape.requestSubmit();
            }
        });
        rodape.addEventListener('submit', async evento => {
            evento.preventDefault();
            const texto = entrada.value.trim();
            if (!texto || enviando) return;
            if (!statusAssistente.disponivel) {
                adicionarMensagem('assistant', 'O serviço ainda não está configurado. Informe o administrador da plataforma.');
                return;
            }
            enviando = true;
            entrada.value = '';
            entrada.disabled = true;
            enviar.disabled = true;
            adicionarMensagem('user', texto);
            const espera = adicionarMensagem('assistant', 'Analisando com segurança…');
            espera.classList.add('botia-loading');
            try {
                const resposta = await window.fetch(`${API_ORIGIN}/assistente/mensagens`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({conversa_id: conversaId, mensagem: texto, pagina: window.location.pathname.split('/').pop() || 'index.html'})
                });
                const dados = await resposta.json().catch(() => ({}));
                espera.remove();
                if (!resposta.ok) {
                    adicionarMensagem('assistant', window.mensagemErroAPI(dados));
                } else {
                    conversaId = dados.conversa_id;
                    adicionarMensagem('assistant', dados.mensagem.conteudo, dados.mensagem.artefatos, dados.mensagem.criado_em);
                }
            } catch (_) {
                espera.remove();
                adicionarMensagem('assistant', 'Não consegui concluir a solicitação agora. Tente novamente em instantes.');
            } finally {
                enviando = false;
                entrada.disabled = false;
                enviar.disabled = false;
                entrada.focus();
            }
        });
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', iniciarBotIA, {once: true});
    } else {
        iniciarBotIA();
    }
})();
