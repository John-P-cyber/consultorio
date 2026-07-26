(() => {
    const requiredRole = document.body.dataset.role;
    if (requiredRole && localStorage.getItem('role') !== requiredRole) {
        window.location.replace('login.html');
        return;
    }

    const windows1252 = {
        0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85,
        0x2020: 0x86, 0x2021: 0x87, 0x02c6: 0x88, 0x2030: 0x89, 0x0160: 0x8a,
        0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e, 0x2018: 0x91, 0x2019: 0x92,
        0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
        0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b, 0x0153: 0x9c,
        0x017e: 0x9e, 0x0178: 0x9f
    };

    const corrigir = value => {
        if (!/[\u00c3\u00c2\u00f0\u00e2]/.test(value)) return value;
        try {
            return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(
                [...value],
                char => windows1252[char.charCodeAt(0)] ?? char.charCodeAt(0)
            ));
        } catch (_) {
            return value;
        }
    };

    const reparar = root => {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) node.nodeValue = corrigir(node.nodeValue);
    };

    const aviso = (message, kind = 'error') => {
        document.querySelector('.app-toast')?.remove();
        const toast = document.createElement('div');
        toast.className = 'app-toast';
        toast.dataset.kind = kind;
        toast.setAttribute('role', 'status');
        toast.textContent = corrigir(String(message));
        document.body.appendChild(toast);
        window.setTimeout(() => toast.remove(), 4200);
    };

    window.alert = message => aviso(
        message,
        /sucesso|cadastrado|marcada|gravado|salvo/i.test(String(message)) ? 'success' : 'error'
    );
    window.mostrarSucesso = message => aviso(message, 'success');
    reparar(document.body);

    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
        if (node.nodeType === Node.TEXT_NODE) node.nodeValue = corrigir(node.nodeValue);
        if (node.nodeType === Node.ELEMENT_NODE) reparar(node);
    }))).observe(document.body, { childList: true, subtree: true });

    const fetchAnterior = window.fetch.bind(window);
    window.fetch = async (...args) => {
        const response = await fetchAnterior(...args);
        if (response.status === 401 && !String(args[0]).includes('/auth/login')) {
            localStorage.clear();
            window.location.replace('login.html');
        }
        return response;
    };
})();
