#!/usr/bin/env python3
"""Servidor estatico local para desenvolvimento.

Igual ao `python3 -m http.server`, mas desliga cache do navegador
(Cache-Control: no-store) em todo arquivo. Sem isso, o Chrome mantém CSS
e imagens antigos mesmo depois de um hard refresh, porque o servidor
padrao nao manda header nenhum de cache e o navegador aplica cache
heuristico por conta propria.
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import sys

PORTA = int(sys.argv[1]) if len(sys.argv) > 1 else 4173


class SemCache(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORTA), SemCache).serve_forever()
