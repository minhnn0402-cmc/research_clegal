import re


def is_vanban_hop_nhat(cls_so_hieu: str) -> bool:
  """
  Check if the document is a hop nhat document.
  """
  return "VBHN" in cls_so_hieu.upper()


def get_content_vbhn(text: str) -> str:
  """
  Get the content of a VBHN document.
  """
  match = re.search(r"\bCăn\s+cứ\b", text, flags=re.IGNORECASE)

  if match:
    return text[:match.start()]

  return text
