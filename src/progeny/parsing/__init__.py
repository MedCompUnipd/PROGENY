"""Format-specific readers used by PROGENY's public artifacts."""

from progeny.parsing.fasta import FastaParser
from progeny.parsing.gaf import GafParser
from progeny.parsing.owl import OwlLoader
from progeny.parsing.uniprot import UniProtDatParser, UniProtMetadataIndex
from progeny.records import UniProtSection

__all__ = [
    "FastaParser",
    "GafParser",
    "OwlLoader",
    "UniProtDatParser",
    "UniProtMetadataIndex",
    "UniProtSection",
]
