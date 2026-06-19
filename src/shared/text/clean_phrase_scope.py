
from src.infrastructure.config import ConfigLoader


config_loader = ConfigLoader()
doc_types = config_loader.doc_clause_types['doc_types']


def clean_text_after_thay_the_keyword(text: str) -> str:
    """
    Remove text after the "hết hiệu lực kể từ ngày ... có hiệu lực thi hành"
    in a clause when it is not part of the reference scope.

    Args:
        text: Input text to process

    Returns:
        Processed text with irrelevant parts removed
    """
    keywords = [
        f"hết hiệu lực kể từ ngày {doc_type} này có hiệu lực thi hành"
        for doc_type in doc_types
    ]
    for keyword in keywords:
        if keyword in text:
            idx = text.find(keyword) + len(keyword)
            return text[:idx].strip()
    return text


def extract_can_cu_section(text: str) -> tuple[str, str]:
    """
    Extract the leading `Căn cứ` block from a legal document.

    Returns:
        A tuple of (can_cu_text, remaining_text).
    """
    lines = text.split('\n')
    can_cu_lines = []
    remaining_lines = []
    in_block = False

    for line in lines: 
        if line.startswith('Căn cứ'):
            in_block = True 
            can_cu_lines.append(line)
        elif in_block: 
            # Block ended - everything from here goes to remaining
            remaining_lines.append(line)
            in_block = False
        else: 
            remaining_lines.append(line)

    return '\n'.join(can_cu_lines).strip(), '\n'.join(remaining_lines).strip()
