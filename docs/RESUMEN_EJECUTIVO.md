# FitZone · Resumen ejecutivo de calidad (Unidad 5)

**Para quién es:** cualquier persona del negocio, sin conocimientos de programación.

## En una frase
Las reglas del gimnasio que importan (quién entra, quién reserva, cuántos caben) están comprobadas
**automáticamente**: 180 revisiones se ejecutan en segundos y **todas pasan**.

## ¿Qué significa cada número?
| Resultado | Qué quiere decir en lenguaje de negocio |
| --- | --- |
| **180 pruebas, 0 fallas** | Se simularon 180 situaciones reales (socio con membresía vencida, clase llena, doble reserva, rol sin permiso…) y el sistema respondió bien en todas. |
| **100% de cobertura** (meta: 80%) | Cada línea de las reglas del negocio fue puesta a prueba al menos una vez. Ninguna regla quedó "sin revisar". |
| **CI en GitHub** | Cada vez que alguien cambia algo, GitHub repite todas las revisiones solo. Si algo se rompe, avisa con una ❌ antes de que llegue a los socios. |

## ¿Qué problemas del BRD ayuda a evitar?
- **Accesos indebidos** (membresía vencida o clase fuera del plan): BR-06 y BR-07.
- **Sobrecupo y lugares mal asignados:** BR-05, con control para que dos personas no se queden con el último lugar.
- **Acciones sin permiso** (por ejemplo, recepción modificando membresías): BR-01 a BR-04.
- **Inasistencias (no-shows) sin registrar:** BR-08.

## Seguridad de las pruebas
Ningún dato real se toca: la base de datos de prueba vive solo en memoria y desaparece al terminar.
Los avisos y los cobros se **simulan**: no se envía ningún correo ni se cobra a nadie.

## Lo que sigue pendiente (decisiones de FitZone, no de programación)
Política de cancelación (BR-10), consecuencia de un no-show (BR-09) y tiempo límite para confirmar
un lugar de la lista de espera. Hoy el sistema usa valores provisionales y lo declara así.

## Cómo ver la evidencia
- Reporte de cobertura (abrir en el navegador): `docs/evidencias/cobertura_html/index.html`
- Salida de pruebas y cobertura: `docs/evidencias/SECCION4_cobertura.txt`
- Revisión automática: pestaña **Actions** del repositorio en GitHub.
