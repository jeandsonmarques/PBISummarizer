
# Helper para aplicar o CSS/typografia Montserrat dentro do HTML renderizado em QTextBrowser
def apply_result_style(html: str) -> str:
    base = """
    <style>
    @font-face {
      font-family: 'MontserratCustom';
      src: url('resources/fonts/Montserrat/Montserrat-Regular.ttf');
    }
    body { font-family: 'MontserratCustom','Montserrat','Open Sans','Segoe UI',Arial,sans-serif;
           color:#2E3A59; background-color:#F8F9FB; font-size:11pt; margin:0; padding:0.2em 0.4em; }
    h1,h2,h3 { color:#153C8A; font-weight:600; }
    .section-title { color:#20C2A0; font-weight:600; margin-top:0.6em; }
    ul { margin:0.2em 0 0.2em 1.1em; padding:0; }
    .group { background:#ffffff; padding:8px; margin:6px 0; border-radius:0px;
             box-shadow:0 1px 2px rgba(46,58,89,0.04); }
    table { border-collapse: collapse; width: 100%; }
    th, td { padding: 6px 8px; border-bottom: 1px solid #E6EEF2; text-align: left; }
    th { color: #153C8A; font-weight:600; }
    </style>
    """
    return base + html
