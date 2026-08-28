"""Create and initialize the SQL Server learning database."""

import os

from .repository import initialize_database

DEFAULT_CONNECTION = (
    "DRIVER={SQL Server};"
    "SERVER=127.0.0.1,1433;DATABASE=MesSimulator;"
    "UID=sa;PWD=MesLearning_2026!"
)


def main() -> None:
    initialize_database(os.getenv("MES_SQL_CONNECTION", DEFAULT_CONNECTION))
    print("MesSimulator database initialized.")


if __name__ == "__main__":
    main()
