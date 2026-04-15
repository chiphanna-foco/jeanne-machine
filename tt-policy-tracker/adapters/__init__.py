from adapters.base import BaseAdapter, RawDoc
from adapters.openstates import OpenStatesAdapter
from adapters.congress import CongressAdapter
from adapters.federal_register import FederalRegisterAdapter

__all__ = [
    "BaseAdapter",
    "RawDoc",
    "OpenStatesAdapter",
    "CongressAdapter",
    "FederalRegisterAdapter",
]
