# Pixtuoid + Herdr V1.8 (experimental)

Cambios incrementales sobre V1.7:

- `./pixtuoid-herdr` abre Floating sin parámetros, conservando `./pixtuoid-herdr floating`.
- Tamaño inicial del Floating: **1600 × 1000**, zoom **3**. Se aplica una vez por versión; después podés redimensionar.
- Label encima de cada personaje: estado legible (`Pensando en…`, `Necesita atención` o `Tarea:`) y título del job multilínea. El nombre se obtiene del título expuesto por Herdr, con fallback al directorio; no es un resumen generado.
- Se conservan focus de Herdr, detección de agentes, animaciones al mover el mouse (solo se pausa la locomoción), tooltip con última respuesta disponible y Soft Gray opcional.

## Pisos y capacidad

**No se fuerza una capacidad mayor a la geometría real.** Pixtuoid decide cuántos escritorios puede dibujar por piso según ventana y zoom; falsear este número puede hacer invisibles a los agentes. Por eso, con muchos agentes todavía pueden existir varios floors. La concentración efectiva en un único piso requiere modificar el layout o reducir zoom, no solo el contador.

## Compilación

GitHub Actions usa Pixtuoid `v0.21.0` como base del parche y prepara el artifact Linux. El workflow se ejecuta automáticamente en el PR para validar la compilación; `workflow_dispatch` sigue disponible.

**Estado:** patch y pruebas Python verificados localmente con un checkout sintético; compilación Rust y rendering real pendientes de GitHub Actions. No reemplazar el binario V1.7 hasta probar.
