#!/usr/bin/env python3
from _bootstrap import bootstrap

bootstrap()

from hypersonics_cfd.export_density_gradient_slice import main


if __name__ == "__main__":
    raise SystemExit(main())
