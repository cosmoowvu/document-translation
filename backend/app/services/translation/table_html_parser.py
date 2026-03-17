"""
HTML Table Parser Module
Parses HTML table strings to extract cell text content.
"""
from html.parser import HTMLParser


class HTMLTableParser(HTMLParser):
    """Parse HTML table and extract cell text contents in document order."""

    def __init__(self):
        super().__init__()
        self.in_td = False
        self.current_cell = []
        self.cells = []

    def handle_starttag(self, tag, attrs):
        if tag in ('td', 'th'):
            self.in_td = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.in_td = False
            self.cells.append(''.join(self.current_cell))

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)
