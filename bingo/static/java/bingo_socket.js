/* =========================================
   BINGO SOCKET JS - Motor de Tiempo Real
   ========================================= */



const BINGO_VAR = typeof window.BINGO_CONFIG !== 'undefined' ? window.BINGO_CONFIG : (typeof BINGO_CONFIG !== 'undefined' ? BINGO_CONFIG : null);



if (BINGO_VAR) {
    const protocolo = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
    const wsUrl = protocolo + window.location.host + '/ws/juego/' + BINGO_VAR.id_partida + '/';
    
    let pingInterval = null;
    let reconnectTimeout = null;
    let cierreIntencional = false;



    function conectarWebSocket() {
        console.log("Intentando conectar al servidor de juego en:", wsUrl);
        window.bingoSocket = new WebSocket(wsUrl);



        window.bingoSocket.onopen = function(e) {
            console.log("🟢 Conectado al sistema de eventos en tiempo real.");
            clearTimeout(reconnectTimeout);
            
            pingInterval = setInterval(() => {
                if (window.bingoSocket.readyState === WebSocket.OPEN) {
                    window.bingoSocket.send(JSON.stringify({ 'tipo': 'ping' }));
                }
            }, 30000); 
        };



        window.bingoSocket.onclose = function(e) {
            clearInterval(pingInterval);
            if (!cierreIntencional) {
                console.warn("🔴 Conexión perdida. Reconectando en 3 segundos...");
                reconnectTimeout = setTimeout(conectarWebSocket, 3000);
            }
        };



        window.bingoSocket.onerror = function(err) {
            console.error("Socket error:", err);
            window.bingoSocket.close(); 
        };



        window.bingoSocket.onmessage = function(e) {
            const payload = JSON.parse(e.data);
            if (payload.canal === 'pong') return; 
            
            if (payload.canal === 'partida') {
                document.dispatchEvent(new CustomEvent('evento_partida', { detail: payload.datos }));
                
                if (payload.datos.evento === 'nueva_bola') {
                    const bolaMaestra = document.getElementById(`bola-maestra-${payload.datos.numero}`);
                    if (bolaMaestra) {
                        bolaMaestra.classList.remove('ball-pending');
                        bolaMaestra.classList.add('ball-called');
                        const colorClass = bolaMaestra.getAttribute('data-color');
                        if(colorClass) bolaMaestra.classList.add(colorClass);
                    }
                }
                else if (payload.datos.evento === 'alerta_admin') {
                    const soyAdmin = document.getElementById('admin-mensaje-input') !== null;
                    if (!soyAdmin) {
                        const toastContainer = document.getElementById('admin-toast-container') || (() => {
                            const tc = document.createElement('div');
                            tc.id = 'admin-toast-container';
                            tc.className = 'toast-container position-fixed top-0 start-50 translate-middle-x p-3 mt-2';
                            tc.style.zIndex = '10500';
                            document.body.appendChild(tc);
                            return tc;
                        })();



                        const toastId = 'toast-' + Date.now();
                        const toastHtml = `
                            <div id="${toastId}" class="toast align-items-center text-bg-danger border-0 shadow-lg animate__animated animate__bounceInDown" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="6000">
                                <div class="d-flex">
                                    <div class="toast-body fs-6 fw-bold text-center w-100 p-3">
                                        <i class="fas fa-bullhorn fs-4 d-block mb-2 text-warning"></i> 
                                        ${payload.datos.mensaje}
                                    </div>
                                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                                </div>
                            </div>
                        `;
                        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
                        const toastElement = document.getElementById(toastId);
                        const toast = new bootstrap.Toast(toastElement);
                        toast.show();
                        toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
                    }
                }
                else if (payload.datos.evento === 'alerta_reclamo') {
                    const aliasGanador = payload.datos.alias;
                    const codigoCarton = payload.datos.codigo;
                    const esAdmin = document.querySelector('.master-board') !== null;
                    
                    if (esAdmin) {
                        const lista = document.getElementById('lista-jugadores-conectados');
                        if (lista) {
                            let items = Array.from(lista.getElementsByTagName('li'));
                            let liGanador = items.find(li => li.innerText.includes(aliasGanador));
                            if (liGanador) {
                                liGanador.classList.remove('border-light');
                                liGanador.classList.add('border-danger', 'border-2', 'bg-danger-subtle', 'animate__animated', 'animate__flash');
                                const viejaMedalla = liGanador.querySelector('.medalla-bingo');
                                if(viejaMedalla) viejaMedalla.remove();
                                liGanador.innerHTML += `<span class="medalla-bingo badge bg-danger ms-auto animate__animated animate__tada animate__infinite shadow"><i class="fas fa-trophy"></i> BINGO</span>`;
                            }
                        }
                    }
                }
            } 
            else if (payload.canal === 'chat') {
                const cajaChat = document.getElementById('chat-mensajes');
                if (cajaChat) {
                    const esMiMensaje = (payload.usuario === (BINGO_VAR && BINGO_VAR.mi_alias));
                    const nuevoMensaje = document.createElement('div');
                    nuevoMensaje.className = `mb-3 d-flex flex-column ${esMiMensaje ? 'align-items-end' : 'align-items-start'} animate__animated animate__fadeInUp animate__faster`;
                    const colorFondo = esMiMensaje ? 'bg-primary text-white shadow-sm' : 'bg-light text-dark border shadow-sm';
                    const colorNombre = esMiMensaje ? 'text-primary' : 'text-secondary';
                    const nombreAlias = esMiMensaje ? 'Tú' : payload.usuario;
                    
                    nuevoMensaje.innerHTML = `
                        <span class="small fw-bold ${colorNombre} mb-1 px-1" style="font-size: 0.70rem; letter-spacing: 0.5px;">${nombreAlias}</span>
                        <div class="px-3 py-2 rounded-4 ${colorFondo}" style="max-width: 90%; word-break: break-word; font-size: 0.9rem; line-height: 1.4;">
                            ${payload.mensaje}
                        </div>
                    `;
                    cajaChat.appendChild(nuevoMensaje);
                    cajaChat.scrollTop = cajaChat.scrollHeight;
                }
            }
            else if (payload.canal === 'presencia') {
                const listaJugadores = payload.lista_jugadores;
                const cantidad = listaJugadores.length;
                
                document.querySelectorAll('.contador-dinamico').forEach(c => c.textContent = cantidad);



                let htmlJugadores = '';
                let htmlAdmin = '';



                if (cantidad === 0) {
                    htmlJugadores = `
                        <li class="list-group-item bg-transparent border-0 text-center text-body-secondary py-5">
                            <i class="fas fa-ghost fs-1 mb-3 text-muted"></i><br>
                            No hay rivales en la sala aún.
                        </li>`;
                    htmlAdmin = `<li class="list-group-item text-center text-muted py-4"><i class="fas fa-ghost mb-2 fs-3"></i><br>Nadie en la sala</li>`;
                } else {
                    listaJugadores.forEach(alias => {
                        const inicial = alias.charAt(0).toUpperCase();
                        
                        htmlJugadores += `
                            <li class="list-group-item bg-transparent text-body d-flex align-items-center py-3 animate__animated animate__fadeIn" data-alias="${alias}">
                                <div class="text-white rounded-circle d-flex justify-content-center align-items-center me-3 flex-shrink-0" 
                                     style="width: 35px; height: 35px; font-weight: bold; background-color: #4F46E5;">
                                    ${inicial}
                                </div>
                                <span class="fw-bold text-truncate">${alias}</span>
                            </li>`;
                            
                        htmlAdmin += `
                            <li class="list-group-item d-flex align-items-center py-2 animate__animated animate__fadeIn border-light" data-alias="${alias}">
                                <i class="fas fa-user-circle text-primary me-2 fs-4"></i>
                                <span class="fw-bold text-secondary text-truncate">${alias}</span>
                            </li>`;
                    });
                }



                document.querySelectorAll('.lista-jugadores-dinamica').forEach(lista => {
                    lista.innerHTML = htmlJugadores;
                });



                const radarAdmin = document.getElementById('lista-jugadores-conectados');
                if (radarAdmin) {
                    radarAdmin.innerHTML = htmlAdmin;
                }
            }
        };
    }



    conectarWebSocket();



    // =======================================================
    // FIX SUPREMO: ACELERADOR DE DESCONEXIÓN (CERO DELAY)
    // =======================================================
    window.addEventListener('beforeunload', function() {
        cierreIntencional = true;
        if (window.bingoSocket && window.bingoSocket.readyState === WebSocket.OPEN) {
            window.bingoSocket.send(JSON.stringify({ 'tipo': 'salida_inmediata' }));
            window.bingoSocket.close(1000, "Cierre fulminante");
        }
    });



    // Trampa para atrapar el clic a otros enlaces (Logotipo, Menús, Botones)
    document.addEventListener('click', function(e) {
        const link = e.target.closest('a');
        if (link && link.href && !link.href.includes('javascript:') && !link.href.includes('#') && link.target !== '_blank') {
            e.preventDefault(); // Pausamos la navegación un instante
            cierreIntencional = true;
            if (window.bingoSocket && window.bingoSocket.readyState === WebSocket.OPEN) {
                // Le GRITAMOS al servidor que actualice la BD y el radar al instante
                window.bingoSocket.send(JSON.stringify({ 'tipo': 'salida_inmediata' }));
                window.bingoSocket.close();
            }
            // Retomamos la navegación luego de 50ms imperceptibles
            setTimeout(() => {
                window.location.href = link.href;
            }, 50); 
        }
    });



    document.addEventListener('submit', function() {
        cierreIntencional = true;
        if (window.bingoSocket && window.bingoSocket.readyState === WebSocket.OPEN) {
            window.bingoSocket.send(JSON.stringify({ 'tipo': 'salida_inmediata' }));
        }
    });
    // =======================================================



    // Lógica del Chat
    document.addEventListener('DOMContentLoaded', () => {
        const chatInput = document.getElementById('chat-input');
        const chatBtn = document.getElementById('chat-btn-enviar');
        if (chatInput && chatBtn) {
            function enviarMensajeChat() {
                if (chatInput.value.trim() !== '') {
                    window.bingoSocket.send(JSON.stringify({ 'tipo': 'chat', 'mensaje': chatInput.value.trim() }));
                    chatInput.value = ''; 
                }
            }
            chatBtn.addEventListener('click', enviarMensajeChat);
            chatInput.addEventListener('keyup', (e) => { if (e.key === 'Enter') enviarMensajeChat(); });
        }
    });
}
