/**
 * JUEGO BINGO - Lógica de Tiempo Real
 * Maneja: Marcado de cartones, detección de ganadores, sincronización
 */

class JuegoBingoRealtime {
    constructor() {
        this.cartones = [];
        this.numerosMarcados = new Set();
        this.autoMarcar = false;
        this.patronesVictoria = {
            'Tabla Llena': this.verificarTablaLlena,
            'Las Cuatro Esquinas': this.verificarEsquinas,
            'En Diagonal': this.verificarDiagonal,
            'Forma de X': this.verificarX,
            'Forma de Cruz': this.verificarCruz,
            'Marco de Foto': this.verificarMarco,
            'Linea Vertical': this.verificarLineaVertical,
            'Linea Horizontal': this.verificarLineaHorizontal,
            'Forma de L': this.verificarL,
        };
        
        this.inicializar();
    }
    
    inicializar() {
        // Cargar cartones desde el DOM
        document.querySelectorAll('.carton-dinamico').forEach(cartonDiv => {
            const matrizStr = cartonDiv.getAttribute('data-carton-matriz');
            try {
                const matriz = JSON.parse(matrizStr);
                const cartonId = cartonDiv.getAttribute('data-carton-id');
                this.cartones.push({
                    id: cartonId,
                    matriz: matriz,
                    elemento: cartonDiv,
                    marcadas: new Set([12]) // El centro (FREE) siempre está marcado
                });
            } catch (e) {
                console.error('Error cargando cartón:', e);
            }
        });
        
        // Escuchar eventos de partida
        document.addEventListener('evento_partida', (e) => this.procesarEvento(e.detail));
        
        // Auto-marcado manual por clic
        document.querySelectorAll('.celda-pista').forEach(celda => {
            celda.addEventListener('click', (e) => {
                if (e.target.closest('.carton-dinamico')) {
                    this.marcarCeldaManual(celda);
                }
            });
        });
        
        // Switch de auto-marcado
        const switchAuto = document.getElementById('switch-automarcado');
        if (switchAuto) {
            switchAuto.addEventListener('change', (e) => {
                this.autoMarcar = e.target.checked;
            });
        }
    }
    
    procesarEvento(evento) {
        if (evento.evento === 'nueva_bola') {
            const numero = evento.numero;
            console.log(`📍 Se llamó el número: ${numero}`);
            
            this.numerosMarcados.add(numero);
            
            // Auto-marcar si está habilitado
            if (this.autoMarcar) {
                this.marcarNumeroEnTodos(numero);
            }
            
            // Verificar si hay ganador
            setTimeout(() => this.verificarGanador(), 100);
        }
    }
    
    marcarNumeroEnTodos(numero) {
        document.querySelectorAll('.celda-pista').forEach(celda => {
            const numeroStr = celda.querySelector('.numero-celda')?.textContent?.trim();
            if (numeroStr === String(numero)) {
                if (!celda.classList.contains('marcada') && !celda.classList.contains('free')) {
                    celda.classList.add('marcada');
                    celda.style.backgroundColor = '#ffc107';
                    celda.style.borderColor = '#ff9800';
                    celda.querySelector('.marcado-visual')?.classList.remove('d-none');
                    
                    // Actualizar contador
                    const cartonDiv = celda.closest('.carton-dinamico');
                    if (cartonDiv) {
                        const contador = cartonDiv.querySelector('.contador-marcados');
                        if (contador) {
                            const marcadas = cartonDiv.querySelectorAll('.marcada, .free').length;
                            contador.textContent = marcadas;
                        }
                    }
                }
            }
        });
    }
    
    marcarCeldaManual(celda) {
        if (celda.classList.contains('free')) return;
        
        celda.classList.toggle('marcada');
        
        if (celda.classList.contains('marcada')) {
            celda.style.backgroundColor = '#ffc107';
            celda.style.borderColor = '#ff9800';
            celda.querySelector('.marcado-visual')?.classList.remove('d-none');
        } else {
            celda.style.backgroundColor = '#fff';
            celda.style.borderColor = '#ddd';
            celda.querySelector('.marcado-visual')?.classList.add('d-none');
        }
        
        // Actualizar contador
        const cartonDiv = celda.closest('.carton-dinamico');
        if (cartonDiv) {
            const contador = cartonDiv.querySelector('.contador-marcados');
            if (contador) {
                const marcadas = cartonDiv.querySelectorAll('.marcada, .free').length;
                contador.textContent = marcadas;
            }
        }
    }
    
    verificarGanador() {
        for (let carton of this.cartones) {
            const modalidad = document.querySelector('[data-modalidad]')?.getAttribute('data-modalidad');
            
            if (modalidad && this.patronesVictoria[modalidad]) {
                if (this.patronesVictoria[modalidad].call(this, carton)) {
                    this.declararGanador(carton, modalidad);
                    return;
                }
            }
        }
    }
    
    obtenerCeldasMarcadas(carton) {
        const celdas = carton.elemento.querySelectorAll('.celda-pista');
        const marcadas = [];
        
        celdas.forEach((celda, idx) => {
            if (celda.classList.contains('marcada') || celda.classList.contains('free')) {
                marcadas.push(idx);
            }
        });
        
        return marcadas;
    }
    
    // Patrones de victoria
    verificarTablaLlena(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        return marcadas.length === 25;
    }
    
    verificarEsquinas(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        return [0, 4, 20, 24].every(idx => marcadas.includes(idx));
    }
    
    verificarDiagonal(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        const diag1 = [0, 6, 12, 18, 24].every(idx => marcadas.includes(idx));
        const diag2 = [4, 8, 12, 16, 20].every(idx => marcadas.includes(idx));
        return diag1 || diag2;
    }
    
    verificarX(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        return [0, 4, 6, 8, 12, 16, 18, 20, 24].every(idx => marcadas.includes(idx));
    }
    
    verificarCruz(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        return [2, 7, 10, 11, 12, 13, 14, 17, 22].every(idx => marcadas.includes(idx));
    }
    
    verificarMarco(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        return [0,1,2,3,4, 5,9, 10,14, 15,19, 20,21,22,23,24].every(idx => marcadas.includes(idx));
    }
    
    verificarLineaVertical(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        const col1 = [0, 5, 10, 15, 20].every(idx => marcadas.includes(idx));
        const col2 = [1, 6, 11, 16, 21].every(idx => marcadas.includes(idx));
        const col3 = [2, 7, 12, 17, 22].every(idx => marcadas.includes(idx));
        const col4 = [3, 8, 13, 18, 23].every(idx => marcadas.includes(idx));
        const col5 = [4, 9, 14, 19, 24].every(idx => marcadas.includes(idx));
        return col1 || col2 || col3 || col4 || col5;
    }
    
    verificarLineaHorizontal(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        const fila1 = [0, 1, 2, 3, 4].every(idx => marcadas.includes(idx));
        const fila2 = [5, 6, 7, 8, 9].every(idx => marcadas.includes(idx));
        const fila3 = [10, 11, 12, 13, 14].every(idx => marcadas.includes(idx));
        const fila4 = [15, 16, 17, 18, 19].every(idx => marcadas.includes(idx));
        const fila5 = [20, 21, 22, 23, 24].every(idx => marcadas.includes(idx));
        return fila1 || fila2 || fila3 || fila4 || fila5;
    }
    
    verificarL(carton) {
        const marcadas = this.obtenerCeldasMarcadas(carton);
        return [0, 5, 10, 15, 20, 21, 22, 23, 24].every(idx => marcadas.includes(idx));
    }
    
    declararGanador(carton, modalidad) {
        console.log(`🎉 ¡GANADOR! Cartón ${carton.id} con patrón: ${modalidad}`);
        
        // Animar el cartón ganador
        carton.elemento.classList.add('animate__animated', 'animate__bounce', 'carton-ganador');
        carton.elemento.style.boxShadow = '0 0 30px rgba(255, 193, 7, 0.8)';
        
        // Mostrar notificación
        this.mostrarNotificacionGanador(carton.id, modalidad);
        
        // Enviar evento al servidor (si hay WebSocket)
        if (window.bingoSocket && window.bingoSocket.readyState === WebSocket.OPEN) {
            window.bingoSocket.send(JSON.stringify({
                tipo: 'bingo_ganador',
                carton_id: carton.id,
                modalidad: modalidad
            }));
        }
    }
    
    mostrarNotificacionGanador(cartonId, modalidad) {
        const zonaNotificaciones = document.getElementById('zona-notificaciones-bingo');
        if (zonaNotificaciones) {
            const notif = document.createElement('div');
            notif.className = 'alert alert-success alert-dismissible fade show animate__animated animate__bounceInDown shadow-lg';
            notif.innerHTML = `
                <div class="d-flex align-items-center">
                    <i class="fas fa-trophy text-warning me-2 fs-4"></i>
                    <div>
                        <strong>🎉 ¡BINGO!</strong><br>
                        <small>Cartón #${cartonId} - Patrón: ${modalidad}</small>
                    </div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            zonaNotificaciones.appendChild(notif);
            
            // Auto-cerrar en 10 segundos
            setTimeout(() => notif.remove(), 10000);
        }
    }
}

// Inicializar cuando el DOM esté listo
document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelector('.carton-dinamico')) {
        window.juegoBingo = new JuegoBingoRealtime();
        console.log('✅ Sistema de juego en tiempo real inicializado');
    }
});
