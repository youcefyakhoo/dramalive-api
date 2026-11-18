"""Cliente de Drama Live (FastConnections API v13.0.0) — ASÍ FUNCIONA, paso a paso.

Flujo real, verificado contra el servidor:
  1. La web es Flutter (web.dramalive.cc). Trae la config del servidor (gs), que
     incluye  server_url / live_url (= .../livedrama/v13.0.0/).
  2. El usuario mete un "FG Code". Ese código viaja como KEY_ACTIVATED_TYPE en
     TODAS las peticiones; es la playlist privada que alguien creó en fgcode.store.
  3. glt  {type:"tv"}                -> temas (categorías) de la playlist
     glbt {type:"tv", topic:"hot_now"}-> canales del tema (id_live, name, url, agent)
     glasbi {id:"live_tv_xxx"}        -> ficha del canal: url + backup (marcadores .LS.)
  4. Si la url es un marcador ".LS.V2...", la app abre el reproductor del proveedor
     (player/v3/player.html) y éste llama a  re0.../redirect/glbr  con
     {id, url, agent}, que devuelve la URL real a reproducir + los headers.
  5. Todo cuerpo va cifrado AES-128-CBC, clave "43fc9b1a3f854049",
     formato base64(ct):base64(iv).

Smoke test:  python3 drama_client.py 232425
"""
from __future__ import annotations

import json
import uuid

import requests

import drcrypto

API_BASE = "https://li0.highperformanceconnect.shop/api/live/livedrama/v13.0.0/"
API_REDIRECT = "https://re0.highperformanceconnect.shop/redirect/glbr"
MAIN_SERVER = "https://main.fastconnections.online/api/live/livedrama/v13.0.0/"
UA = ("Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36")


class DramaClient:
    def __init__(self, fgcode: str, base: str = API_BASE, timeout: int = 20):
        self.fgcode = fgcode.strip()
        self.base = base if base.endswith("/") else base + "/"
        self.timeout = timeout
        self.device_id = str(uuid.uuid4())
        self.user_id = f"{_now_ms()}_notloggedin.com_dramalive3"
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Content-Type": "text/plain;charset=UTF-8"})

    # ---------- infraestructura ----------
    def _payload(self, extra: dict) -> dict:
        """El sobre que exige el servidor: metadatos del 'dispositivo' + el FG Code."""
        base = {
            "user_id": self.user_id,
            "device_id": self.device_id,
            "device_api": "chrome/131.0.0.0",
            "version_name": "web_241",
            "language": "en",
            "timezone": "UTC",
            "device_type": "phone",
            "os_platform": "web",
            "os": "android",
            "KEY_ACTIVATED_TYPE": self.fgcode,
            "store": "web",
            "isStoreVersion": True,
            "isPremium": False,
            "isCoupon_active": False,
            "hideAds": False,
            "appCount": json.dumps({"runCount": 1, "adsLoaded": 1, "adsShowed": 1, "adsFailed": 1}),
            "mainServer": MAIN_SERVER,
        }
        base.update(extra)
        return base

    def _post(self, url: str, extra: dict) -> dict:
        body = drcrypto.encrypt(json.dumps(self._payload(extra), ensure_ascii=False))
        r = self.s.post(url, data=body.encode(), timeout=self.timeout)
        r.raise_for_status()
        txt = r.text.strip()
        if not txt:
            return {"result": 1, "error": "respuesta vacía"}
        if ":" not in txt:
            # el servidor a veces responde HTML de error (p.ej. 403/451)
            return {"result": 1, "error": txt[:200]}
        return json.loads(drcrypto.decrypt(txt))

    # ---------- endpoints ----------
    def temas(self, tipo: str = "tv") -> list[dict]:
        r = self._post(self.base + "glt", {"type": tipo})
        return r.get("live_topics") or []

    def canales(self, topic: str, tipo: str = "tv") -> list[dict]:
        r = self._post(self.base + "glbt", {"type": tipo, "topic": topic})
        return r.get("live") or []

    def canal(self, id_live: str) -> dict | None:
        r = self._post(self.base + "glasbi", {"id": id_live})
        return r.get("live") or None

    def resolver(self, id_live: str, url: str, agent: str) -> dict:
        """Marcador .LS. -> URL real. Devuelve {url, agent, mediatype, headers...}."""
        r = self._post(API_REDIRECT, {"id": id_live, "url": url, "agent": agent})
        data = (r.get("data") or {}).get("url") or ""
        if not data:
            return {"ok": False, "raw": r}
        try:
            info = json.loads(data)
        except json.JSONDecodeError:
            info = {"url": data, "agent": agent}
        info["ok"] = bool(info.get("url"))
        return info

    @staticmethod
    def opciones(ficha: dict) -> list[dict]:
        """Trocea `url` + `backup` en opciones jugables.

        Formato del proveedor:  "url -- agente -;- url -- agente -;- ..."
        A veces la opción es un JSON {"url","agent","iframe","headers"}.
        """
        trozos = [ficha.get("url") or ""]
        trozos += (ficha.get("backup") or "").split("-;-")
        salida = []
        for crudo in trozos:
            crudo = crudo.strip()
            if not crudo:
                continue
            if crudo.startswith("{"):
                # el JSON puede venir con sufijo: {"url":...} -- double_redirect
                dec = json.JSONDecoder()
                try:
                    j, _fin = dec.raw_decode(crudo)
                    salida.append({"url": (j.get("url") or "").strip(),
                                   "agent": j.get("agent", ""),
                                   "headers": j.get("headers") or {}, "json": j})
                    continue
                except json.JSONDecodeError:
                    pass
            partes = [p.strip() for p in crudo.split(" -- ")]
            if partes and partes[0]:
                salida.append({"url": partes[0],
                               "agent": partes[1] if len(partes) > 1 else "redirect",
                               "headers": {}})
        return salida

    def resolver_con_respaldo(self, ficha: dict, probar: bool = True) -> dict:
        """Prueba la principal y, si no emite, las de respaldo. Devuelve la que va."""
        for i, op in enumerate(self.opciones(ficha)):
            if op["url"].startswith(("http://.LS.", "http://LS.")):
                r = self.resolver(ficha["id_live"], op["url"], op.get("agent") or "redirect")
            else:
                r = {"ok": bool(op["url"]), "url": op["url"],
                     "agent": op.get("agent"), "headers": op.get("headers")}
            if not r.get("ok") or not r.get("url"):
                continue
            if probar and not self.probar_stream(r["url"], r.get("headers")).get("ok"):
                continue
            r["intento"] = i
            return r
        return {"ok": False, "url": ""}

    # ---------- todas las opciones de un canal ----------
    @staticmethod
    def _tipo(op: dict) -> str:
        u = op.get("url", "")
        if u.startswith(("http://.LS.", "http://LS.", ".LS.")):
            return "marcador"
        if "ordernap" in u or "quotarevival" in u or "/e/" in u:
            return "embed"
        if u.endswith((".m3u8", ".mpd")) or ".m3u8?" in u or ".mpd?" in u:
            return "directa"
        if u.endswith((".html", "/")):
            return "pagina"
        return "otra"

    def opciones_con_estado(self, ficha: dict, timeout: int = 10) -> list[dict]:
        """Resuelve TODAS las opciones del canal y dice cuáles emiten.

        Devuelve una lista (en el orden del proveedor) con: tipo, origen, url
        final, headers, si emite, cuánto tardó y el error si lo hubo.
        """
        from concurrent.futures import ThreadPoolExecutor

        ops, vistos = [], set()
        for i, op in enumerate(self.opciones(ficha)):
            u = (op.get("url") or "").strip()
            if not u or u in vistos:
                continue
            vistos.add(u)
            ops.append({"n": i, **op})

        def trabajo(op):
            import time
            t0 = time.time()
            fila = {
                "n": op["n"],
                "tipo": self._tipo(op),
                "origen": op["url"],
                "url": "",
                "headers": op.get("headers") or {},
                "agent": op.get("agent") or "",
                "mediatype": "",
                "emite": False,
                "hls": False,
                "content_type": "",
                "http": None,
                "ms": 0,
                "error": "",
            }
            try:
                if fila["tipo"] == "marcador":
                    r = self.resolver(ficha["id_live"], op["url"], op.get("agent") or "redirect")
                    if not r.get("ok"):
                        fila["error"] = "el marcador no resuelve (muerto)"
                        fila["ms"] = int((time.time() - t0) * 1000)
                        return fila
                    fila["url"] = r.get("url", "")
                    fila["headers"] = r.get("headers") or fila["headers"]
                    fila["agent"] = r.get("agent") or fila["agent"]
                    fila["mediatype"] = r.get("mediatype") or ""
                else:
                    fila["url"] = op["url"]
                p = self.probar_stream(fila["url"], fila["headers"], timeout=timeout)
                fila["emite"] = bool(p.get("ok"))
                fila["hls"] = bool(p.get("hls"))
                fila["content_type"] = p.get("content_type") or ""
                fila["http"] = p.get("status")
                if not p.get("ok"):
                    fila["error"] = p.get("error") or f"HTTP {p.get('status')}"
            except Exception as e:  # noqa: BLE001
                fila["error"] = str(e)[:120]
            fila["ms"] = int((time.time() - t0) * 1000)
            return fila

        # en paralelo: 9 opciones x ~2 s en serie serían 18 s por canal
        with ThreadPoolExecutor(max_workers=6) as ex:
            filas = list(ex.map(trabajo, ops))
        # dos marcadores distintos pueden acabar en la misma URL: se queda el más rápido
        unicas, por_url = [], {}
        for f in filas:
            clave = f["url"] or f"origen:{f['origen']}"
            if clave in por_url:
                por_url[clave]["repetida_en"].append(f["n"])
                continue
            f["repetida_en"] = []
            por_url[clave] = f
            unicas.append(f)
        unicas.sort(key=lambda f: (not f["emite"], f["ms"]))
        return unicas

    def probar_stream(self, url: str, headers: dict | None = None, timeout: int = 12) -> dict:
        """¿La URL emite de verdad?

        Sirve para HLS (manifiesto con #EXTM3U) y para streams continuos de radio
        (RadioJar y similares), que no terminan nunca: se leen solo los primeros
        KB y se corta, si no la petición se queda colgada para siempre.
        """
        h = {"User-Agent": UA}
        h.update(headers or {})
        try:
            r = self.s.get(url, headers=h, timeout=(6, timeout), stream=True)
            tipo = (r.headers.get("Content-Type") or "").lower()
            buf = b""
            if r.status_code == 200:
                for trozo in r.iter_content(4096):
                    buf += trozo
                    if len(buf) > 65536:
                        break
                    if b"#EXTM3U" in buf:
                        break
            r.close()
            txt = buf.decode("utf-8", "replace")
            es_hls = "#EXTM3U" in txt
            es_medio = tipo.startswith(("audio/", "video/", "application/vnd.apple.mpegurl",
                                        "application/x-mpegurl", "application/octet-stream"))
            vivo = r.status_code == 200 and (es_hls or (es_medio and len(buf) > 0))
            return {"ok": vivo, "status": r.status_code, "hls": es_hls,
                    "content_type": tipo, "primeras": txt.splitlines()[:4]}
        except requests.RequestException as e:
            return {"ok": False, "error": str(e)[:150]}


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


if __name__ == "__main__":
    import sys

    codigo = sys.argv[1] if len(sys.argv) > 1 else "232425"
    c = DramaClient(codigo)
    temas = c.temas()
    print(f"FG Code {codigo}: {len(temas)} temas -> {[t['id_topic'] for t in temas][:6]}")
    if not temas:
        sys.exit(1)
    ch = c.canales(temas[0]["id_topic"])
    print(f"Tema {temas[0]['id_topic']}: {len(ch)} canales")
    for x in ch[:5]:
        print(f"   {x['id_live']:<28} {x['name'][:24]:<26} agent={x['agent']}")
    if ch:
        ficha = c.canal(ch[0]["id_live"])
        print("\nFicha del primero:")
        print("  url   :", (ficha or {}).get("url", "")[:110])
        print("  backup:", ((ficha or {}).get("backup", "") or "")[:110])
        if ficha and ficha.get("url", "").startswith("http://.LS."):
            res = c.resolver(ficha["id_live"], ficha["url"], ficha.get("agent", "redirect"))
            print("  glbr  :", res.get("url", "")[:110], "| agent:", str(res.get("agent"))[:40])
            if res.get("url"):
                print("  prueba:", c.probar_stream(res["url"], res.get("headers")))
