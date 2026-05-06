import re
import os
import sys
import argparse
import pymupdf
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

PDFS_DIR = os.path.join(os.path.dirname(__file__), "../pdfs")
XML_DIR = os.path.join(os.path.dirname(__file__), "xmls")
TXT_DIR = os.path.join(os.path.dirname(__file__), "txts")

INSTITUTION_RE = re.compile(
    r'\b(?:universit|institu|laborator|laboratoire|\blab\b|cnrs|école|polytechn|'
    r'department|dept\.|faculty|grenoble|montréal|avignon|marseille|rennes|'
    r'vannes|upf|unam|iula|dtic|lia\b|cnrs|ea\s*\d+|umr\s*\d+|cp\s*\d+|'
    r'communicated by|^\d{4,5}|^bp\d|\bInc\b|\bCorp\b|\bLtd\b|\bLLC\b)',
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
    """Retourne (titre, auteurs_bruts) extraits des métadonnées du PDF."""
    try:
        doc = pymupdf.open(pdf_path)
        meta = doc.metadata
        doc.close()
    except Exception:
        return "", ""

    title_raw = (meta.get("title") or "").strip()
    author_raw = (meta.get("author") or "").strip()

    # Reject garbage titles (TeX output paths, backslash commands)
    if "/" in title_raw or title_raw.startswith("\\"):
        title_raw = ""

    # Reject digitizer/producer author entries (contain an email)
    if "@" in author_raw:
        author_raw = ""

    # pymupdf uses ";" as separator; normalise to match the rest of the code
    # (split on ";" already handled downstream via re.split(r'\s*;\s*', ...))
    return title_raw, author_raw


def clean_pdf_text(text):
    """Corrige les accents séparés, supprime les symboles bizarres et les caractères de contrôle invalides pour le XML."""
    if not text:
        return text
    # Fix accents
    text = text.replace("´e", "é").replace("´E", "É")
    text = text.replace("`e", "è").replace("`E", "È")
    text = text.replace("´a", "á").replace("´A", "Á")
    text = text.replace("`a", "à").replace("`A", "À")
    text = text.replace("´u", "ú").replace("´U", "Ú")
    text = text.replace("`u", "ù").replace("`U", "Ù")
    text = text.replace("´o", "ó").replace("´O", "Ó")
    text = text.replace("´i", "í").replace("´I", "Í")
    text = text.replace("´c", "ć").replace("´C", "Ć")
    text = text.replace("¨e", "ë").replace("¨E", "Ë")
    text = text.replace("¨i", "ï").replace("¨I", "Ï")
    
    # Suppression des symboles bizarres (notes de musique servant de marqueurs, etc.)
    text = text.replace("♮", "").replace("♭", "").replace("∗", "")
    
    # Suppression des caractères de contrôle invalides pour XML 1.0 (ASCII 0-31 sauf tab, nl, cr)
    # L'erreur "Char value 18" correspond à \x12 (DC2)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    
    return text


def convert_pdf_to_txt(pdf_path, txt_path):
    """Extrait le texte d'un PDF et le sauvegarde dans un fichier TXT."""
    print(f"Extraction du texte depuis {pdf_path}...")
    try:
        doc = pymupdf.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text() + "\n"
        doc.close()
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text
    except Exception as e:
        print(f"[ERREUR] Impossible de convertir {pdf_path}: {e}")
        return ""


def list_articles(pdfs_dir):
    """Scanne pdfs_dir à la recherche de fichiers PDF et retourne des dictionnaires d'articles."""
    articles = []
    for fname in sorted(os.listdir(pdfs_dir)):
        if not fname.lower().endswith(".pdf"):
            continue
        pdf_path = os.path.join(pdfs_dir, fname)
        title, authors_raw = extract_pdf_metadata(pdf_path)
        articles.append({
            "filename": fname,
            "title": title,
            "authors_raw": authors_raw,
        })
    return articles


# ---------------------------------------------------------------------------
# Extraction des emails (gère les formats groupés)
# ---------------------------------------------------------------------------

def expand_emails(text):
    emails = []

    # Grouped curly braces: {name1, name2}@domain.com
    for m in re.finditer(r'\{([^}]+)\}@([\w.\-]+)', text):
        domain = m.group(2)
        for name in m.group(1).split(","):
            name = name.strip()
            if name:
                emails.append(f"{name}@{domain}")

    # Grouped parentheses on one line or split across newline:
    # (a,b,c)\n@domain  or  (a,b,c)@domain
    for m in re.finditer(r'\(([^)]+)\)\s*\n?@([\w.\-]+)', text):
        domain = m.group(2)
        for name in m.group(1).split(","):
            name = name.strip()
            # Keep only entries that look like email local parts (contain a dot or dash)
            if name and ("." in name or "-" in name):
                emails.append(f"{name}@{domain}")

    # Emails standards, en ignorant les domaines de numérisation connus
    bad_domains = {"diskserver.castanet.com", "next.castanet.com"}
    for m in re.finditer(r'[\w.\-]+@[\w.\-]+\.\w+', text):
        email = m.group(0).strip("().,;")
        domain = email.split("@", 1)[1] if "@" in email else ""
        if domain not in bad_domains:
            emails.append(email)

    # Déduplication en préservant l'ordre
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
        # Une ligne d'auteur numérotée signifie que le titre est fini
        if NUMBERED_AUTHOR_RE.match(line):
            break
        # Si la ligne de titre précédente se terminait par une préposition/conjonction,
        # on force cette ligne à être une continuation
        if title_lines and ENDS_WITH_PREP_RE.search(title_lines[-1]):
            title_lines.append(line)
            continue
        # On s'arrête si on tombe sur ce qui ressemble à un nom d'auteur :
        # ligne courte, commence par une majuscule, pas de mots communs de titre
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
    if "@" in line or re.search(r'\d{4,}', line):
        return False
    if not re.match(r'^[A-ZÀ-Ö]', line):
        return False
    words = line.split()
    if len(words) > 20 or len(words) < 2:
        return False
    # La plupart des mots doivent commencer par une majuscule,
    # en excluant les mots de fonction courts comme "de", "and", etc.
    FUNC = {"de", "da", "van", "von", "la", "le", "du", "der", "and", "the"}
    content_words = [w for w in words if w.lower() not in FUNC]
    if not content_words:
        return False
    cap_ratio = sum(1 for w in content_words if re.match(r'^[A-ZÀ-Ö]', w)) / len(content_words)
    return cap_ratio >= 0.5


def get_preamble(text):
    abs_match = re.search(r'\bAbstract\b[.\-—\s]*\n?', text, re.IGNORECASE)
    if abs_match:
        return text[:abs_match.start()]

    lines = text.split('\n')
    for i, line in enumerate(lines):
        if i < 2:
            continue
        # Check if line looks like body text (long prose line)
        if len(line.strip()) > 70 and re.match(r'^[A-ZÀ-Ö]', line.strip()):
            if not INSTITUTION_RE.search(line) and "@" not in line:
                return '\n'.join(lines[:i]) + '\n'
                
    return text[:500]


def extract_authors_from_txt(text):
    """Extrait les noms d'auteurs du préambule (avant l'Abstract)."""
    preamble = get_preamble(text)

    # Extraction du titre pour pouvoir ignorer ces lignes
    title = extract_title_from_txt(text)
    title_norm = re.sub(r'\s+', ' ', title.lower().strip())

    lines = [l.strip() for l in preamble.splitlines() if l.strip()]
    past_title = False
    raw_author_lines = []

    for line in lines:
        if SKIP_LINE_RE.match(line):
            continue

        # Handle numbered author format right away (overrides title detection)
        nm = NUMBERED_AUTHOR_RE.match(line)
        if nm:
            past_title = True
            raw_author_lines.append(nm.group(1).strip())
            continue

        # Skip institution/email lines
        if INSTITUTION_RE.search(line) or "@" in line:
            continue

        # Détection de la fin du titre : une fois qu'on a passé le texte du titre, on change de mode
        if not past_title:
            line_norm = re.sub(r'\s+', ' ', line.lower().strip())
            if line_norm in title_norm or title_norm.startswith(line_norm):
                continue  # this line is part of the title
            past_title = True  # première ligne hors titre → début des auteurs

        if _looks_like_name(line):
            raw_author_lines.append(line)

    authors = []
    for line in raw_author_lines:
        # Sépare les noms séparés par des virgules ou "and"
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
# Extraction du Résumé (Abstract)
# ---------------------------------------------------------------------------

def extract_abstract(text):
    abs_match = re.search(r'\bAbstract\b[.\-—\s]*\n?', text, re.IGNORECASE)
    if abs_match:
        start = abs_match.end()
    else:
        start = len(get_preamble(text))

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

    # Les PDF multi-colonnes peuvent mélanger le texte du résumé avec l'Introduction.
    # Stratégie :
    #   1. Séparer en paragraphes sur les lignes vides.
    #   2. Fusionner les paragraphes consécutifs joints par un trait d'union.
    #   3. Ne garder que les paragraphes commençant par une majuscule.
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', raw) if p.strip()]

    # Étape 2 : fusion des continuations avec trait d'union
    merged = []
    i = 0
    while i < len(paragraphs):
        para = paragraphs[i]
        while (i + 1 < len(paragraphs)
               and para.endswith('-')
               and paragraphs[i + 1][:1].islower()):
            i += 1
            # Supprimer le trait d'union et fusionner
            para = para[:-1] + paragraphs[i]
        merged.append(para)
        i += 1

    # Étape 3 : garder les paragraphes commençant par une majuscule
    valid = [p for p in merged if re.match(r'^[A-ZÀ-Ö]', p)]
    clean = " ".join(valid) if valid else re.sub(r'\s+', ' ', raw).strip()
    return re.sub(r'\s+', ' ', clean).strip()


# ---------------------------------------------------------------------------
# Extraction de la Bibliographie
# ---------------------------------------------------------------------------

BIBLIO_ENTRY_RE = re.compile(r'^[A-ZÀ-Ö][a-z\-]+,\s+[A-Z]\.', re.MULTILINE)
BIBLIO_NUMBERED_RE = re.compile(r'^\[\d+\]', re.MULTILINE)


def extract_references(text):
    # Gère les sauts de page (\x0c) présents dans certains PDF
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

    # Détecte le format d'entrée utilisé
    named_matches = list(BIBLIO_ENTRY_RE.finditer(window))
    numbered_matches = list(BIBLIO_NUMBERED_RE.finditer(window))

    # Use numbered format if it has more matches after the header
    post_header = text_clean[header.end():]
    if len(BIBLIO_NUMBERED_RE.findall(post_header)) >= len(BIBLIO_ENTRY_RE.findall(post_header)):
        # Entrées numérotées : [1] ..., [2] ..., etc. — on prend le texte brut après l'en-tête
        return post_header.strip()

    # Entrées nommées ("Nom, F. ...") avec gestion des colonnes
    positions = [m.start() for m in named_matches]
    if not positions:
        return post_header.strip()

    entries = []
    for i, pos in enumerate(positions):
        next_pos = positions[i + 1] if i + 1 < len(positions) else len(window)
        span = window[pos:next_pos]
        # Tronque à la première ligne vide (élimine le texte du corps intercalé)
        blank = re.search(r'\n[ \t]*\n', span)
        entry = span[: blank.start()].strip() if blank else span.strip()
        if re.search(r'\b(19|20)\d{2}\b', entry):
            entries.append(re.sub(r'\s+', ' ', entry))

    return "\n".join(entries) if entries else post_header.strip()


# ---------------------------------------------------------------------------
# Correspondance Email ↔ auteur
# ---------------------------------------------------------------------------

def match_email_to_author(author_name, emails, used):
    # Normalisation : supprime les accents, passage en minuscules, nettoyage ponctuation
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
        # Bidirectionnel : partie auteur dans l'email OU partie locale de l'email dans l'auteur
        if any(p in local or local in p for p in parts):
            return email
    return ""


# ---------------------------------------------------------------------------
# Extraction des sections (Intro, Corps, Conclusion, Discussion)
# ---------------------------------------------------------------------------

def clean_body_section(section_text, text_clean):
    if not section_text: return section_text
    named_matches = list(BIBLIO_ENTRY_RE.finditer(section_text))
    numbered_matches = list(BIBLIO_NUMBERED_RE.finditer(section_text))
    
    header = re.search(r'\n[ \t]*(?:[0-9IVX]+\.?\s*)?(?:References?|Bibliography|R\s+EFERENCES|R\s+IBLIOGRAPHY)\s*\n', text_clean, re.IGNORECASE)
    post_header = text_clean[header.end():] if header else ""
    
    use_numbered = len(BIBLIO_NUMBERED_RE.findall(post_header)) >= len(BIBLIO_ENTRY_RE.findall(post_header)) if header else (len(numbered_matches) > len(named_matches))
    
    matches = numbered_matches if use_numbered else named_matches
    if not matches: return section_text
        
    to_remove = []
    for m in matches:
        pos = m.start()
        blank = re.search(r'\n[ \t]*\n', section_text[pos:])
        end_pos = pos + blank.start() if blank else len(section_text)
        entry = section_text[pos:end_pos].strip()
        if use_numbered or re.search(r'\b(19|20)\d{2}\b', entry):
            to_remove.append((pos, end_pos))
            
    cleaned = []
    last_end = 0
    for start, end in to_remove:
        cleaned.append(section_text[last_end:start])
        last_end = end
    cleaned.append(section_text[last_end:])
    
    return re.sub(r'\n{3,}', '\n\n', "".join(cleaned).strip())

def extract_body_sections(text):
    sections = {
        "introduction": "",
        "corps": "",
        "discussion": "",
        "conclusion": ""
    }
    
    text_clean = text.replace('\x0c', '\n')
    
    intro_words = r'(?:Introduction|INTRODUCTION)'
    disc_words = r'(?:Discussions?|DISCUSSIONS?)'
    conc_words = r'(?:Conclusions?|Concluding Remarks?|Discussion and Future Work|CONCLUSIONS?|CONCLUDING REMARKS)'
    ref_words = r'(?:References?|Bibliography|REFERENCES?|BIBLIOGRAPHY)'
    
    prefix = r'\n[ \t]*(?:[0-9IVX]+\.?\s*\n?[ \t]*)?'
    
    intro_match = re.search(prefix + intro_words + r'\b[^\n]*\n', text_clean)
    disc_match = re.search(prefix + disc_words + r'\b[^\n]*\n', text_clean)
    conc_match = re.search(prefix + conc_words + r'\b[^\n]*\n', text_clean)
    ref_match = re.search(prefix + ref_words + r'\b[^\n]*\n', text_clean)
    
    pos_intro = intro_match.start() if intro_match else -1
    pos_intro_end = intro_match.end() if intro_match else -1
    pos_disc = disc_match.start() if disc_match else -1
    pos_disc_end = disc_match.end() if disc_match else -1
    pos_conc = conc_match.start() if conc_match else -1
    pos_conc_end = conc_match.end() if conc_match else -1
    pos_ref = ref_match.start() if ref_match else len(text_clean)
    
    if pos_intro > pos_ref: pos_intro = -1; pos_intro_end = -1
    if pos_disc > pos_ref: pos_disc = -1; pos_disc_end = -1
    if pos_conc > pos_ref: pos_conc = -1; pos_conc_end = -1
    
    # Résolution des chevauchements
    if pos_intro > -1 and pos_intro == pos_disc: pos_disc = -1; pos_disc_end = -1
    if pos_disc > -1 and pos_disc == pos_conc: pos_disc = -1; pos_disc_end = -1
    
    if pos_intro > -1:
        end_intro = min([p for p in [pos_disc, pos_conc, pos_ref, len(text_clean)] if p > pos_intro_end], default=len(text_clean))
        next_sec_match = re.search(r'\n[ \t]*(?:[0-9IVX]{1,3}\.?\s+)[A-Z][a-zA-Z ]+\b[^\n]*\n', text_clean[pos_intro_end:end_intro])
        if next_sec_match:
            end_intro = pos_intro_end + next_sec_match.start()
        sections["introduction"] = text_clean[pos_intro_end:end_intro].strip()
        
    if pos_disc > -1:
        end_disc = min([p for p in [pos_conc, pos_ref, len(text_clean)] if p > pos_disc_end], default=len(text_clean))
        sections["discussion"] = clean_body_section(text_clean[pos_disc_end:end_disc].strip(), text_clean)
        
    if pos_conc > -1:
        end_conc = pos_ref if pos_ref > pos_conc_end else len(text_clean)
        sections["conclusion"] = clean_body_section(text_clean[pos_conc_end:end_conc].strip(), text_clean)
        
    start_corps = pos_intro_end if pos_intro > -1 else -1
    if start_corps > -1:
        end_intro_max = min([p for p in [pos_disc, pos_conc, pos_ref, len(text_clean)] if p > pos_intro_end], default=len(text_clean))
        next_sec_match = re.search(r'\n[ \t]*(?:[0-9IVX]{1,3}\.?\s+)[A-Z][a-zA-Z ]+\b[^\n]*\n', text_clean[pos_intro_end:])
        if next_sec_match and (pos_intro_end + next_sec_match.start()) < end_intro_max:
            start_corps = pos_intro_end + next_sec_match.start()
        else:
            start_corps = end_intro_max
    else:
        abs_match = re.search(r'\bAbstract\b[.\-—\s]*\n?', text_clean, re.IGNORECASE)
        start_corps = abs_match.end() + 1000 if abs_match else 1000

    end_corps = min([p for p in [pos_disc, pos_conc, pos_ref, len(text_clean)] if p > start_corps], default=len(text_clean))
    
    if start_corps > -1 and end_corps > start_corps:
        if start_corps > len(text_clean): start_corps = max(0, len(text_clean) - 1000)
        sections["corps"] = clean_body_section(text_clean[start_corps:end_corps].strip(), text_clean)
        
    return sections


# ---------------------------------------------------------------------------
# Extraction des Affiliations
# ---------------------------------------------------------------------------

def extract_affiliations_from_txt(text, known_emails):
    preamble = get_preamble(text)

    title = extract_title_from_txt(text)
    title_norm = re.sub(r'\s+', ' ', title.lower().strip())

    lines = [l.strip() for l in preamble.splitlines() if l.strip()]
    past_title = False
    
    blocks = []
    current_authors = []
    current_affil = []
    current_emails = []

    def save_block():
        nonlocal current_authors, current_affil, current_emails
        if current_authors or current_affil or current_emails:
            blocks.append((current_authors, ", ".join(current_affil), current_emails))
        current_authors = []
        current_affil = []
        current_emails = []

    for line in lines:
        if SKIP_LINE_RE.match(line):
            continue

        if not past_title:
            line_norm = re.sub(r'\s+', ' ', line.lower().strip())
            if line_norm in title_norm or title_norm.startswith(line_norm):
                continue
            past_title = True

        found_email = False
        line_clean = line.replace(" ", "")
        for e in known_emails:
            if e in line_clean:
                if e not in current_emails:
                    current_emails.append(e)
                found_email = True
        
        if found_email or "@" in line:
            continue

        nm = NUMBERED_AUTHOR_RE.match(line)
        if nm:
            if current_affil or current_emails:
                save_block()
            current_authors.append(nm.group(1).strip())
            continue

        if INSTITUTION_RE.search(line):
            if current_emails:
                save_block()
            current_affil.append(line)
            continue

        if _looks_like_name(line):
            if current_affil or current_emails:
                save_block()
            current_authors.append(line)
            continue

        if current_affil and not _looks_like_name(line):
            if len(line) > 2 and not line.startswith(('\\', '[', '(', '*')):
                current_affil.append(line)
            continue
            
    save_block()

    author_affil_map = {}
    email_affil_map = {}
    all_affils = []
    
    for author_lines, affil, emails_in_block in blocks:
        if affil:
            all_affils.append(affil)
            
        for e in emails_in_block:
            email_affil_map[e] = affil
            
        for line in author_lines:
            line = re.sub(r'[\\[\]*†‡,]+$', '', line).strip()
            if re.search(r',\s*[A-ZÀ-Ö]|\band\b', line):
                parts = re.split(r',\s*(?:and\s+)?|\s+and\s+', line)
                for p in parts:
                    p = re.sub(r'[\\[\]*†‡,]+$', '', p).strip()
                    if p and re.match(r'^[A-ZÀ-Ö]', p):
                        author_affil_map[p] = affil
            else:
                author_affil_map[line] = affil
                
    unique_affils = []
    for a in all_affils:
        if a not in unique_affils:
            unique_affils.append(a)
            
    global_affil = ", ".join(unique_affils) if unique_affils else ""
    return author_affil_map, email_affil_map, global_affil


# ---------------------------------------------------------------------------
# Construction XML
# ---------------------------------------------------------------------------

def build_xml(article, txt_content, emails):
    root = Element("article")

    SubElement(root, "preambule").text = article["filename"]

    title = article["title"] or extract_title_from_txt(txt_content)
    SubElement(root, "titre").text = title

    if article["authors_raw"]:
        authors_list = [a.strip() for a in re.split(r'\s*;\s*', article["authors_raw"]) if a.strip()]
    else:
        authors_list = extract_authors_from_txt(txt_content)

    auteurs_el = SubElement(root, "auteurs")
    used_emails = set()
    
    author_affil_map, email_affil_map, global_affil = extract_affiliations_from_txt(txt_content, emails)
    
    def norm(s):
        return re.sub(r'[^a-z]', '', s.lower()
                      .replace('é', 'e').replace('è', 'e').replace('ê', 'e')
                      .replace('à', 'a').replace('â', 'a')
                      .replace('î', 'i').replace('ï', 'i')
                      .replace('ô', 'o').replace('ù', 'u').replace('û', 'u')
                      .replace('ç', 'c'))

    def find_affiliation(author_name, author_email):
        if author_email and author_email in email_affil_map and email_affil_map[author_email]:
            return email_affil_map[author_email]
            
        n_author = norm(author_name)
        for k, v in author_affil_map.items():
            if norm(k) == n_author:
                return v
        for k, v in author_affil_map.items():
            if norm(author_name.split()[-1]) in norm(k) and len(norm(author_name.split()[-1])) > 2:
                return v
        return global_affil

    for author_name in authors_list:
        auteur_el = SubElement(auteurs_el, "auteur")
        SubElement(auteur_el, "name").text = author_name
        email = match_email_to_author(author_name, emails, used_emails)
        if email:
            used_emails.add(email)
        SubElement(auteur_el, "mail").text = email
        SubElement(auteur_el, "affiliation").text = find_affiliation(author_name, email)

    SubElement(root, "abstract").text = extract_abstract(txt_content)
    
    sections = extract_body_sections(txt_content)
    SubElement(root, "introduction").text = sections["introduction"]
    SubElement(root, "corps").text = sections["corps"]
    SubElement(root, "conclusion").text = sections["conclusion"]
    SubElement(root, "discussion").text = sections["discussion"]
    
    SubElement(root, "biblio").text = extract_references(txt_content)

    return root


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    pdf_dir = args.pdf_dir
    
    output_dir = XML_DIR if args.x else TXT_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    selected_fnames = choose_pdfs(pdf_dir)
    if not selected_fnames:
        return

    for fname in selected_fnames:
        base = os.path.splitext(fname)[0]
        pdf_path = os.path.join(pdf_dir, fname)
        txt_path = os.path.join(pdf_dir, base + ".txt")

        txt_content = ""
        generated_txt = False
        if not os.path.exists(txt_path):
            txt_content = convert_pdf_to_txt(pdf_path, txt_path)
            generated_txt = True
        else:
            with open(txt_path, encoding="utf-8") as f:
                txt_content = f.read()
                
        txt_content = clean_pdf_text(txt_content)
        emails = expand_emails(txt_content)
        
        title, authors_raw = extract_pdf_metadata(pdf_path)
        article = {
            "filename": fname,
            "title": title,
            "authors_raw": authors_raw,
        }

        if args.x:
            root = build_xml(article, txt_content, emails)
            tree = ElementTree(root)
            indent(tree, space="  ")
            output_path = os.path.join(output_dir, base + ".xml")
            # unicode et xml_declaration pour assurer un encodage propre
            tree.write(output_path, encoding="unicode", xml_declaration=True, short_empty_elements=False)
        else:
            content = build_txt(article, txt_content, emails)
            output_path = os.path.join(output_dir, base + ".txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)

        print(f"Généré : {output_path}")

        if generated_txt and os.path.exists(txt_path):
            os.remove(txt_path)




# ---------------------------------------------------------------------------
# Menu Interactif
# ---------------------------------------------------------------------------

def choose_pdfs(pdfs_dir):
    """Affiche un menu textuel et retourne la liste des noms de fichiers PDF choisis."""
    all_pdfs = sorted([f for f in os.listdir(pdfs_dir) if f.lower().endswith(".pdf")])

    if not all_pdfs:
        print(f"Aucun PDF trouvé dans {pdfs_dir}")
        return []

    print("\n╔══════════════════════════════════════════════════╗")
    print("║      Parseur d'articles scientifiques            ║")
    print("╚══════════════════════════════════════════════════╝\n")
    print("PDF disponibles :\n")
    for i, fname in enumerate(all_pdfs, 1):
        print(f"  [{i:2d}] {fname}")
    print()
    print("Choisissez les PDF à parser :")
    print("  • Numéros séparés par des virgules  →  ex. : 1,3,5")
    print("  • Une plage                         →  ex. : 2-5")
    print("  • Combinaison                       →  ex. : 1,3-5,7")
    print("  • Tous                              →  tout  /  all")
    print("  • Quitter                           →  q\n")

    while True:
        try:
            choice = input("Votre choix : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return []

        if choice.lower() in ('q', 'quit', 'exit'):
            print("Annulé.")
            return []

        if choice.lower() in ('tout', 'all', '*'):
            print(f"\n{len(all_pdfs)} PDF sélectionnés.\n")
            return all_pdfs

        selected_indices = set()
        valid = True

        for part in choice.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                try:
                    a, b = part.split('-', 1)
                    a, b = int(a.strip()), int(b.strip())
                    if 1 <= a <= b <= len(all_pdfs):
                        selected_indices.update(range(a, b + 1))
                    else:
                        print(f"  ✗ Plage invalide : {part}  (numéros entre 1 et {len(all_pdfs)})")
                        valid = False
                        break
                except ValueError:
                    print(f"  ✗ Format invalide : '{part}'")
                    valid = False
                    break
            else:
                try:
                    n = int(part)
                    if 1 <= n <= len(all_pdfs):
                        selected_indices.add(n)
                    else:
                        print(f"  ✗ Numéro invalide : {n}  (entre 1 et {len(all_pdfs)})")
                        valid = False
                        break
                except ValueError:
                    print(f"  ✗ Format invalide : '{part}'")
                    valid = False
                    break

        if valid and selected_indices:
            selected = [all_pdfs[i - 1] for i in sorted(selected_indices)]
            print(f"\nPDF sélectionnés : {', '.join(selected)}\n")
            return selected
        elif valid:
            print("  ✗ Aucune sélection valide, veuillez réessayer.")


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
    
    sections = extract_body_sections(txt_content)
    biblio = extract_references(txt_content)

    out_sections = [
        f"FICHIER   : {article['filename']}",
        f"TITRE     : {title}",
        "AUTEURS   :\n" + ("\n".join(authors_lines) if authors_lines else "  (inconnus)"),
        "ABSTRACT  :\n  " + (abstract or "(non trouvé)"),
        "INTRODUCTION:\n  " + (sections['introduction'].replace("\n", "\n  ") if sections['introduction'] else "(non trouvée)"),
        "CORPS:\n  " + (sections['corps'].replace("\n", "\n  ") if sections['corps'] else "(non trouvé)"),
        "CONCLUSION:\n  " + (sections['conclusion'].replace("\n", "\n  ") if sections['conclusion'] else "(non trouvée)"),
        "DISCUSSION:\n  " + (sections['discussion'].replace("\n", "\n  ") if sections['discussion'] else "(non trouvée)"),
        "RÉFÉRENCES:\n  " + (biblio.replace("\n", "\n  ") if biblio else "(non trouvées)"),
    ]
    return "\n\n".join(out_sections) + "\n"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Parseur d'articles scientifiques PDF → XML ou TXT"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-x", action="store_true", help="Sortie en XML")
    group.add_argument("-t", action="store_true", help="Sortie en TXT")
    parser.add_argument("pdf_dir", nargs='?', default=PDFS_DIR, help="Répertoire des PDF (défaut: ../pdfs)")
    return parser.parse_args()


if __name__ == "__main__":
    main()

