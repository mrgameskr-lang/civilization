"""Write or replay an A/B/C/D peacetime economy archive."""
from . import peace62
from .depot62_cli import main


if __name__=="__main__":
    main("6.0B2",("A","B","C","D"),peace62)
