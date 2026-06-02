"""ARI-OS local web monitor — System 7 styled dashboard.

`python3 -m ari_os.tools.monitor` serves http://localhost:7777, reading
~/.ari-os state and rendering a classic Mac OS 7 control panel. Stdlib only.
"""
from __future__ import annotations
import html as _html
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from . import state as _state

PORT = 7777
DEFAULT_THEME = "beige"

# Both themes share the System 7 stipple style (a 4px dot pattern over a
# vertical gradient); only the palette differs. `stipple` is the aris-space
# wallpaper. Selected via $ARI_OS_MONITOR_THEME or the control panel.
THEMES = {
    "beige": ("radial-gradient(circle at 0 0,rgba(255,255,255,0.4) 1px,transparent 1.5px),"
              "linear-gradient(180deg,#D6D2C4 0%,#C9C4B8 100%)"),
    "stipple": ("radial-gradient(circle at 0 0,rgba(255,255,255,0.5) 1px,transparent 1.5px),"
                "linear-gradient(180deg,#C8A8E9 0%,#F2B8DC 100%)"),
}


def current_theme() -> str:
    t = os.environ.get("ARI_OS_MONITOR_THEME", DEFAULT_THEME)
    return t if t in THEMES else DEFAULT_THEME


def body_background(theme: str) -> str:
    img = THEMES.get(theme, THEMES[DEFAULT_THEME])
    # Pin to the viewport so the fill gradient never tiles below short content;
    # only the 4px stipple repeats.
    return (f"background-image:{img};background-size:4px 4px,100% 100%;"
            f"background-repeat:repeat,no-repeat;background-attachment:fixed;")


_CSS = """
body{font-family:Chicago,'ChicagoFLF',system-ui,sans-serif;
  color:#000;margin:0;padding:24px;min-height:100vh;box-sizing:border-box;}
.window{background:#fff;border:2px solid #000;box-shadow:2px 2px 0 #000;
  max-width:560px;margin:0 auto;}
.title-bar{background:repeating-linear-gradient(#000 0 1px,#fff 1px 2px);
  border-bottom:2px solid #000;padding:3px 8px;display:flex;align-items:center;}
.title-bar .name{background:#fff;padding:0 8px;font-weight:bold;}
.body{padding:12px;}
.row{display:flex;justify-content:space-between;border:1px solid #000;
  padding:6px 8px;margin:4px 0;background:#fff;}
.s-running{font-weight:bold;}
.s-blocked{background:#000;color:#fff;}
.s-done{color:#555;}
.q{border:2px solid #000;background:#fff;padding:8px;margin-top:8px;}
.picker{position:fixed;top:12px;right:12px;background:#fff;border:2px solid #000;
  box-shadow:2px 2px 0 #000;padding:4px 8px;font-size:12px;font-weight:bold;}
.picker input{vertical-align:middle;margin-left:6px;}
"""

# Client-side gradient picker: recolors the dithered wallpaper from a chosen
# hue and remembers it in localStorage (survives the 3s auto-refresh).
_PICKER = """
<div class="picker">BG<input type="color" id="bg" value="#C8A8E9"></div>
<script>
(function(){
  function lighten(hex,amt){
    var n=parseInt(hex.slice(1),16),r=n>>16&255,g=n>>8&255,b=n&255;
    r=Math.round(r+(255-r)*amt);g=Math.round(g+(255-g)*amt);b=Math.round(b+(255-b)*amt);
    return '#'+((1<<24)+(r<<16)+(g<<8)+b).toString(16).slice(1);
  }
  function apply(hex){
    document.body.style.backgroundImage=
      'radial-gradient(circle at 0 0,rgba(255,255,255,0.5) 1px,transparent 1.5px),'+
      'linear-gradient(180deg,'+lighten(hex,0.35)+' 0%,'+hex+' 100%)';
    document.body.style.backgroundSize='4px 4px,100% 100%';
    document.body.style.backgroundRepeat='repeat,no-repeat';
    document.body.style.backgroundAttachment='fixed';
  }
  var input=document.getElementById('bg');
  var saved=localStorage.getItem('ariosBg');
  if(saved){input.value=saved;apply(saved);}
  input.addEventListener('input',function(){
    localStorage.setItem('ariosBg',input.value);apply(input.value);});
})();
</script>
"""


def load_state() -> dict:
    qdir = _state.state_dir() / "questions"
    return {"workers": _state.reconcile(),
            "questions": [p.stem for p in sorted(qdir.glob("*.md"))]}


def render_html(state: dict, theme: str | None = None) -> str:
    theme = theme if theme in THEMES else current_theme()
    rows = []
    for w in state.get("workers", []):
        st_raw = w.get("status", "?")
        st_class = st_raw if st_raw in {"running", "blocked", "done"} else "unknown"
        label = _html.escape(w.get("label", ""), quote=True)
        st = _html.escape(st_raw, quote=True)
        rows.append(
            f'<div class="row s-{st_class}"><span>{label}</span>'
            f'<span>{st}</span></div>')
    body = "".join(rows) or '<div class="row"><span>no workers</span></div>'
    qs = state.get("questions", [])
    qhtml = ""
    if qs:
        items = "".join(
            f"<div>&#x26A0; {_html.escape(q, quote=True)} needs an answer</div>"
            for q in qs)
        qhtml = f'<div class="q"><b>Questions</b>{items}</div>'
    return (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<meta http-equiv='refresh' content='3'>"
            f"<title>ARI-OS</title><style>{_CSS}\nbody{{{body_background(theme)}}}</style>"
            f"</head><body>"
            f"<div class='window'><div class='title-bar'>"
            f"<span class='name'>ARI-OS Monitor</span></div>"
            f"<div class='body'>{body}{qhtml}</div></div>{_PICKER}</body></html>")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        html = render_html(load_state()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *a):
        pass


def main() -> None:
    srv = HTTPServer(("127.0.0.1", PORT), _Handler)
    print(f"Monitor live at http://localhost:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
