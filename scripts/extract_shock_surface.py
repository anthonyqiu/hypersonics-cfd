#!/usr/bin/env python3
from _bootstrap import bootstrap

bootstrap()

from hypersonics_cfd.shock.panel import main


if __name__ == "__main__":
    raise SystemExit(main())
