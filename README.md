# Coppel Map

Mapa interactivo de las tiendas Coppel en México, con los datos del localizador oficial de coppel.com (consultado el 13 de noviembre de 2026).

- **1,709 tiendas Coppel** en los 32 estados.
- **2,480 ubicaciones** en total, contando cajeros, BanCoppel, Afore Coppel, Coppel Canadá, Motos, Bodega y Fashion Market.

## Contenido

| Archivo | Qué es |
| --- | --- |
| `index.html` | Mapa interactivo (Leaflet). Filtra por estado, tipo de ubicación o búsqueda por nombre, municipio o CP. Ábrelo en el navegador o publícalo con GitHub Pages. |
| `data/tiendas_coppel_oficial.csv` | Las 1,709 tiendas: name, address, municipality, state, postal_code, lat, lon, tipos, phone, location_id, url. |
| `data/coppel_todas_ubicaciones_oficial.csv` | Las 2,480 ubicaciones, con una columna 0/1 por tipo (`es_tiendas_coppel`, `es_cajero`, etc.). |
| `data/conteo_por_estado.csv` | Número de tiendas Coppel por estado. |

## Fuente

Las coordenadas son las del pin de cada ubicación en el localizador oficial ([coppel.com/ubicacion-de-tiendas-coppel](https://www.coppel.com/ubicacion-de-tiendas-coppel)). El contorno de los estados del mapa es simplificado, así que algunas tiendas en la costa pueden verse ligeramente fuera de la línea.
