# Drama Live — cómo funciona por dentro y API funcional

Investigado el 18/11/2026 sobre `https://web.dramalive.cc/` con el código `232425`
(redirige a `fgcode.store`). **Todo lo que sale aquí está medido contra el servidor
real**, no deducido leyendo el bundle.

---

## 1. Qué es realmente

Drama Live **no tiene catálogo propio**. Es un *reproductor de listas*: el usuario
introduce un **FG Code** y la app pide a la API del proveedor
(*FastConnections*) los canales de esa lista privada. El FG Code es una playlist
que alguien creó en `fgcode.store` (código + contraseña + enlaces).

> Su propio aviso legal lo dice: «This app does not supply or include any media or
> content, users must provide their own content».

La web es **Flutter compilado** (`main.dart.js`, 4,3 MB, versión `13.0.3 (241)`),
no React ni HTML: por eso no se ve nada en el código fuente de la página.

```
https://fgcode.org/232425
        │  (redirección 302)
        ▼
https://fgcode.store/link/api.php/get?code=232425     ← esto hoy devuelve
                                                         HTTP 200 con un Fatal
                                                         error de PHP/MySQL
```

Ese endpoint de `fgcode.store` **está roto** (bug suyo, no nuestro):
`Call to a member function bind_param() on bool ... FGDbHandler.php:805`. Aun así
el código funciona, porque la app **no** usa ese endpoint: habla directamente con
la API del proveedor y manda el código como `KEY_ACTIVATED_TYPE`.

---

## 2. La cadena de llamadas

Servidor activo (descubierto capturando el tráfico real):

```
API      https://li0.highperformanceconnect.shop/api/live/livedrama/v13.0.0/
redirect https://re0.highperformanceconnect.shop/redirect/glbr
```

| Paso | Endpoint | Cuerpo extra | Devuelve |
|---|---|---|---|
| 1 | `glt` | `{"type":"tv"}` | `live_topics`: los temas (categorías) |
| 2 | `glbt` | `{"type","topic":"hot_now"}` | `live`: los canales del tema |
| 3 | `glasbi` | `{"id":"live_tv_beinsport1"}` | ficha: `url`, `agent`, `backup` |
| 4 | `glbr` | `{"id","url","agent"}` | la URL real + headers |

**Todos** los cuerpos llevan el mismo sobre:

```json
{
  "user_id": "1794966857803000_notloggedin.com_dramalive3",
  "device_id": "<uuid4>",
  "device_api": "chrome/131.0.0.0",
  "version_name": "web_241",
  "language": "en", "timezone": "UTC",
  "device_type": "phone", "os_platform": "web", "os": "android",
  "KEY_ACTIVATED_TYPE": "232425",          ← aquí viaja el FG Code
  "store": "web", "isStoreVersion": true, "isPremium": false,
  "isCoupon_active": false, "hideAds": false,
  "appCount": "{\"runCount\":1,\"adsLoaded\":1,\"adsShowed\":1,\"adsFailed\":1}",
  "mainServer": "https://main.fastconnections.online/api/live/livedrama/v13.0.0/"
}
```

No hay login, ni token, ni firma: **solo el código**. Por eso es reutilizable.

### 2.1 El cifrado (esto es lo que faltaba para hacerlo nativo)

El cuerpo va **AES-128-CBC** con clave fija embebida en la app, en este formato:

```
base64(cifrado) : base64(iv)
```

- clave: `43fc9b1a3f854049` (los 16 caracteres literalmente, **no** es base64)
- relleno: PKCS#7
- en `main.dart.js`, funciones `c0()` (cifra) y `dJ()` (descifra)

Verificado: pedí el `glt` real, descifré la respuesta y salió el JSON con los 265
temas. (Aparte existe `Salted__`/OpenSSL para el *player secret*; **no hace falta**
para la API: sirve solo para cifrar la URL dentro de `swap`/`drm`.)

---

## 3. Por qué beIN a veces no emite (dato nuevo e importante)

`glasbi` devuelve `url` **y** `backup`. Cada entrada es del estilo:

```
url -- agente -;- url -- agente -;- {json} -- double_redirect -;- ...
```

Ejemplo real de **Bein S. 1** (9 opciones):

1. `.LS.V2live_tv_custom_handler_...SD_/s` → `glbr` → ✅ emite
2. `ordernap.net/e/z7iiiknxnuqjk` … (los embeds de BStream/Cloudflare que ya
   conocemos de los pedidos anteriores)
3. `quotarevival.net/e/yxtmusy4xj8tj`
4. `daddy_91`, `LOAD_BALANCER` …
5. `primetv.cc.cd/beinfhd11/...m3u8` ← la directa que en el móvil sí emitía

Las entradas `.LS.` no son URLs: son **marcadores**. La app las manda a `glbr` y
`glbr` devuelve la URL final alojada en un dominio distinto **cada vez**
(`max6.maxcontentdataios.shop`, `sup6.superspeednet.cfd`, `spe8.speedfastnet.cfd`…),
con su `User-Agent` y `Referer` obligatorios. Si el marcador está muerto, hay que
bajar a la siguiente opción del `backup`. Eso es exactamente lo que hace la API.

---

## 4. La API

En `/home/user/dramalive-api/`:

```
drcrypto.py      AES-128-CBC (cifra/descifra)
drama_client.py  cliente: glt, glbt, glasbi, glbr + respaldos + comprobación
server.py        FastAPI con los endpoints
requirements.txt
```

Arrancar: `uvicorn server:app --host 0.0.0.0 --port 8000` · docs en `/docs`.

| Endpoint | Qué hace |
|---|---|
| `GET /salud` | estado |
| `GET /temas/{codigo}?tipo=tv\|radio` | temas de la playlist |
| `GET /canales/{codigo}/{tema}?tipo=tv` | canales del tema |
| `GET /canal/{codigo}/{id_live}` | ficha + **URL ya resuelta** (probando respaldos) |
| `GET /stream/{codigo}/{id_live}` | 302 a la URL que emite (VLC/ExoPlayer/IPTV) |
| `GET /lista/{codigo}.m3u` | playlist M3U completa (`?tema=` opcional) |
| `GET /probar/{codigo}/{id_live}` | ¿emite de verdad? |

### Resultados medidos ahora mismo (código 232425)

| Canal | Opciones | Resultado |
|---|---|---|
| Bein S. 1 | 9 | ✅ m3u8 200, segmentos `.js` que son **MPEG-TS** (95 kB) |
| Bein S. 2 | 9 | ✅ m3u8 200, segmento TS 1,07 MB |
| Bein S. 3 | 9 | ✅ m3u8 200, segmento TS 1 MB |
| 2M | 8 | ✅ emite |
| AD Sport 1 | 7 | ❌ todas las opciones muertas hoy |
| Al Aoula | 3 | ❌ todas muertas hoy |

Playlist: **265 temas**, 89 canales solo en «Most watched», y 200 temas de radio.

### Detalle fino del stream

Los segmentos **no** son `.ts` sino `.js` (`k9x_1794919732-1794924442.js`), pero el
contenido empieza por `0x47` = **MPEG-TS**. hls.js/ExoPlayer los reproducen igual
porque el manifiesto es HLS normal; si integras a mano, no filtres por extensión.

---

## 5. Lo que **no** se puede

- **Películas/series**: `movie`, `vod` y `series` devuelven **0 temas**. Este
  código es solo TV/radio; el catálogo VOD va por otra vía de la app.
- **Sin el código no hay nada**: cada FG Code es una lista distinta (265 temas el
  `232425`). No hay catálogo global.
- **Los marcadores caducan**: la URL de `glbr` cambia de dominio entre llamadas, así
  que hay que resolver *justo antes* de reproducir. La API cachea 60 s como mucho.
- **No es magia**: si el proveedor retira un canal (slate de Pluto, `451`, embeds
  de Cloudflare), seguirá sin emitir; lo único que se gana es saltar rápido al
  respaldo bueno.

## 6. Aviso

Esto es la lista privada de un tercero (contenido con derechos). La API es un
cliente técnico de la misma: no aloja ni redistribuye nada y depende del servidor
ajeno, que puede cambiar el cifrado o cerrar los endpoints cuando quiera.

---

# 7. Versión esencial con **todas** las opciones (v1.1)

Lo que pediste: que resuelva y muestre **todas** las fuentes de cada canal, no
solo la primera que emita.

## Cómo se listan todas

`glasbi` da `url` + `backup`, separados por `-;-`, con el agente tras ` -- `.
Algunas entradas son un JSON (`{"url","agent","headers"}`): se parsea con
`raw_decode` porque a veces viene con sufijo (`{...} -- double_redirect`).

`DramaClient.opciones_con_estado(ficha)`:

1. trocea y **desduplica** (dos marcadores distintos pueden acabar en la misma URL);
2. resuelve cada marcador por `glbr` y **prueba** la URL resultante;
3. en paralelo (6 hilos): en serie un canal de 9 opciones tardaba ~18 s;
4. devuelve por opción: número del proveedor, tipo, URL final, headers, si emite,
   código HTTP, milisegundos y el error si lo hubo.

Tipos que se etiquetan: `marcador` (`.LS.`), `embed` (ordernap/quotarevival),
`directa` (`.m3u8`/`.mpd`) y `otra` (stream continuo de radio).

## Medido con el código 232425

| Canal | Opciones | Emitiendo |
|---|---|---|
| Bein S. 1 | 8 | **4** |
| Bein S. 2 | 8 | **4** |
| Bein S. 3 | 7 | **3** |
| Radio (Quran FM 98.2) | 1 | 1 (MP3) |

Las que no emiten son siempre las mismas: `primetv.cc.cd` (403 fuera del embed),
`ordernap.net` y `quotarevival.net` (403) y `tossequip.net` (403).

## Por qué hay un proxy (`/p`, `/ps`)

Los segmentos del proveedor exigen el **Referer y el User-Agent** que devuelve
`glbr`; desde el navegador no se pueden poner en un `<video>`, y además hay CORS.
El proxy vuelve a pedirlos con esas cabeceras y sirve el manifiesto con los
segmentos reescritos. Verificado: segmento de 1–4 MB que empieza por `0x47`
(MPEG-TS).

Dos trampas del proveedor que el proxy resuelve:

- los segmentos se llaman **`.js`** pero son TS: no filtrar por extensión;
- la **ventana del directo rota** cada pocos segundos y la resolución cambia de
  dominio: si un segmento da 404 se vuelve a resolver y se reintenta una vez.

## Endpoints nuevos

| Endpoint | Qué hace |
|---|---|
| `GET /opciones/{codigo}/{id_live}` | **todas** las opciones, resueltas y probadas |
| `GET /p/{codigo}/{id_live}/{n}.m3u8` | manifiesto de **una** opción concreta |
| `GET /ps/{codigo}/{id_live}/{n}/{recurso}` | sus segmentos y claves |
| `GET /stream/{codigo}/{id_live}?n=2` | 302 a la opción 2 |

`{n}` es el **número que asigna el proveedor** (0,1,2…), no la posición en la
lista: la lista se reordena por velocidad y la posición cambiaría.

## La web (`/`)

- barra de código FG + interruptor **TV / Radio**;
- temas en chips, canales en rejilla;
- al abrir un canal: **todas** sus opciones con un punto verde/rojo, la URL final
  y los ms que tardó; **arranca sola** con la primera que emite;
- si una no carga en 9 s, **salta sola** a la siguiente que emita (máx. 3 saltos);
- botón «Viendo» en la activa; «Re-probar» vuelve a medir todo.
