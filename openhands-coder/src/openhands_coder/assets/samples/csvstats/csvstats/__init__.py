def column_mean(csv_text: str, column: str) -> float:
    """Mean of a named numeric column in CSV text (first line is the header).

    Skips blank lines and cells that are not valid numbers. Raises KeyError
    if the column is not in the header; raises ValueError if the column has
    no numeric values at all.
    """
    raise NotImplementedError
