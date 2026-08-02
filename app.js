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
})();
