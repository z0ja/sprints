import re
import os
import sys
import argparse
import pymupdf
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

PDFS_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../pdfs")
XML_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../xmls")
TXT_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../txts")

INSTITUTION_RE = re.compile(
    r'universit|institu|laborator|\blab\b|cnrs|école|polytechn|research|'
    r'department|dept\.|faculty|grenoble|montréal|avignon|marseille|rennes|'
    r'vannes|upf|unam|iula|dtic|lia\b|cnrs|ea\s*\d+|umr\s*\d+|cp\s*\d+|'
    r'communicated by|^\d{4,5}|^bp\d|\bInc\b|\bCorp\b|\bLtd\b|\bLLC\b',
    re.IGNORECASE,
)

SKIP_LINE_RE = re.compile(
    r'^arXiv|^\d{4}\.\d+|^v\d+\s|^preprint|^\s*$|^\d+$|^LETTER$|'
    r'^Communicated|^\[.*\]$',
    re.IGNORECASE,
)

NUMBERED_AUTHOR_RE = re.compile(r'^\d+(?:st|nd|rd|th)\s+([A-ZÀ-Ö].+)')
ENDS_WITH_PREP_RE = re.compile(
    r'\b(a|an|the|in|of|for|on|with|by|to|from|and|at)\s*$', re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Extraction des métadonnées directement depuis le PDF via pymupdf
# ---------------------------------------------------------------------------

def extract_pdf_metadata(pdf_path):
    """Retourne (title, authors_raw, txt_content) extraits directement du PDF."""
    try:
        doc = pymupdf.open(pdf_path)
        meta = doc.metadata

        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        txt_content = "\n".join(pages_text)

        doc.close()
    except Exception as e:
        print(f"[WARN] pymupdf ne peut pas lire {pdf_path} : {e}")
        return "", "", ""

    title_raw = (meta.get("title") or "").strip()
    author_raw = (meta.get("author") or "").strip()

    if "/" in title_raw or title_raw.startswith("\\"):
        title_raw = ""

    if "@" in author_raw:
        author_raw = ""

    return title_raw, author_raw, txt_content


def list_articles(pdfs_dir):
    """Parcourt pdfs_dir pour trouver les PDF et retourne une liste de dicts article."""
    articles = []
    for fname in sorted(os.listdir(pdfs_dir)):
        if not fname.lower().endswith(".pdf"):
            continue
        pdf_path = os.path.join(pdfs_dir, fname)
        title, authors_raw, txt_content = extract_pdf_metadata(pdf_path)
        articles.append({
            "filename": fname,
            "title": title,
            "authors_raw": authors_raw,
            "txt_content": txt_content,
        })
    return articles


# ---------------------------------------------------------------------------
# Extraction des emails
# ---------------------------------------------------------------------------

def expand_emails(text):
    emails = []

    for m in re.finditer(r'\{([^}]+)\}@([\w.\-]+)', text):
        domain = m.group(2)
        for name in m.group(1).split(","):
            name = name.strip()
            if name:
                emails.append(f"{name}@{domain}")

    for m in re.finditer(r'\(([^)]+)\)\s*\n?@([\w.\-]+)', text):
        domain = m.group(2)
        for name in m.group(1).split(","):
            name = name.strip()
            if name and ("." in name or "-" in name):
                emails.append(f"{name}@{domain}")

    bad_domains = {"diskserver.castanet.com", "next.castanet.com"}
    for m in re.finditer(r'[\w.\-]+@[\w.\-]+\.\w+', text):
        email = m.group(0).strip("().,;")
        domain = email.split("@", 1)[1] if "@" in email else ""
        if domain not in bad_domains:
            emails.append(email)

    seen = set()
    result = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


# ---------------------------------------------------------------------------
# Extraction du titre depuis le texte
# ---------------------------------------------------------------------------

def extract_title_from_txt(text):
    lines = text.splitlines()
    title_lines = []

    for line in lines[:15]:
        line = line.strip()
        if not line or SKIP_LINE_RE.match(line):
            continue
        if INSTITUTION_RE.search(line) or "@" in line:
            break
        # Une ligne d'auteur numérotée indique que le titre est terminé
        if NUMBERED_AUTHOR_RE.match(line):
            break
        # Si la ligne précédente se termine par une préposition/conjonction,
        # forcer la continuation quelle que soit la forme de cette ligne
        if title_lines and ENDS_WITH_PREP_RE.search(title_lines[-1]):
            title_lines.append(line)
            continue
        # Stopper dès qu'on reconnaît un nom d'auteur :
        # ligne courte, majuscule initiale, pas de mot de titre courant
        words = line.split()
        if (title_lines
                and 1 <= len(words) <= 5
                and re.match(r'^[A-ZÀ-Ö]', line)
                and not re.search(r'\b(of|the|in|for|on|a|an|and|with|by|to|from)\b', line, re.I)):
            break
        title_lines.append(line)
        if len(title_lines) == 2 and not ENDS_WITH_PREP_RE.search(line):
            break

    return " ".join(title_lines)


# ---------------------------------------------------------------------------
# Extraction des auteurs depuis le texte
# ---------------------------------------------------------------------------

def _looks_like_name(line):
    """Retourne True si la ligne ressemble à un ou plusieurs noms de personnes."""
    line = line.strip()
    if not line or len(line) > 120:
        return False
    if INSTITUTION_RE.search(line):
        return False
    if "@" in line or re.search(r'\d{4,}|\[', line):
        return False
    if not re.match(r'^[A-ZÀ-Ö]', line):
        return False
    words = line.split()
    if len(words) > 20:
        return False
    # La majorité des mots doit commencer par une majuscule (noms propres),
    # à l'exclusion des mots-outils courts comme "de", "da", "van", "and"
    FUNC = {"de", "da", "van", "von", "la", "le", "du", "der", "and", "the"}
    content_words = [w for w in words if w.lower() not in FUNC]
    if not content_words:
        return False
    cap_ratio = sum(1 for w in content_words if re.match(r'^[A-ZÀ-Ö]', w)) / len(content_words)
    return cap_ratio >= 0.5


def extract_authors_from_txt(text):
    """Extrait les noms d'auteurs depuis le préambule (avant l'Abstract)."""
    abs_match = re.search(r'\bAbstract\b', text, re.IGNORECASE)
    preamble = text[: abs_match.start()] if abs_match else text[:500]

    # Extraire le titre pour pouvoir ignorer ses lignes
    title = extract_title_from_txt(text)
    title_norm = re.sub(r'\s+', ' ', title.lower().strip())

    lines = [l.strip() for l in preamble.splitlines() if l.strip()]
    past_title = False
    raw_author_lines = []

    for line in lines:
        if SKIP_LINE_RE.match(line):
            continue

        # Traiter immédiatement le format d'auteur numéroté (prioritaire sur la détection du titre)
        nm = NUMBERED_AUTHOR_RE.match(line)
        if nm:
            past_title = True
            raw_author_lines.append(nm.group(1).strip())
            continue

        # Ignorer les lignes d'institution ou d'email
        if INSTITUTION_RE.search(line) or "@" in line:
            continue

        # Détecter la fin du titre : basculer le drapeau dès qu'on dépasse le texte du titre
        if not past_title:
            line_norm = re.sub(r'\s+', ' ', line.lower().strip())
            if line_norm in title_norm or title_norm.startswith(line_norm):
                continue  # this line is part of the title
            past_title = True  # first line not in title → authors start

        if _looks_like_name(line):
            raw_author_lines.append(line)

    authors = []
    for line in raw_author_lines:
        # Séparer les noms par virgule ou "and" (ex. "Nom1, Nom2, and Nom3")
        if re.search(r',\s*[A-ZÀ-Ö]|\band\b', line):
            parts = re.split(r',\s*(?:and\s+)?|\s+and\s+', line)
            for p in parts:
                p = p.strip()
                if p and re.match(r'^[A-ZÀ-Ö]', p):
                    authors.append(p)
        else:
            authors.append(line)

    return authors if authors else []


# ---------------------------------------------------------------------------
# Extraction de l'abstract
# ---------------------------------------------------------------------------

def extract_abstract(text):
    # Chercher l'en-tête "Abstract" (simple, avec point ou tiret long)
    abs_match = re.search(r'\bAbstract\b[.\-—\s]*\n?', text, re.IGNORECASE)

    if not abs_match:
        # Fallback : trouver le premier paragraphe ressemblant à du texte de corps.
        # Ignorer les blocs de préambule (titre/auteurs/affiliations) :
        # aucune ligne du paragraphe ne doit correspondre aux motifs d'institution.
        for m in re.finditer(r'\n\n([A-Z][^\n]{50,}(?:\n[^\n]+){2,})', text):
            paragraph = m.group(1)
            lines_p = paragraph.splitlines()
            if any(INSTITUTION_RE.search(l) or "@" in l for l in lines_p):
                continue
            # Exiger qu'au moins la moitié des lignes fasse ≥ 50 caractères (corps de texte, pas des noms)
            long_lines = sum(1 for l in lines_p if len(l.strip()) >= 50)
            if long_lines < max(1, len(lines_p) // 2):
                continue
            return re.sub(r'\s+', ' ', paragraph).strip()
        return ""

    start = abs_match.end()
    remaining = text[start:]

    stop = re.search(
        r'\n\s*(?:'
        r'\d+\s*\n\s*Introduction'   # "1\n\nIntroduction"
        r'|I\.?\s+I[^\n]{0,25}'      # IEEE "I. INTRODUCTION" or "I. I NTRODUCTION"
        r'|Introduction\b'
        r'|Keywords?\s*[—:\-]'
        r'|Index\s+Terms\s*[—:\-]'
        r')',
        remaining,
        re.IGNORECASE,
    )

    raw = remaining[: stop.start()] if stop else remaining[:3000]

    # Les PDF multi-colonnes peuvent mêler texte de l'abstract et de l'Introduction.
    # Stratégie :
    #   1. Découper en paragraphes sur les lignes vides.
    #   2. Fusionner les paragraphes liés par un trait d'union en fin de ligne
    #      (ex. "has been de-" + "signed to…" → "has been designed to…").
    #   3. Conserver uniquement les paragraphes commençant par une majuscule ;
    #      les paragraphes débutant en minuscule sont du débordement de colonne
    #      provenant d'une autre section.
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', raw) if p.strip()]

    # Étape 2 : fusionner les continuations avec trait d'union
    merged = []
    i = 0
    while i < len(paragraphs):
        para = paragraphs[i]
        while (i + 1 < len(paragraphs)
               and para.endswith('-')
               and paragraphs[i + 1][:1].islower()):
            i += 1
            # Supprimer le trait d'union et joindre (le fragment complète le mot coupé)
            para = para[:-1] + paragraphs[i]
        merged.append(para)
        i += 1

    # Étape 3 : conserver les paragraphes commençant par une majuscule
    valid = [p for p in merged if re.match(r'^[A-ZÀ-Ö]', p)]
    clean = " ".join(valid) if valid else re.sub(r'\s+', ' ', raw).strip()
    return re.sub(r'\s+', ' ', clean).strip()


# ---------------------------------------------------------------------------
# Extraction de la bibliographie
# ---------------------------------------------------------------------------

BIBLIO_ENTRY_RE = re.compile(r'^[A-ZÀ-Ö][a-z\-]+,\s+[A-Z]\.', re.MULTILINE)
BIBLIO_NUMBERED_RE = re.compile(r'^\[\d+\]', re.MULTILINE)


def extract_references(text):
    # Remplacer les sauts de page (\x0c) utilisés comme séparateurs dans certains PDF
    text_clean = text.replace('\x0c', '\n')

    header = re.search(
        r'\n(?:References|Bibliography|REFERENCES|BIBLIOGRAPHY'
        r'|R\s+EFERENCES|R\s+IBLIOGRAPHY)\s*\n',
        text_clean,
    )
    if not header:
        return ""

    window_start = max(0, header.start() - 5000)
    window = text_clean[window_start:]

    # Détecter le format des entrées bibliographiques utilisé
    named_matches = list(BIBLIO_ENTRY_RE.finditer(window))
    numbered_matches = list(BIBLIO_NUMBERED_RE.finditer(window))

    # Utiliser le format numéroté s'il a plus d'occurrences après l'en-tête
    post_header = text_clean[header.end():]
    if len(BIBLIO_NUMBERED_RE.findall(post_header)) >= len(BIBLIO_ENTRY_RE.findall(post_header)):
        # Entrées numérotées : [1] ..., [2] ... — prendre le texte brut après l'en-tête
        return post_header.strip()

    # Entrées nommées ("Nom, P. ...") avec gestion du multi-colonne
    positions = [m.start() for m in named_matches]
    if not positions:
        return post_header.strip()

    entries = []
    for i, pos in enumerate(positions):
        next_pos = positions[i + 1] if i + 1 < len(positions) else len(window)
        span = window[pos:next_pos]
        # Tronquer à la première ligne vide (supprime le texte de corps intercalé)
        blank = re.search(r'\n[ \t]*\n', span)
        entry = span[: blank.start()].strip() if blank else span.strip()
        if re.search(r'\b(19|20)\d{2}\b', entry):
            entries.append(re.sub(r'\s+', ' ', entry))

    return "\n".join(entries) if entries else post_header.strip()


# ---------------------------------------------------------------------------
# Correspondance email ↔ auteur
# ---------------------------------------------------------------------------

def match_email_to_author(author_name, emails, used):
    # Normaliser : supprimer grossièrement les accents, mettre en minuscules, enlever la ponctuation
    def norm(s):
        return re.sub(r'[^a-z]', '', s.lower()
                      .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
                      .replace('à', 'a').replace('â', 'a')
                      .replace('î', 'i').replace('ï', 'i')
                      .replace('ô', 'o').replace('ù', 'u').replace('û', 'u')
                      .replace('ç', 'c'))

    parts = [norm(p) for p in re.split(r'[\s\-]+', author_name) if len(p) > 2]
    for email in emails:
        if email in used:
            continue
        local = norm(email.split("@")[0])
        # Bidirectionnel : partie auteur dans l'email OU local email dans la partie auteur
        if any(p in local or local in p for p in parts):
            return email
    return ""


# ---------------------------------------------------------------------------
# Construction du XML
# ---------------------------------------------------------------------------

def build_xml(article, txt_content, emails):
    root = Element("article")

    SubElement(root, "preamble").text = article["filename"]

    title = article["title"] or extract_title_from_txt(txt_content)
    SubElement(root, "titre").text = title

    if article["authors_raw"]:
        authors_list = [a.strip() for a in re.split(r'\s*;\s*', article["authors_raw"]) if a.strip()]
    else:
        authors_list = extract_authors_from_txt(txt_content)

    auteurs_el = SubElement(root, "auteurs")
    used_emails = set()
    for author_name in authors_list:
        auteur_el = SubElement(auteurs_el, "auteur")
        SubElement(auteur_el, "name").text = author_name
        email = match_email_to_author(author_name, emails, used_emails)
        if email:
            used_emails.add(email)
        SubElement(auteur_el, "mail").text = email

    SubElement(root, "abstract").text = extract_abstract(txt_content)
    SubElement(root, "biblio").text = extract_references(txt_content)

    return root


# ---------------------------------------------------------------------------
# Sortie TXT
# ---------------------------------------------------------------------------

def build_txt(article, txt_content, emails):
    """Produit une représentation en texte brut des métadonnées de l'article."""
    title = article["title"] or extract_title_from_txt(txt_content)

    if article["authors_raw"]:
        authors_list = [a.strip() for a in re.split(r'\s*;\s*', article["authors_raw"]) if a.strip()]
    else:
        authors_list = extract_authors_from_txt(txt_content)

    used_emails = set()
    authors_lines = []
    for author_name in authors_list:
        email = match_email_to_author(author_name, emails, used_emails)
        if email:
            used_emails.add(email)
        mail_str = f" <{email}>" if email else ""
        authors_lines.append(f"  - {author_name}{mail_str}")

    abstract = extract_abstract(txt_content)
    biblio   = extract_references(txt_content)

    sections = [
        f"FICHIER   : {article['filename']}",
        f"TITRE     : {title}",
        "AUTEURS   :\n" + ("\n".join(authors_lines) if authors_lines else "  (inconnus)"),
        "ABSTRACT  :\n  " + (abstract or "(non trouvé)"),
        "RÉFÉRENCES:\n  " + (biblio.replace("\n", "\n  ") if biblio else "(non trouvées)"),
    ]
    return "\n\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Parseur d'articles scientifiques PDF → XML ou TXT"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-x", action="store_true", help="Sortie en XML  (dans sprints/xmls/)")
    group.add_argument("-t", action="store_true", help="Sortie en TXT  (dans sprints/txts/)")
    return parser.parse_args()


def main():
    args = parse_args()

    output_dir = XML_DIR if args.x else TXT_DIR
    os.makedirs(output_dir, exist_ok=True)

    articles = list_articles(PDFS_DIR)

    for article in articles:
        base = os.path.splitext(article["filename"])[0]
        txt_content = article["txt_content"]
        emails = expand_emails(txt_content)

        if args.x:
            root = build_xml(article, txt_content, emails)
            tree = ElementTree(root)
            indent(tree, space="  ")
            output_path = os.path.join(output_dir, base + ".xml")
            tree.write(output_path, encoding="unicode", xml_declaration=True)
        else:
            content = build_txt(article, txt_content, emails)
            output_path = os.path.join(output_dir, base + ".txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)

        print(f"Généré : {output_path}")


if __name__ == "__main__":
    main()
