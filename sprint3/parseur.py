import re
import os
import pymupdf
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

PDFS_DIR = os.path.join(os.path.dirname(__file__), "../pdfs")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "xmls")

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
    """Return (title, authors_raw) extracted from PDF metadata."""
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


def list_articles(pdfs_dir):
    """Scan pdfs_dir for PDF files and return article dicts."""
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
# Email extraction (handles grouped formats)
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

    # Standard emails, ignoring known digitizer domains
    bad_domains = {"diskserver.castanet.com", "next.castanet.com"}
    for m in re.finditer(r'[\w.\-]+@[\w.\-]+\.\w+', text):
        email = m.group(0).strip("().,;")
        domain = email.split("@", 1)[1] if "@" in email else ""
        if domain not in bad_domains:
            emails.append(email)

    # Deduplicate preserving order
    seen = set()
    result = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            result.append(e)
    return result


# ---------------------------------------------------------------------------
# Title extraction from txt
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
        # A numbered author line means the title is done
        if NUMBERED_AUTHOR_RE.match(line):
            break
        # If the previous title line ended with a preposition/conjunction,
        # force this line to be a continuation regardless of its shape
        if title_lines and ENDS_WITH_PREP_RE.search(title_lines[-1]):
            title_lines.append(line)
            continue
        # Stop when we hit what looks like an author name:
        # short line, starts with capital, no common "title" words
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
# Author extraction from txt
# ---------------------------------------------------------------------------

def _looks_like_name(line):
    """Return True if the line looks like one or more person names."""
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
    # Most words should start with a capital (proper nouns / names),
    # excluding short function words like "de", "da", "van", "and"
    FUNC = {"de", "da", "van", "von", "la", "le", "du", "der", "and", "the"}
    content_words = [w for w in words if w.lower() not in FUNC]
    if not content_words:
        return False
    cap_ratio = sum(1 for w in content_words if re.match(r'^[A-ZÀ-Ö]', w)) / len(content_words)
    return cap_ratio >= 0.5


def extract_authors_from_txt(text):
    """Extract author names from the preamble (before Abstract)."""
    abs_match = re.search(r'\bAbstract\b', text, re.IGNORECASE)
    preamble = text[: abs_match.start()] if abs_match else text[:500]

    # Extract the title so we can skip those lines
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

        # Detect end of title: once we've passed the title text, switch flag
        if not past_title:
            line_norm = re.sub(r'\s+', ' ', line.lower().strip())
            if line_norm in title_norm or title_norm.startswith(line_norm):
                continue  # this line is part of the title
            past_title = True  # first line not in title → authors start

        if _looks_like_name(line):
            raw_author_lines.append(line)

    authors = []
    for line in raw_author_lines:
        # Split comma/and-separated names (e.g. "Name1, Name2, and Name3")
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
# Abstract extraction
# ---------------------------------------------------------------------------

def extract_abstract(text):
    # Look for "Abstract" header (plain, with dot, or with em-dash)
    abs_match = re.search(r'\bAbstract\b[.\-—\s]*\n?', text, re.IGNORECASE)

    if not abs_match:
        # Fallback: find the first paragraph that looks like body text.
        # Skip preamble blocks (title/author/affiliation) by requiring that
        # none of the paragraph lines match institution patterns.
        for m in re.finditer(r'\n\n([A-Z][^\n]{50,}(?:\n[^\n]+){2,})', text):
            paragraph = m.group(1)
            lines_p = paragraph.splitlines()
            if any(INSTITUTION_RE.search(l) or "@" in l for l in lines_p):
                continue
            # Require at least half the lines to be ≥ 50 chars (body text, not names)
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

    # Multi-column PDFs can mix abstract text with Introduction text.
    # Strategy:
    #   1. Split into paragraphs on blank lines.
    #   2. Merge consecutive paragraphs joined by a hyphen line-break
    #      (e.g. "has been de-" + "signed to…" → "has been designed to…").
    #   3. Keep only paragraphs that start with an uppercase letter;
    #      lowercase-start paragraphs that are NOT hyphen continuations
    #      are right-column overflow from another section.
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', raw) if p.strip()]

    # Step 2: merge hyphen continuations
    merged = []
    i = 0
    while i < len(paragraphs):
        para = paragraphs[i]
        while (i + 1 < len(paragraphs)
               and para.endswith('-')
               and paragraphs[i + 1][:1].islower()):
            i += 1
            # Strip the hyphen and join (the fragment completes the cut word)
            para = para[:-1] + paragraphs[i]
        merged.append(para)
        i += 1

    # Step 3: keep uppercase-starting paragraphs
    valid = [p for p in merged if re.match(r'^[A-ZÀ-Ö]', p)]
    clean = " ".join(valid) if valid else re.sub(r'\s+', ' ', raw).strip()
    return re.sub(r'\s+', ' ', clean).strip()


# ---------------------------------------------------------------------------
# Bibliography extraction
# ---------------------------------------------------------------------------

BIBLIO_ENTRY_RE = re.compile(r'^[A-ZÀ-Ö][a-z\-]+,\s+[A-Z]\.', re.MULTILINE)
BIBLIO_NUMBERED_RE = re.compile(r'^\[\d+\]', re.MULTILINE)


def extract_references(text):
    # Handle form feeds (\x0c) used as page separators in some PDFs
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

    # Detect which entry format is used
    named_matches = list(BIBLIO_ENTRY_RE.finditer(window))
    numbered_matches = list(BIBLIO_NUMBERED_RE.finditer(window))

    # Use numbered format if it has more matches after the header
    post_header = text_clean[header.end():]
    if len(BIBLIO_NUMBERED_RE.findall(post_header)) >= len(BIBLIO_ENTRY_RE.findall(post_header)):
        # Numbered entries: [1] ..., [2] ..., etc. — take raw text after header
        return post_header.strip()

    # Named entries ("Lastname, F. ...") with multi-column awareness
    positions = [m.start() for m in named_matches]
    if not positions:
        return post_header.strip()

    entries = []
    for i, pos in enumerate(positions):
        next_pos = positions[i + 1] if i + 1 < len(positions) else len(window)
        span = window[pos:next_pos]
        # Truncate at the first blank line (drops intervening body text)
        blank = re.search(r'\n[ \t]*\n', span)
        entry = span[: blank.start()].strip() if blank else span.strip()
        if re.search(r'\b(19|20)\d{2}\b', entry):
            entries.append(re.sub(r'\s+', ' ', entry))

    return "\n".join(entries) if entries else post_header.strip()


# ---------------------------------------------------------------------------
# Email ↔ author matching
# ---------------------------------------------------------------------------

def match_email_to_author(author_name, emails, used):
    # Normalise: remove accents crudely, lowercase, strip punctuation
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
        # Bidirectional: author part in email OR email local in author part
        if any(p in local or local in p for p in parts):
            return email
    return ""


# ---------------------------------------------------------------------------
# XML construction
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
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    articles = list_articles(PDFS_DIR)

    for article in articles:
        base = os.path.splitext(article["filename"])[0]
        txt_path = os.path.join(PDFS_DIR, base + ".txt")

        txt_content = ""
        emails = []
        if os.path.exists(txt_path):
            with open(txt_path, encoding="utf-8") as f:
                txt_content = f.read()
            emails = expand_emails(txt_content)
        else:
            print(f"[WARN] fichier texte introuvable : {txt_path}")

        root = build_xml(article, txt_content, emails)

        tree = ElementTree(root)
        indent(tree, space="  ")

        output_path = os.path.join(OUTPUT_DIR, base + ".xml")
        tree.write(output_path, encoding="unicode", xml_declaration=True)
        print(f"Généré : {output_path}")


if __name__ == "__main__":
    main()
