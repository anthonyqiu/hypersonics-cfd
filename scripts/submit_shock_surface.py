#!/usr/bin/env python3
from _bootstrap import bootstrap

bootstrap()

from hypersonics_cfd.submit_shock_surface import main


if __name__ == "__main__":
    raise SystemExit(main())
