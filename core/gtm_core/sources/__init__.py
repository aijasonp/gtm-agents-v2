"""Signal sourcing from public, dated, structured sources: SEC EDGAR filings, company newsrooms
and news feeds, and public job board APIs. Every finding carries its source URL and date."""
from .model import Finding

__all__ = ["Finding"]
