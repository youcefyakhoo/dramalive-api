# Drama Live — API + reproductor (todo en uno)

Lee playlists **FG Code** de Drama Live (TV, radio), resuelve **todas** las
fuentes de cada canal y las reproduce. Sin WebView, sin claves de terceros.

## Arrancar

```bash
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

Abre `http://localhost:8000` en el navegador. El código FG va en la barra de
arriba (por defecto `232425`).

En Windows, si `uvicorn` no se reconoce:

```bat
python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

## Qué hay dentro

| Fichero | Para qué |
|---|---|
| `drcrypto.py` | cifrado AES-128-CBC de la API (clave incluida) |
| `drama_client.py` | cliente: `glt`, `glbt`, `glasbi`, `glbr` + probar todas las opciones |
| `server.py` | API FastAPI + proxy HLS + la web |
| `static/index.html` | la interfaz (TV/Radio, canales, todas las opciones) |
| `static/hls.min.js` | reproductor HLS (incluido, no usa CDN) |
| `COMO-FUNCIONA.md` | la investigación completa: endpoints, cifrado, trampas |

## Endpoints

```
GET /salud
GET /temas/{codigo}?tipo=tv|radio
GET /canales/{codigo}/{tema}?tipo=tv
GET /canal/{codigo}/{id_live}
GET /opciones/{codigo}/{id_live}          <- TODAS las fuentes, probadas
GET /p/{codigo}/{id_live}/{n}.m3u8        <- manifiesto de una opción (proxy)
GET /ps/{codigo}/{id_live}/{n}/{recurso}  <- sus segmentos (proxy)
GET /stream/{codigo}/{id_live}?n=0        <- 302 a la URL real
GET /lista/{codigo}.m3u                   <- playlist M3U
```

Docs interactivas: `http://localhost:8000/docs`

## Notas

- El proxy (`/p`, `/ps`) es obligatorio: los segmentos exigen `Referer` y
  `User-Agent` que un `<video>` del navegador no puede enviar.
- `{n}` es el número que da el proveedor, no la posición en la lista.
- La ventana del directo rota cada pocos segundos: si un segmento caduca, el
  proxy vuelve a resolver y reintenta una vez.
