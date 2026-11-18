"""API REST sobre Drama Live (playlists FG Code) — FastAPI.

Arranca:   uvicorn server:app --host 0.0.0.0 --port 8000
Docs:      http://localhost:8000/docs

Endpoints
  GET /salud                              -> estado
  GET /temas/{codigo}                     -> temas (categorías) de la playlist
  GET /canales/{codigo}/{tema}            -> canales del tema
  GET /canal/{codigo}/{id_live}           -> ficha + URL final ya resuelta
  GET /stream/{codigo}/{id_live}          -> 302 a la URL que emite (para reproductores)
  GET /lista/{codigo}.m3u                 -> playlist M3U con TODOS los canales
  GET /probar/{codigo}/{id_live}          -> ¿emite? (descarga el primer segmento)
"""
from __future__ import annotations

import asyncio
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, PlainTextResponse, RedirectResponse,
                               Response, StreamingResponse)

import drama_client as dc

app = FastAPI(
    title="Drama Live API",
    description="Playlists FG Code de Drama Live (tv + radio). Cadena: glt -> glbt -> glasbi -> glbr.",
    version="1.1.0",
)

# la web puede estar en otro dominio (ej. Cloudflare Pages) consumiendo esta API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

import os
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# caché en memoria: cada glbr tarda ~0,5-2 s y los marcadores caducan, así que se
# guarda poco tiempo (60 s) para no servir una URL muerta.
_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(k: str, ttl: float = 60) -> Any | None:
    import time
    v = _cache.get(k)
    if not v:
        return None
    ts, val = v
    if time.time() - ts > ttl:
        _cache.pop(k, None)
        return None
    return val


def _cache_set(k: str, val: Any) -> None:
    import time
    _cache[k] = (time.time(), val)


def cliente(codigo: str) -> dc.DramaClient:
    codigo = (codigo or "").strip()
    if not codigo.isalnum() or len(codigo) > 32:
        raise HTTPException(400, "código FG inválido")
    return dc.DramaClient(codigo)


def _sync(fn, *a, **kw):
    return asyncio.to_thread(fn, *a, **kw)


@app.get("/salud")
async def salud():
    return {"ok": True, "servicio": "dramalive", "version": app.version}


@app.get("/temas/{codigo}")
async def temas(codigo: str, tipo: str = Query("tv", pattern="^(tv|radio)$")):
    c = cliente(codigo)
    k = f"temas:{codigo}:{tipo}"
    if (v := _cache_get(k)) is not None:
        return v
    try:
        t = await _sync(c.temas, tipo)
    except Exception as e:
        raise HTTPException(502, f"el servidor de Drama Live no respondió: {e}")
    if not t:
        raise HTTPException(404, "código sin temas (¿existe la playlist?)")
    out = {"codigo": codigo, "tipo": tipo, "total": len(t), "temas": t}
    _cache_set(k, out)
    return out


@app.get("/canales/{codigo}/{tema}")
async def canales(codigo: str, tema: str, tipo: str = Query("tv", pattern="^(tv|radio)$")):
    c = cliente(codigo)
    k = f"canales:{codigo}:{tema}:{tipo}"
    if (v := _cache_get(k, 120)) is not None:
        return v
    try:
        ch = await _sync(c.canales, tema, tipo)
    except Exception as e:
        raise HTTPException(502, f"el servidor de Drama Live no respondió: {e}")
    out = {"codigo": codigo, "tema": tema, "total": len(ch), "canales": ch}
    _cache_set(k, out)
    return out


@app.get("/canal/{codigo}/{id_live}")
async def canal(codigo: str, id_live: str):
    """Ficha del canal y, si es un marcador .LS., la URL final ya resuelta."""
    c = cliente(codigo)
    k = f"canal:{codigo}:{id_live}"
    if (v := _cache_get(k)) is not None:
        return v
    try:
        ficha = await _sync(c.canal, id_live)
    except Exception as e:
        raise HTTPException(502, f"el servidor de Drama Live no respondió: {e}")
    if not ficha:
        raise HTTPException(404, "canal no encontrado en esta playlist")
    out = {"codigo": codigo, "canal": ficha, "resuelto": None}
    try:
        # recorre principal + respaldos y devuelve la primera que emite
        out["resuelto"] = await _sync(c.resolver_con_respaldo, ficha, True)
    except Exception as e:
        out["error_resolucion"] = str(e)[:200]
    _cache_set(k, out)
    return out


@app.get("/stream/{codigo}/{id_live}")
async def stream(codigo: str, id_live: str, n: int = Query(0, ge=0)):
    """Redirección directa a la URL de la opción n. Útil para VLC, ExoPlayer, IPTV."""
    fuente = await _fuente(codigo, id_live, n)
    return RedirectResponse(fuente["url"], status_code=302)


@app.get("/probar/{codigo}/{id_live}")
async def probar(codigo: str, id_live: str):
    d = await canal(codigo, id_live)
    r = d.get("resuelto") or {}
    if not r.get("url"):
        return {"emite": False, "motivo": "sin URL resuelta"}
    c = cliente(codigo)
    p = await _sync(c.probar_stream, r["url"], r.get("headers"))
    return {"canal": id_live, "url": r["url"], "emite": p.get("ok", False), "detalle": p}


@app.get("/opciones/{codigo}/{id_live}")
async def opciones(codigo: str, id_live: str):
    """TODAS las opciones del canal, resueltas y probadas (no solo la primera)."""
    c = cliente(codigo)
    k = f"ops:{codigo}:{id_live}"
    if (v := _cache_get(k, 180)) is not None:
        return v
    try:
        ficha = await _sync(c.canal, id_live)
    except Exception as e:
        raise HTTPException(502, f"el servidor de Drama Live no respondió: {e}")
    if not ficha:
        raise HTTPException(404, "canal no encontrado en esta playlist")
    filas = await _sync(c.opciones_con_estado, ficha)
    out = {
        "codigo": codigo,
        "canal": {k2: ficha.get(k2) for k2 in ("id_live", "name", "img_url", "id_topic")},
        "total": len(filas),
        "emitiendo": sum(1 for f in filas if f["emite"]),
        "opciones": filas,
    }
    _cache_set(k, out)
    return out


@app.api_route("/p/{codigo}/{id_live}.m3u8", methods=["GET", "HEAD"])
@app.api_route("/p/{codigo}/{id_live}/{n}.m3u8", methods=["GET", "HEAD"])
async def proxy_playlist(codigo: str, id_live: str, n: int = 0):
    """Manifiesto HLS de UNA opción concreta del canal, con segmentos reescritos."""
    fuente = await _fuente(codigo, id_live, n)
    return await _manifiesto(codigo, id_live, n, fuente)


@app.api_route("/ps/{codigo}/{id_live}/{n}/{recurso:path}", methods=["GET", "HEAD"])
async def proxy_segmento(codigo: str, id_live: str, n: int, recurso: str):
    """Segmentos/claves desde el servidor del canal (evita CORS y Referer obligatorio).

    La ventana del directo rota cada pocos segundos y el host cambia de nombre en
    cada resolución: si el segmento ya no existe se reintenta con la URL recién
    resuelta antes de darlo por perdido.
    """
    up, fuente, destino = None, None, ""
    for intento in range(2):
        if intento:
            # refrescar la resolución (el proveedor cambia de dominio a cada rato)
            _cache.pop(f"ops:{codigo}:{id_live}", None)
            _cache.pop(f"canal:{codigo}:{id_live}", None)
        fuente = await _fuente(codigo, id_live, n)
        destino = _destino(fuente["url"], recurso)
        h = {"User-Agent": dc.UA}
        h.update(fuente.get("headers") or {})
        try:
            up = requests.get(destino, headers=h, timeout=20, stream=True)
            if up.status_code == 200:
                break
        except requests.RequestException:
            up = None
    if up is None:
        raise HTTPException(502, "el servidor del canal no responde")
    if up.status_code != 200:
        raise HTTPException(504, "segmento caducado: la ventana del directo rotó")
    tipo = up.headers.get("Content-Type", "application/octet-stream")
    if recurso.endswith((".js", ".ts", ".m4s")):
        tipo = "video/mp2t"
    def trozos():
        try:
            for chunk in up.iter_content(65536):
                yield chunk
        except requests.RequestException:
            return      # el navegador cortó o el host tardó: no es un error del servidor
    return StreamingResponse(trozos(), status_code=up.status_code, media_type=tipo)


def _destino(base: str, recurso: str) -> str:
    """Reconstruye la URL absoluta del recurso a partir del manifiesto vigente."""
    from urllib.parse import urljoin
    if recurso.startswith("abs/"):
        return recurso[4:]
    if recurso.startswith("http"):
        return recurso
    return urljoin(base, recurso)


async def _fuente(codigo: str, id_live: str, n: int) -> dict:
    """URL final + headers de la opción n del canal (0 = la primera que emite)."""
    d = await opciones(codigo, id_live)
    ops = d.get("opciones") or []
    if not ops:
        raise HTTPException(404, "el canal no tiene opciones")
    # `n` es el número que da el proveedor: NO cambia aunque la lista se reordene
    op = next((o for o in ops if o.get("n") == n), None)
    if op is None and 0 <= n < len(ops):
        op = ops[n]
    if op is None:
        raise HTTPException(404, f"la opción {n} no existe")
    if not op.get("url"):
        raise HTTPException(404, "esa opción no resuelve")
    return {"url": op["url"], "headers": op.get("headers") or {}, "hls": op.get("hls")}


async def _manifiesto(codigo: str, id_live: str, n: int, fuente: dict):
    h = {"User-Agent": dc.UA}
    h.update(fuente.get("headers") or {})
    try:
        up = requests.get(fuente["url"], headers=h, timeout=20)
    except requests.RequestException as e:
        raise HTTPException(502, f"el servidor del canal no responde: {e}")
    texto = up.text
    if "#EXTM3U" not in texto:
        raise HTTPException(502, "esa opción no es un manifiesto HLS (usa su URL directa)")
    from urllib.parse import urlparse
    import re as _re
    base = fuente["url"]
    salida = []
    for linea in texto.splitlines():
        l = linea.strip()
        if not l:
            continue
        if l.startswith("#"):
            if "URI=" in l:
                l = _re.sub(r'URI="([^"]+)"',
                            lambda m: 'URI="/ps/%s/%s/%d/%s"' % (codigo, id_live, n, _rel(base, m.group(1))), l)
            salida.append(l)
            continue
        salida.append("/ps/%s/%s/%d/%s" % (codigo, id_live, n, _rel(base, l)))
    return PlainTextResponse("\n".join(salida) + "\n",
                             media_type="application/vnd.apple.mpegurl")


def _rel(base: str, destino: str) -> str:
    """Ruta relativa al directorio del manifiesto; si es otro host, va marcada."""
    from urllib.parse import urlparse
    b = urlparse(base)
    d = urlparse(destino)
    if d.netloc and d.netloc != b.netloc:
        return "abs/" + destino
    ruta = d.path.lstrip("/")
    carpeta = b.path.rsplit("/", 1)[0].lstrip("/")
    if carpeta and ruta.startswith(carpeta + "/"):
        ruta = ruta[len(carpeta) + 1:]
    return ruta + (("?" + d.query) if d.query else "")


@app.get("/", include_in_schema=False)
async def portada():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/static/hls.min.js", include_in_schema=False)
async def hlsjs():
    return FileResponse(os.path.join(STATIC, "hls.min.js"), media_type="application/javascript")


@app.get("/lista/{codigo}.m3u", response_class=PlainTextResponse)
async def lista(codigo: str, tipo: str = Query("tv", pattern="^(tv|radio)$"), tema: str | None = None):
    """Playlist M3U: cada canal apunta a /stream/... (la resolución se hace al abrir)."""
    c = cliente(codigo)
    try:
        temas_ = await _sync(c.temas, tipo)
    except Exception as e:
        raise HTTPException(502, f"el servidor de Drama Live no respondió: {e}")
    if not temas_:
        raise HTTPException(404, "código sin temas")
    objetivos = [t["id_topic"] for t in temas_] if not tema else [tema]
    lineas = ["#EXTM3U", f"#PLAYLIST Drama Live {codigo}"]
    for tp in objetivos:
        try:
            chs = await _sync(c.canales, tp, tipo)
        except Exception:
            continue
        for x in chs:
            logo = x.get("img_url") or ""
            lineas.append(f'#EXTINF:-1 tvg-id="{x.get("id_live","")}" tvg-logo="{logo}" '
                          f'group-title="{tp}",{x.get("name","")}')
            lineas.append(f"/stream/{codigo}/{x.get('id_live','')}")
    return "\n".join(lineas) + "\n"
