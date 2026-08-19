#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script pour corriger l'encodage de tous les fichiers sources (py, html, css, js, txt...)
dans tout le projet, en les convertissant en UTF-8 sans BOM.
"""

import os
import sys
from pathlib import Path

# Extensions à traiter
EXTENSIONS = ('.py', '.html', '.htm', '.txt', '.css', '.js', '.xml', '.json', '.yaml', '.yml', '.ini', '.cfg', '.conf')

# Dossiers à ignorer (ne pas parcourir)
IGNORE_DIRS = {'.git', '__pycache__', 'venv', 'env', 'node_modules', 'staticfiles', 'media', 'migrations', '.idea', '.vscode'}

def detect_encoding(filepath):
    """Tente de détecter l'encodage d'un fichier."""
    encodings = ['utf-8', 'windows-1252', 'latin-1', 'cp1252', 'iso-8859-1']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                f.read()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None

def convert_to_utf8(filepath):
    """Convertit un fichier en UTF-8 sans BOM."""
    encoding = detect_encoding(filepath)
    if encoding is None:
        print(f"❌ Impossible de détecter l'encodage pour {filepath}")
        return False
    if encoding == 'utf-8':
        # Déjà UTF-8, on ne fait rien
        return False
    try:
        with open(filepath, 'r', encoding=encoding) as f:
            content = f.read()
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        print(f"✅ Converti : {filepath} (était en {encoding})")
        return True
    except Exception as e:
        print(f"❌ Erreur sur {filepath} : {e}")
        return False

def main():
    """Parcourt récursivement le répertoire courant et convertit les fichiers."""
    root_dir = Path('.')
    modified = 0
    total = 0

    for root, dirs, files in os.walk(root_dir):
        # Filtrer les dossiers à ignorer
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for file in files:
            if file.endswith(EXTENSIONS):
                filepath = Path(root) / file
                total += 1
                if convert_to_utf8(filepath):
                    modified += 1

    print(f"\n✅ {modified} fichier(s) converti(s) en UTF-8 sur {total} fichier(s) traités.")

if __name__ == '__main__':
    main()