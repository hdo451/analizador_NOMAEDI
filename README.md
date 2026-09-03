# Mes a Mes

Analizador simple e híbrido de estados de cuenta. Reúne varios PDFs,
consolida sus movimientos por mes y muestra exactamente cuánto cambiaron los
ingresos y los gastos entre dos períodos.

Esta variante vive en la rama `feature/resumen-mensual-deterministico` y no
incluye el solucionador de problemas cotidianos ni recomendaciones financieras
generadas por IA. La IA es opcional y se limita a proponer categorías.

## Qué hace

- Acepta varios estados de cuenta PDF en una sola ejecución.
- Asigna automáticamente cada archivo a uno de seis perfiles: principal,
  ahorros, tarjeta de crédito, segunda tarjeta, conjunta u otra.
- Acepta varios archivos de la misma cuenta, por ejemplo uno por mes.
- Agrupa transacciones según el mes real de cada movimiento.
- Compara gastos, ingresos, resultado neto y categorías entre dos meses.
- Compara lado a lado el gasto de cada categoría en los dos meses elegidos.
- Resume las categorías en un máximo de seis filas; el resto se conserva
  agrupado como `Resto de categorías`.
- Advierte cuando los dos meses no contienen las mismas cuentas.
- Excluye transferencias entre cuentas propias y movimientos cuya dirección no
  puede demostrarse.
- Permite corregir el tipo y la categoría de un movimiento durante la sesión.
- Permite crear tres categorías personales para separar gastos que de otro modo
  quedarían en `Otros`.
- Permite desglosar un retiro de cajero en varias líneas de gasto sin cambiar
  ni duplicar el monto original.
- Ofrece un agente experto opcional que revisa `Otros` y categorías automáticas
  basadas en comercios, con salida estructurada y validaciones locales.

## Frontera determinística

La aplicación conserva bajo reglas locales todo lo que afecta los totales:

- extracción, conciliación, dirección débito/crédito, sumas y comparaciones se
  ejecutan localmente con reglas;
- el agente nunca puede cambiar un monto, fecha, cuenta, saldo o dirección;
- las categorías que contradicen la dirección son rechazadas automáticamente;
- los textos de “En palabras simples” salen de plantillas numéricas fijas;
- el tablero muestra movimientos no resueltos, fallbacks, categorías aceptadas
  del agente y número real de llamadas;
- los PDFs duplicados por contenido se bloquean para evitar doble conteo.

Las categorías personales siguen siendo temporales. Las correcciones a
categorías estándar pueden recordarse localmente cuando la opción correspondiente
está activada en la tabla de movimientos.

### Catálogo determinístico de comercios

El archivo [`data/deterministic_merchant_rules.json`](data/deterministic_merchant_rules.json)
contiene reglas versionadas y editables para supermercados, telecomunicaciones,
servicios básicos, suscripciones, restaurantes, transporte, compras, salud,
retiros, comisiones y transferencias explícitas entre cuentas propias. Las
transferencias salientes que identifican claramente a un tercero se clasifican
provisionalmente como `shopping` (Compras) y aparecen con una marca amarilla
para que el usuario confirme o corrija su destino.

Cada regla declara un identificador, categoría, dirección permitida, confianza
y una lista de descriptores. Las coincidencias ignoran mayúsculas, acentos y
separadores, pero respetan límites de palabra. Los comercios ambiguos no reciben
una categoría general sin una señal adicional; por ejemplo, `Walmart Grocery`
se reconoce como supermercado, mientras `Walmart Supercenter` queda para
revisión.

### Memoria local de correcciones

Al aplicar cambios en la tabla, la opción **Recordar mis correcciones** guarda
la descripción normalizada, la dirección débito/crédito y la categoría en
`data/user_category_rules.json`. En los próximos estados de cuenta esa regla
personal tiene prioridad sobre el catálogo general y evita una llamada al
agente. Las categorías personales y las transferencias internas nunca se
guardan como reglas de comercio. El archivo local es útil en desarrollo y
durante la vida de una instancia, pero no constituye almacenamiento durable en
Streamlit Community Cloud; para aprendizaje permanente debe reemplazarse por
una base externa asociada al usuario o a la organización.

### Agente experto opcional

Con una clave configurada, el usuario puede autorizar expresamente el envío de
los movimientos dudosos al modelo `gpt-5.6`. El agente recibe descripción,
fecha, monto, sentido ya determinado, institución, tipo de documento y perfil
de cuenta. No recibe el PDF completo, y antes de enviar se ocultan secuencias
largas que parezcan números de cuenta, tarjeta o referencia.

La respuesta usa Structured Outputs con una lista cerrada de categorías,
confianza, motivo breve y marca de revisión. Una respuesta inválida, incompleta
o incompatible cae en `Otros` para revisión sin detener el análisis. Las
solicitudes se realizan con `store=False`.

### Retiros de efectivo

Cuando se agrega una explicación a un retiro, el movimiento original queda
visible pero deja de sumar por sí mismo. En su lugar, el sistema suma las líneas
agregadas y una línea automática de `Efectivo pendiente de asignar`. La suma de
estas líneas siempre coincide con el retiro original.

## Seis cuentas disponibles

| Cuenta | Uso esperado | Tipo de documento |
|---|---|---|
| Cuenta principal | Movimientos diarios | Cuenta bancaria |
| Ahorros | Ahorro y transferencias | Cuenta bancaria |
| Tarjeta de crédito | Primera tarjeta | Tarjeta de crédito |
| Segunda tarjeta | Tarjeta adicional | Tarjeta de crédito |
| Cuenta conjunta | Cuenta compartida | Cuenta bancaria |
| Otra cuenta | Cuenta bancaria adicional | Cuenta bancaria |

El límite es de seis cuentas, no de seis archivos. Es posible cargar doce PDFs
para comparar dos meses de las seis cuentas.

## Inicio rápido

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

No se necesita una clave de OpenAI para usar el modo basado solo en reglas. Para
habilitar el agente, copia `.streamlit/secrets.toml.example` a
`.streamlit/secrets.toml` y agrega la clave, o define `OPENAI_API_KEY` en un
archivo `.env` local:

```bash
OPENAI_API_KEY="..."
```

En la pantalla de carga, activa el agente y marca el consentimiento. Sin ambas
acciones, ningún dato de movimientos se envía a OpenAI.

## Uso recomendado

1. Exporta PDFs basados en texto desde el banco.
2. Sube todos los documentos de los meses que quieras revisar.
3. Selecciona el mes de referencia y el mes a comparar.
4. Revisa cualquier advertencia de cobertura o dirección desconocida.
5. Corrige movimientos solo cuando puedas confirmar su naturaleza en el PDF.

La comparación usa meses calendario (`AAAA-MM`) derivados de la fecha de cada
transacción. Un estado que cruza dos meses aporta movimientos a ambos.

## Verificación

```bash
python -m pytest -q
python -m py_compile streamlit_app.py main_coordinator.py \
  agents/*.py utils/*.py
```

Las pruebas de `tests/test_monthly_analysis.py` cubren:

- las seis cuentas y su inferencia por nombre de archivo;
- orden cronológico y exclusión de direcciones no resueltas;
- diferencias exactas y porcentajes con base cero;
- agrupación exhaustiva en seis categorías visibles;
- advertencias por cobertura desigual;
- textos generados mediante reglas fijas;
- inicialización y categorización sin llamadas a modelos.

`tests/test_expert_categorizer.py` verifica además la salida estructurada, el
enmascaramiento de identificadores, la selección de reglas revisables, el
fallback seguro y el rechazo de categorías incompatibles con débito/crédito.
`tests/test_merchant_database_categories.py` cubre el catálogo, sus límites de
palabra, la precedencia de correcciones y la memoria separada por dirección.

## Límites conocidos

- Los PDFs escaneados como imagen requieren OCR antes de cargarlos.
- Un formato nuevo sin signos, columnas, secciones o saldos conciliables queda
  marcado para revisión en vez de ser adivinado.
- Las comparaciones con cuentas faltantes siguen siendo matemáticamente
  correctas, pero la interfaz las marca como potencialmente incompletas.
- Es una herramienta educativa; las decisiones financieras deben validarse con
  los documentos originales y, cuando corresponda, con un profesional.
