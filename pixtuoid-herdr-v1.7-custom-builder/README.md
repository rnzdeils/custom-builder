# Pixtuoid + Herdr V1.7 · pausa de desplazamiento + oficina gris suave

**Kit experimental para `rnzdeils/custom-builder`**. Se basa en la V1.6, preserva la detección, estados, focus, etiquetas completas y tooltip. Ningún proceso adicional en ejecución.

## Cambios

1. **Puntero sobre Floating:** se aplica `Motion::Still` al movimiento espacial de los personajes. **No se congela `self.ui.now()`**: las animaciones de escritura/espera/alertas pueden avanzar mientras el mouse está sobre la oficina. Cuando el mouse sale, vuelve la locomoción normal. Las actualizaciones reales de estado continúan.
2. **Herdr Soft Gray, variante de paleta:** el build transforma los colores de ambientación del tema `normal` (grupos `surface`, `office`, `furniture`, `lighting`, `appliance`) reduciendo su saturación, dejando **sin modificar** los colores de ropa/personajes, badges de fuente, interfaz y glows de herramientas. Se hace en `theme/normal.rs` del checkout de compilación. No registra un séptimo tema: es una **variante del tema `normal`** en *este fork*. Los otros temas oficiales no se modifican. 
3. Conserva la compilación GitHub Actions: un binario nativo para Linux, que se ejecuta sin Rust ni contenedores.

## Instalar en custom-builder

Copiar a la raíz del repo `.github/workflows/pixtuoid-herdr.yml` y `pixtuoid-herdr/`. Desde GitHub Actions ejecutar **Build Pixtuoid + Herdr (Linux)**:

- `upstream_ref`: preferentemente el commit de Pixtuoid con el que ya compiló tu V1.6, para evitar variaciones de upstream.
- `gray_office`: `true` para intentar la paleta gris. `false` para compilar con el tema original.
- `run_rust_tests`: opcional, no necesario para producir el binario.

Descargar el artifact `pixtuoid-herdr-linux-x86_64`, descomprimir y ejecutar:

```bash
./pixtuoid-herdr floating
```

La paleta modificada se ve cuando el tema activo es `normal`. Si tenés otro tema activo, cambia `theme = "normal"` en `~/.config/pixtuoid/config.toml` con Pixtuoid cerrado (esa sección debe estar a nivel raíz, antes de `[floating]`).

## Compatibilidad y limitaciones

- No se pudo descargar ni compilar el upstream en este entorno. **La compilación y la estética real están pendientes de validar en GitHub Actions.** Las pruebas Python solo validan el aplicador sobre fragmentos de código simulados y el transformador de paleta sobre un ejemplo sintético.
- Si el upstream cambia el formato de la paleta, el Action emite un warning y mantiene el tema `normal` original; no modifica parcialmente una paleta desconocida.
- La variante Soft Gray **no está registrada como tema elegible** en el selector `t`. Para restaurar el normal clásico recompilar con `gray_office=false`, o seleccionar cualquiera de los otros temas oficiales.
- No se oscurecen los sprites de personajes; no se leen ni modifican prompts o respuestas. El bridge no existe, sigue siendo un solo proceso Pixtuoid.
- Solo se cambia la locomoción de los personajes. El modo `Still` de Pixtuoid puede afectar algunos recorridos propios de la oficina (mascotas, paseos) — validar el comportamiento final en pantalla.

## Pruebas locales del kit

```bash
python3 -m unittest discover -s pixtuoid-herdr/tests -v
```

V1.6 permanece como respaldo. No sustituir el ejecutable que ya te funciona hasta verificar V1.7.
