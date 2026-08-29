import sys
import os
if sys.path[0] == '':
    sys.path.pop(0)
cwd = os.getcwd()
if cwd in sys.path:
    sys.path.remove(cwd)
import alembic.config
alembic.config.main()
