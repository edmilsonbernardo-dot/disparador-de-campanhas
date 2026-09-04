"""Utilidades: leitura tolerante de CSV com colunas nome/email."""
import csv
import io
import re
import unicodedata

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

NAME_HEADER_CANDIDATES = {"nome", "name", "nome completo", "cliente", "contato"}
EMAIL_HEADER_CANDIDATES = {"email", "e-mail", "e_mail", "mail", "endereco de email"}


def _normalize(text: str) -> str:
    text = text.strip().lower()
    text = "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )
    return text


def _detect_columns(fieldnames):
    name_col = None
    email_col = None
    for field in fieldnames or []:
        norm = _normalize(field)
        if norm in NAME_HEADER_CANDIDATES and name_col is None:
            name_col = field
        if norm in EMAIL_HEADER_CANDIDATES and email_col is None:
            email_col = field
    return name_col, email_col


def parse_contacts_csv(file_storage):
    """Lê um FileStorage de CSV e retorna (contatos, avisos).

    contatos: lista de dicts {"name": str, "email": str}
    avisos: lista de strings descrevendo linhas ignoradas/problemas
    """
    raw = file_storage.read()
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Não foi possível ler a codificação do arquivo CSV.")

    # Detecta o delimitador (vírgula ou ponto-e-vírgula, comum em exportações BR).
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("O CSV está vazio ou sem cabeçalho.")

    name_col, email_col = _detect_columns(reader.fieldnames)
    if not email_col:
        raise ValueError(
            "Não encontrei uma coluna de e-mail no CSV. "
            "Use um cabeçalho como 'email' ou 'e-mail'. "
            f"Colunas encontradas: {', '.join(reader.fieldnames)}"
        )

    contacts = []
    warnings = []
    seen_emails = set()

    for i, row in enumerate(reader, start=2):  # linha 1 é o cabeçalho
        email = (row.get(email_col) or "").strip()
        name = (row.get(name_col) or "").strip() if name_col else ""

        if not email:
            warnings.append(f"Linha {i}: sem e-mail, ignorada.")
            continue
        if not EMAIL_RE.match(email):
            warnings.append(f"Linha {i}: e-mail inválido ('{email}'), ignorada.")
            continue
        email_lower = email.lower()
        if email_lower in seen_emails:
            warnings.append(f"Linha {i}: e-mail duplicado ('{email}'), ignorada.")
            continue
        seen_emails.add(email_lower)

        contacts.append({"name": name or email.split("@")[0], "email": email})

    return contacts, warnings
