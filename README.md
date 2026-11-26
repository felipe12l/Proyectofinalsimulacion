# Simulación de defensa naval

Simulador híbrido de eventos discretos y dinámica continua, compatible con Python
3.10+ y sin dependencias externas.

## Ejecutar

```bash
python3 simulation.py
python3 -m unittest
python3 web_server.py
```

Al iniciar el servidor, abre `http://127.0.0.1:8000` en el navegador. La interfaz
permite ajustar los parámetros del escenario, ejecutar la simulación y consultar
indicadores, distribución de estados y resultados individuales. El servidor web
usa `http.server` de Python; no requiere paquetes adicionales. Por defecto solo
escucha en `127.0.0.1`.

### Publicar en internet con Render

El archivo `render.yaml` deja configurado un servicio público. Para obtener tu
enlace:

1. Sube este proyecto a un repositorio de GitHub.
2. En Render, crea un **Blueprint** y conecta ese repositorio.
3. Espera el despliegue; Render mostrará una URL pública `*.onrender.com`.

La URL queda activa según el estado de tu servicio en Render. El servidor web
limita cada ejecución a un presupuesto de cómputo y admite como máximo dos
simulaciones simultáneas; la función serverless y el motor local conservan los
rangos completos de la especificación.

La función `run_simulation(payload)` devuelve un diccionario serializable a JSON.
`lambda_handler(event, context)` acepta el payload directamente o en `event.body`
(objeto o texto JSON), para uso en AWS Lambda y runtimes serverless similares.

### Análisis Monte Carlo

En la interfaz selecciona el número de corridas (N ≥ 100) y pulsa **Ejecutar
Monte Carlo**. Ejecuta N réplicas para cada salva de 5, 10 y 20 amenazas (3N
simulaciones), en modo estocástico, y muestra la tasa de supervivencia con
intervalo Wilson bilateral del 95 % y diagrama de barras con sus límites.
Se considera superviviente una corrida sin impactos sobre el buque durante el
horizonte simulado; el horizonte debe permitir lanzar la salva completa de 20.
Las semillas `base_seed + índice_de_réplica` se emparejan
entre tamaños de salva para facilitar su comparación; el máximo es 1000
réplicas por grupo.

También se puede ejecutar desde Python:

```python
from simulation import run_monte_carlo

result = run_monte_carlo({
    "runs": 100,
    "seed": 42,
    "mode": "est",
})
```

La ruta web `POST /api/monte-carlo` devuelve el mismo resumen agregado. En la
entrada Lambda, usa `"operation": "monte_carlo"` junto con los parámetros y
`runs`.

Ejemplo:

```python
from simulation import run_simulation

result = run_simulation({
    "seed": 42,
    "mode": "est",
    "threat_count": 5,
    "duration_s": 90,
})
```

Todos los parámetros omitidos toman los valores predeterminados de
`SimulationConfig`. Los valores suministrados se validan contra los rangos de la
especificación; `threat_count` acepta 5, 10 o 20. Para estudiar radares degradados,
`detection_probability` admite 0–1; un valor de 0 desactiva detecciones.

## Dónde se aplica cada concepto

| Concepto | Aplicación |
| --- | --- |
| Variables ambientales y reproducibilidad | La gravedad es constante y `SimulationConfig` valida densidad, viento, oleaje, clutter, modo y semilla. `Environment` actualiza viento con paseo aleatorio, dirección por ejecución y cabeceo sinusoidal. |
| Entidades y perfiles de amenaza | `Threat` conserva posición, velocidad, masa, arrastre, área y perfil; `_new_threat()` genera perfiles balístico y rasante dentro de los rangos solicitados. |
| S0-S6 y reglas FSM | `ThreatState`, `_radar_sweep()`, `_evaluate()`, `_dispatch_fire_control()`, `_impact_state()` y `_resolve_detonation()` implementan detección, pérdida de track, evaluación, espera, intercepción, fallo, impacto e inocuidad. |
| Radar, horizonte y clutter | `_radar_limit_m()` calcula el horizonte; `_radar_sweep()` aplica periodo/capacidad; `_poisson()` muestrea ecos y `_detection_chance()` reduce Pd con rango y clutter. |
| Integración continua y arrastre | `_integrate_threat()` aplica Euler explícito, arrastre cuadrático relativo al viento y gravedad; `_move_ship()` representa deriva simplificada del buque. |
| Cola y control de fuego | `pending_fire` es la cola de amenazas evaluadas; `_dispatch_fire_control()` respeta capacidad de interceptores, latencia, TTI y orden de prioridad. |
| Guiado e intercepción | `_guide_interceptors()` usa navegación proporcional, comprueba el radio de espoleta y `_resolve_detonation()` decide neutralización según Pk. |
| Indicadores de rendimiento | `_result()` calcula throughput, espera media, conteos FSM, cola máxima, recursos restantes y detalle por amenaza. |
| Monte Carlo e incertidumbre | `run_monte_carlo()` ejecuta réplicas estocásticas para Nₐ=5, 10 y 20; `wilson_confidence_interval()` estima el IC del 95 % para la tasa binomial de supervivencia. |
| Serverless / JSON | `run_simulation()` no guarda estado entre invocaciones; `lambda_handler()` valida/decodifica el evento y propaga errores de entrada claramente. |
| Aplicación web | `web/index.html` contiene el formulario y los paneles; `web/app.js` representa métricas, FSM y amenazas; `web_server.py` sirve la interfaz, limita solicitudes y conecta `/api/simulate` con el mismo motor Python; `render.yaml` configura su publicación. |

En modo `det`, el entorno se fija sin viento, oleaje ni clutter y los parámetros
aleatorios usan sus puntos medios. La detección usa su valor esperado, pero Pk se
muestrea con la semilla para que pueda haber neutralizaciones fallidas; el mismo
payload sigue produciendo el mismo resultado. En modo `est`, las variaciones y
eventos probabilísticos usan el generador local inicializado con `seed`, sin
compartir estado global.

## Límites del modelo

Es un simulador educativo agregado, no un modelo de ingeniería ni una predicción
operacional. La deriva del buque, el vuelo rasante y la guía de interceptores son
aproximaciones discretizadas; el paso fijo `dt_s` se limita al intervalo
`0.001–0.05 s` especificado.
