# Coppel Map

Mapa interactivo de las tiendas Coppel en México, con los datos del localizador oficial de coppel.com (consultado el 13 de noviembre de 2026).

- **1,709 tiendas Coppel** en los 32 estados.
- **2,480 ubicaciones** en total, contando cajeros, BanCoppel, Afore Coppel, Coppel Canadá, Motos, Bodega y Fashion Market.

## Contenido

| Archivo | Qué es |
| --- | --- |
| `index.html` | Mapa interactivo (Leaflet) a pantalla completa, en un solo archivo. Panel flotante en escritorio y hoja inferior deslizable en móvil; buscador con sugerencias (nombre, colonia, municipio, estado o CP; tecla `/`), filtros por región Telcel (R1 a R9), estado y tipo de ubicación, con píldoras de filtros activos y botón para limpiarlos. Pestañas «Resumen» (conteo por estado o por región) y «Ubicaciones» (lista de lo visible, ordenable por cercanía con «Mi ubicación»). Mapa base «Calles» (CARTO/OpenStreetMap) o «Simple» (solo estados coloreados por región), modo claro y oscuro, leyenda plegable y fichas con teléfono, «Cómo llegar», copiar dirección y enlace a la ficha oficial. Los filtros se guardan en la URL (`#r=5&e=Jalisco&q=...`) para compartir la vista. Las sucursales y cajeros BanCoppel que el localizador trae sin tipo (601 ubicaciones) se clasifican por su nombre, así que ya aparecen en el mapa. Ábrelo en el navegador o publícalo con GitHub Pages. |
| `data/tiendas_coppel_oficial.csv` | Las 1,709 tiendas: name, address, municipality, state, postal_code, lat, lon, tipos, phone, location_id, url. |
| `data/coppel_todas_ubicaciones_oficial.csv` | Las 2,480 ubicaciones, con una columna 0/1 por tipo (`es_tiendas_coppel`, `es_cajero`, etc.). |
| `data/conteo_por_estado.csv` | Número de tiendas Coppel por estado. |
| `data/conteo_por_region_telcel.csv` | Número de tiendas Coppel por región Telcel (R1 a R9). |

## Fuente

Las coordenadas son las del pin de cada ubicación en el localizador oficial ([coppel.com/ubicacion-de-tiendas-coppel](https://www.coppel.com/ubicacion-de-tiendas-coppel)). El contorno de los estados del mapa es simplificado, así que algunas tiendas en la costa pueden verse ligeramente fuera de la línea.

## Regiones Telcel

Las regiones R1 a R9 son las 9 regiones celulares definidas por el IFT, que Telcel usa como sus regiones. Cada ubicación trae su región en la columna `region_telcel`.

| Región | Estados |
| --- | --- |
| R1 | Baja California, Baja California Sur y el municipio de San Luis Río Colorado (Sonora) |
| R2 | Sonora (excepto San Luis Río Colorado) y Sinaloa |
| R3 | Chihuahua, Durango y La Laguna de Coahuila (Torreón, Matamoros, San Pedro, Francisco I. Madero y Viesca) |
| R4 | Nuevo León, Tamaulipas y el resto de Coahuila |
| R5 | Jalisco (excepto 12 municipios del norte), Colima, Michoacán y Nayarit |
| R6 | Aguascalientes, Guanajuato, Querétaro, San Luis Potosí, Zacatecas y 12 municipios del norte de Jalisco (Lagos de Moreno, Teocaltiche, Encarnación de Díaz, Ojuelos, Villa Hidalgo, entre otros) |
| R7 | Puebla, Veracruz, Oaxaca, Guerrero y Tlaxcala |
| R8 | Campeche, Chiapas, Quintana Roo, Tabasco y Yucatán |
| R9 | Ciudad de México, Estado de México, Hidalgo y Morelos |

Fuente: [IFT, esquema de regiones celulares](https://www.ift.org.mx/sites/default/files/industria/temasrelevantes/24408/documentos/02-esquemadegranularidadaps.pdf).

En 11 tiendas el estado que trae el localizador no coincide con sus coordenadas (por ejemplo, Coppel Cosmopol aparece en Jalisco pero está en Coacalco, Estado de México). En esos casos la región se asignó según la ubicación real del pin. El mapa colorea estados completos, así que los municipios de excepción no se distinguen en el relleno, pero cada tienda sí trae su región correcta.
